"""handmouse_win.py — Windows-native hand tracking mouse controller.

Uses ffmpeg (DShow) to capture camera frames, MediaPipe Tasks hand landmarker
for tracking, and pyautogui to control the Windows mouse. No WSL required.

Features:
  - Multi-monitor: pick which display to control
  - Hand selection: track left hand, right hand, or whichever appears first
  - GPU acceleration: tries MediaPipe GPU delegate (NVIDIA/AMD via OpenCL/DirectX),
    falls back to CPU automatically

Usage:
    python handmouse_win.py [options]

    --list              List cameras and monitors, then exit
    --camera NAME       DShow device name (default: "1080P Pro Stream")
    --width / --height  Capture resolution (default 640x480)
    --fps N             Capture frame rate (default 30)
    --mirror            Flip camera horizontally (default on)
    --show              Show preview window with landmark overlay
    --monitor N         Which monitor to control (0 = primary, 1 = second, ...)
    --hand left|right|any  Which hand to track (default: any)
    --sensitivity N     Mouse sensitivity multiplier (default 1.0)
    --gpu               Try GPU delegate for hand detection; falls back to CPU
"""

import argparse
import os
import subprocess
import sys
import threading
import time

import cv2
import mediapipe as mp
import numpy as np
import pyautogui
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python import vision as mp_vision
from screeninfo import get_monitors

from gestures import classify, _palm_center

# ── ffmpeg path (patched by setup_windows.ps1) ────────────────────────────────
FFMPEG = r"C:\Users\TylerMass\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffmpeg.exe"

MODEL_PATH = os.path.join(os.path.dirname(__file__), "hand_landmarker.task")

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

# MediaPipe was designed for ~640px input; anything larger wastes CPU and can
# crash. Frames captured at higher resolution are downscaled to this before
# inference — landmark coords are normalised so accuracy is unaffected.
INFER_W, INFER_H = 640, 480


# ── monitor helpers ───────────────────────────────────────────────────────────

def sorted_monitors():
    """Return monitors sorted: primary first, then by x position."""
    mons = get_monitors()
    return sorted(mons, key=lambda m: (not m.is_primary, m.x))


def monitor_label(i, m):
    tag = " (primary)" if m.is_primary else ""
    return f"{i}: {m.width}×{m.height} at ({m.x},{m.y}){tag}  [{m.name}]"


# ── EMA smoother ──────────────────────────────────────────────────────────────

class EMA:
    def __init__(self, alpha=0.35):
        self.alpha = alpha
        self.val = None

    def update(self, v):
        self.val = v if self.val is None else self.alpha * v + (1 - self.alpha) * self.val
        return self.val


# ── ffmpeg camera reader ──────────────────────────────────────────────────────

class FFmpegCamera:
    def __init__(self, device_name, width, height, fps):
        self.width = width
        self.height = height
        self.frame_bytes = width * height * 3
        cmd = [
            FFMPEG,
            # low-latency flags: disable internal buffering so frames arrive in real-time
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-probesize", "32",
            "-analyzeduration", "0",
            "-loglevel", "quiet",
            "-f", "dshow",
            "-video_size", f"{width}x{height}",
            "-framerate", str(fps),
            "-i", f"video={device_name}",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            # no output buffering either
            "-flush_packets", "1",
            "-",
        ]
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=0,  # unbuffered pipe on our side too
        )
        self._frame = None
        self._seq   = 0   # increments every time a new frame is stored
        self._lock  = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        """Read ffmpeg output as fast as possible, always keeping only the latest frame.

        If inference is slow and frames pile up in the OS pipe buffer, we drain
        them all and only expose the newest one — this prevents lag from building up.
        """
        buf = bytearray()
        while self._running:
            chunk = self._proc.stdout.read(65536)
            if not chunk:
                break
            buf.extend(chunk)
            # consume ALL complete frames from the buffer, keeping only the last
            while len(buf) >= self.frame_bytes:
                raw = bytes(buf[:self.frame_bytes])
                del buf[:self.frame_bytes]
                frame = np.frombuffer(raw, dtype=np.uint8).reshape(
                    (self.height, self.width, 3))
                with self._lock:
                    self._frame = frame
                    self._seq  += 1

    def read(self):
        with self._lock:
            if self._frame is None:
                return False, None
            return True, self._frame.copy()

    def read_seq(self):
        """Return (seq, frame) — caller can compare seq to detect a new frame."""
        with self._lock:
            if self._frame is None:
                return 0, None
            return self._seq, self._frame.copy()

    def release(self):
        self._running = False
        self._proc.terminate()


# ── mouse controller ──────────────────────────────────────────────────────────

class MouseController:
    SCROLL_LINES_PER_UNIT = 150  # scroll lines per full normalised unit of hand travel
    SCROLL_SCALE_ABS      = 15  # absolute mode: camera pixels of movement per scroll line

    def __init__(self, monitor, cam_w, cam_h, mirror, sensitivity=1.0,
                 mode="relative", all_monitors=None):
        self.mon = monitor          # screeninfo Monitor (absolute mode maps to this)
        self.cw, self.ch = cam_w, cam_h
        self.mirror = mirror
        self.sensitivity = sensitivity
        self.mode = mode            # "relative" | "absolute"

        # Virtual desktop bounds (relative mode can roam all monitors)
        mons = all_monitors or [monitor]
        vd_x1 = min(m.x for m in mons)
        vd_y1 = min(m.y for m in mons)
        vd_x2 = max(m.x + m.width  for m in mons)
        vd_y2 = max(m.y + m.height for m in mons)
        self._vd = (vd_x1, vd_y1, vd_x2, vd_y2)

        # Speed reference: always scale against the primary monitor so that
        # cursor speed is the same regardless of how many monitors are connected
        # or what their sizes are.
        primary = next((m for m in mons if m.is_primary), mons[0])
        self._ref_w = primary.width
        self._ref_h = primary.height

        # Max hand movement per frame (in normalised units) before we clamp.
        # At 30 fps a comfortable fast swipe ≈ 0.08/frame; 0.15 allows sprint-speed
        # without letting a corner-snap teleport the cursor across monitors.
        self._MAX_DELTA = 0.15

        # ── relative mode state ──
        self._px = EMA(0.4)
        self._py = EMA(0.4)
        self._prev_palm  = None   # None = anchor fresh on next frame
        self._scroll_acc = 0.0   # fractional scroll accumulator

        # ── absolute mode state ──
        self.sx = EMA(0.35)       # screen-coord smoothers
        self.sy = EMA(0.35)
        self._scroll_anchor = None

        self._left_down  = False
        self._right_down = False

    # ── shared helpers ────────────────────────────────────────────────────────

    def _norm_x(self, nx):
        return 1.0 - nx if self.mirror else nx

    def cleanup(self):
        if self._left_down:
            pyautogui.mouseUp(button="left")
            self._left_down = False
        if self._right_down:
            pyautogui.mouseUp(button="right")
            self._right_down = False

    def update(self, lm_norm, gesture):
        palm = _palm_center(lm_norm)
        if self.mode == "absolute":
            self._update_abs(palm, gesture)
        else:
            self._update_rel(palm, gesture)

    # ── absolute mode ─────────────────────────────────────────────────────────

    def _map(self, nx, ny):
        """Map normalised [0,1] hand coords → absolute pixel on the target monitor."""
        nx = self._norm_x(nx)
        margin = max(0.02, 0.15 / self.sensitivity)
        nx = max(0.0, min(1.0, (nx - margin) / (1 - 2 * margin)))
        ny = max(0.0, min(1.0, (ny - margin) / (1 - 2 * margin)))
        return self.mon.x + int(nx * self.mon.width), self.mon.y + int(ny * self.mon.height)

    def _update_abs(self, palm, gesture):
        sx, sy = self._map(palm[0], palm[1])
        sx = int(self.sx.update(sx))
        sy = int(self.sy.update(sy))

        if gesture == "move":
            if self._left_down:
                pyautogui.mouseUp(button="left");  self._left_down = False
            if self._right_down:
                pyautogui.mouseUp(button="right"); self._right_down = False
            self._scroll_anchor = None
            pyautogui.moveTo(sx, sy)

        elif gesture == "left":
            pyautogui.moveTo(sx, sy)
            if not self._left_down:
                pyautogui.mouseDown(button="left"); self._left_down = True

        elif gesture == "right":
            pyautogui.moveTo(sx, sy)
            if not self._right_down:
                pyautogui.mouseDown(button="right"); self._right_down = True

        elif gesture == "scroll":
            if self._left_down:
                pyautogui.mouseUp(button="left");  self._left_down = False
            if self._right_down:
                pyautogui.mouseUp(button="right"); self._right_down = False
            if self._scroll_anchor is None:
                self._scroll_anchor = (palm[0], palm[1])
            else:
                dy_norm = palm[1] - self._scroll_anchor[1]
                lines = -dy_norm * self.ch / self.SCROLL_SCALE_ABS
                if abs(lines) >= 1:
                    pyautogui.scroll(int(lines))
                    self._scroll_anchor = (palm[0], palm[1])

        elif gesture == "fist":
            self.cleanup(); self._scroll_anchor = None

        # "none" — hold position without acting

    # ── relative (trackpad) mode ──────────────────────────────────────────────

    def _reset_tracking(self):
        self._prev_palm = None
        self._px.val    = None
        self._py.val    = None

    def _move_delta(self, dpx, dpy):
        """Apply a normalised-coord delta, clamped to the virtual desktop.

        Reads the real OS cursor position each call instead of tracking internally —
        this ensures any drift (DPI rounding, another app nudging the cursor, etc.)
        never accumulates and the cursor can't suddenly jump to a stale position.
        """
        # tiny dead zone — swallows detection noise during precision clicks
        # without being noticeable during normal movement (~1-2px at default settings)
        DEAD = 0.0004
        if abs(dpx) < DEAD: dpx = 0.0
        if abs(dpy) < DEAD: dpy = 0.0
        if dpx == 0.0 and dpy == 0.0:
            return
        # clamp to prevent corner-snap teleporting the cursor
        dpx = max(-self._MAX_DELTA, min(self._MAX_DELTA, dpx))
        dpy = max(-self._MAX_DELTA, min(self._MAX_DELTA, dpy))
        cx, cy = pyautogui.position()   # always ground truth from the OS
        vx1, vy1, vx2, vy2 = self._vd
        nx = max(vx1, min(vx2 - 1, cx + dpx * self.sensitivity * self._ref_w))
        ny = max(vy1, min(vy2 - 1, cy + dpy * self.sensitivity * self._ref_h))
        pyautogui.moveTo(int(nx), int(ny))

    def _update_rel(self, palm, gesture):
        px = self._px.update(self._norm_x(palm[0]))
        py = self._py.update(palm[1])

        if gesture in ("move", "left", "right", "scroll"):
            if self._prev_palm is None:
                # First frame after hand appears / fist released:
                # anchor here so the cursor doesn't jump.
                self._prev_palm = (px, py)
                if gesture == "left" and not self._left_down:
                    pyautogui.mouseDown(button="left");  self._left_down = True
                elif gesture == "right" and not self._right_down:
                    pyautogui.mouseDown(button="right"); self._right_down = True
                return

            dpx = px - self._prev_palm[0]
            dpy = py - self._prev_palm[1]
            self._prev_palm = (px, py)

            if gesture == "move":
                if self._left_down:
                    pyautogui.mouseUp(button="left");  self._left_down = False
                if self._right_down:
                    pyautogui.mouseUp(button="right"); self._right_down = False
                self._move_delta(dpx, dpy)

            elif gesture == "left":
                if self._right_down:
                    pyautogui.mouseUp(button="right"); self._right_down = False
                self._move_delta(dpx, dpy)
                if not self._left_down:
                    pyautogui.mouseDown(button="left"); self._left_down = True

            elif gesture == "right":
                if self._left_down:
                    pyautogui.mouseUp(button="left");  self._left_down = False
                self._move_delta(dpx, dpy)
                if not self._right_down:
                    pyautogui.mouseDown(button="right"); self._right_down = True

            elif gesture == "scroll":
                if self._left_down:
                    pyautogui.mouseUp(button="left");  self._left_down = False
                if self._right_down:
                    pyautogui.mouseUp(button="right"); self._right_down = False
                # accumulate fractional scroll — int() per frame would always be 0
                self._scroll_acc += -dpy * self.SCROLL_LINES_PER_UNIT * self.sensitivity
                lines = int(self._scroll_acc)
                if lines:
                    pyautogui.scroll(lines)
                    self._scroll_acc -= lines   # keep the remainder

        elif gesture == "fist":
            self.cleanup()
            self._reset_tracking()
            self._scroll_acc = 0.0

        else:  # "none"
            self._reset_tracking()
            self._scroll_acc = 0.0


# ── hand selector ─────────────────────────────────────────────────────────────

def pick_hand(result, prefer: str, mirror: bool):
    """
    Return (landmarks, user_hand_label) for the preferred hand, or (None, None).

    We always pass the raw (non-mirrored) BGR frame to MediaPipe.  In a standard
    front-facing camera the image is already a mirror of the scene, so what the
    camera puts on the LEFT side of the frame is the person's physical RIGHT hand.
    MediaPipe's model is trained to account for this, but its label is still from
    the camera's point of view — so "Left" from the model = person's right hand.
    We therefore always flip the label to match physical reality.

    The display mirror flag does NOT affect this: we never mirror the image before
    handing it to MediaPipe, only before showing it on screen.
    """
    if not result.hand_landmarks:
        return None, None

    best_lm, best_label, best_score = None, None, 0.0

    for lm_list, handed_list in zip(result.hand_landmarks, result.handedness):
        cat = handed_list[0]
        score = cat.score
        if score < 0.6:
            continue
        raw_label = cat.category_name          # "Left"/"Right" from camera view
        user_label = "Right" if raw_label == "Left" else "Left"   # always flip

        if prefer == "any" or user_label.lower() == prefer.lower():
            if score > best_score:
                best_lm, best_label, best_score = lm_list, user_label, score

    return best_lm, best_label


# ── GPU delegate helper ───────────────────────────────────────────────────────

def build_hands(use_gpu: bool):
    """Build HandLandmarker in VIDEO mode, trying GPU delegate first if requested.

    VIDEO mode maintains a persistent streaming pipeline whose worker threads are
    reused across frames — IMAGE mode creates new threads per call and leaks them,
    causing the process to slow to a crawl and eventually crash with STATUS_TOO_MANY_THREADS.
    """
    delegates = ([BaseOptions.Delegate.GPU, BaseOptions.Delegate.CPU]
                 if use_gpu else [BaseOptions.Delegate.CPU])

    for delegate in delegates:
        try:
            opts = mp_vision.HandLandmarkerOptions(
                base_options=BaseOptions(
                    model_asset_path=MODEL_PATH,
                    delegate=delegate,
                ),
                num_hands=2,
                min_hand_detection_confidence=0.6,
                min_tracking_confidence=0.5,
                running_mode=mp_vision.RunningMode.VIDEO,
            )
            detector = mp_vision.HandLandmarker.create_from_options(opts)
            label = "GPU" if delegate == BaseOptions.Delegate.GPU else "CPU"
            print(f"Hand detector: {label} (VIDEO mode)")
            return detector
        except Exception as e:
            if delegate == BaseOptions.Delegate.GPU:
                print(f"GPU delegate unavailable — the standard 'pip install mediapipe' "
                      f"on Windows is compiled without GPU support. Running on CPU+XNNPACK.")
            else:
                raise
    raise RuntimeError("Could not initialise hand detector on any delegate")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="handmouse — hand tracking mouse controller")
    ap.add_argument("--camera", default="1080P Pro Stream",
                    help="DShow device name")
    ap.add_argument("--width",  type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fps",    type=int, default=30)
    ap.add_argument("--mirror", action="store_true", default=True)
    ap.add_argument("--no-mirror", dest="mirror", action="store_false")
    ap.add_argument("--show",   action="store_true", help="Show preview window")
    ap.add_argument("--monitor", type=int, default=0,
                    help="Monitor index to control (0 = primary)")
    ap.add_argument("--hand", choices=["left", "right", "any"], default="any",
                    help="Which hand to track (default: any)")
    ap.add_argument("--sensitivity", type=float, default=1.0,
                    help="Mouse sensitivity multiplier (0.1–20.0; higher = less hand movement needed)")
    ap.add_argument("--mode", choices=["relative", "absolute"], default="relative",
                    help="relative = trackpad style, moves freely across all monitors; "
                         "absolute = hand position maps directly to selected monitor")
    ap.add_argument("--gpu", action="store_true",
                    help="Try GPU delegate (NVIDIA/AMD); falls back to CPU")
    ap.add_argument("--list", action="store_true",
                    help="List cameras and monitors then exit")
    args = ap.parse_args()

    if args.list:
        print("── Cameras ──")
        r = subprocess.run(
            [FFMPEG, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True, text=True
        )
        import re
        for name in re.findall(r'"([^"]+)"\s+\(video\)', r.stderr + r.stdout):
            print(f"  {name}")
        print("\n── Monitors ──")
        for i, m in enumerate(sorted_monitors()):
            print(f"  {monitor_label(i, m)}")
        return

    monitors = sorted_monitors()
    if args.monitor >= len(monitors):
        print(f"Monitor {args.monitor} not found — only {len(monitors)} monitor(s) detected.")
        sys.exit(1)
    mon = monitors[args.monitor]

    print(f"Monitor {args.monitor}: {mon.width}×{mon.height} at ({mon.x},{mon.y})"
          f"{'  (primary)' if mon.is_primary else ''}")
    print(f"Camera:  {args.camera!r} @ {args.width}×{args.height} {args.fps}fps")
    print(f"Hand:    {args.hand}   Sensitivity: {args.sensitivity:.1f}×   Mode: {args.mode}")
    print("Starting — Ctrl+C to stop")

    cam  = FFmpegCamera(args.camera, args.width, args.height, args.fps)
    ctrl = MouseController(mon, args.width, args.height, args.mirror, args.sensitivity,
                           mode=args.mode, all_monitors=monitors)
    hands = build_hands(args.gpu)

    # wait for first frame
    print("Waiting for camera...", end="", flush=True)
    for _ in range(100):
        ok, _ = cam.read()
        if ok:
            break
        time.sleep(0.05)
    else:
        print("\nERROR: no frames. Check device name with --list")
        cam.release()
        sys.exit(1)
    print(" ready!")

    last_seq    = 0
    no_hand_t   = None   # time when hand was last lost
    _t0         = time.monotonic()  # reference for VIDEO-mode timestamps
    BUTTON_RELEASE_GRACE = 0.6   # seconds before releasing held buttons after hand disappears
    try:
        while True:
            seq, frame = cam.read_seq()
            if frame is None:
                time.sleep(0.005)
                continue
            if seq == last_seq:
                time.sleep(0.003)
                continue
            last_seq = seq

            # Downscale to inference size before MediaPipe.
            # MediaPipe was designed for ~640px; sending full 1080p frames wastes
            # CPU and can crash due to its internal fixed-size buffers.
            if args.width > INFER_W or args.height > INFER_H:
                scale = min(INFER_W / args.width, INFER_H / args.height)
                infer = cv2.resize(frame, (0, 0), fx=scale, fy=scale,
                                   interpolation=cv2.INTER_LINEAR)
            else:
                infer = frame
            rgb = cv2.cvtColor(infer, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            ts_ms = int((time.monotonic() - _t0) * 1000)
            result = hands.detect_for_video(mp_image, ts_ms)

            lm_list, hand_label = pick_hand(result, args.hand, args.mirror)

            if lm_list is not None:
                no_hand_t = None          # hand is back — reset the timer
                lm = [(lk.x, lk.y, lk.z) for lk in lm_list]
                gesture, _ = classify(lm)
                ctrl.update(lm, gesture)
            else:
                # cursor stays at last position — track how long the hand has been gone
                now = time.monotonic()
                if no_hand_t is None:
                    no_hand_t = now
                    if ctrl.mode == "relative":
                        ctrl._reset_tracking()
                elif now - no_hand_t >= BUTTON_RELEASE_GRACE:
                    ctrl.cleanup()

            if args.show:
                disp = frame.copy()
                if args.mirror:
                    disp = cv2.flip(disp, 1)
                for hl, hd in zip(result.hand_landmarks, result.handedness):
                    cat = hd[0]
                    raw = cat.category_name
                    user = ("Right" if raw == "Left" else "Left") if args.mirror else raw
                    chosen = (args.hand == "any" or user.lower() == args.hand)
                    # dim low-confidence detections visually
                    alpha = cat.score
                    color = (int(0 * alpha), int(255 * alpha), int(0 * alpha)) if chosen \
                            else (80, 80, 80)
                    for lk in hl:
                        cx = int((1 - lk.x if args.mirror else lk.x) * args.width)
                        cy = int(lk.y * args.height)
                        cv2.circle(disp, (cx, cy), 4, color, -1)
                    wrist = hl[0]
                    wx = int((1 - wrist.x if args.mirror else wrist.x) * args.width)
                    wy = int(wrist.y * args.height) + 20
                    cv2.putText(disp, f"{user} {cat.score:.0%}", (wx, wy),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

                cv2.imshow("handmouse", disp)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        ctrl.cleanup()
        cam.release()
        hands.close()
        if args.show:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
