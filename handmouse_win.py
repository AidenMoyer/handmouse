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
            "-loglevel", "quiet",
            "-f", "dshow",
            "-video_size", f"{width}x{height}",
            "-framerate", str(fps),
            "-i", f"video={device_name}",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-",
        ]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self._frame = None
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        while self._running:
            raw = self._proc.stdout.read(self.frame_bytes)
            if len(raw) < self.frame_bytes:
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape((self.height, self.width, 3))
            with self._lock:
                self._frame = frame

    def read(self):
        with self._lock:
            return self._frame is not None, (self._frame.copy() if self._frame is not None else None)

    def release(self):
        self._running = False
        self._proc.terminate()


# ── mouse controller ──────────────────────────────────────────────────────────

class MouseController:
    SCROLL_SCALE = 15  # pixels of hand movement per scroll line

    def __init__(self, monitor, cam_w, cam_h, mirror, sensitivity=1.0):
        self.mon = monitor          # screeninfo Monitor object
        self.cw, self.ch = cam_w, cam_h
        self.mirror = mirror
        self.sensitivity = sensitivity
        self.sx = EMA(0.35)
        self.sy = EMA(0.35)
        self._scroll_anchor = None
        self._left_down = False
        self._right_down = False

    def _map(self, nx, ny):
        """Map normalized [0,1] hand coords → absolute screen pixel on target monitor."""
        if self.mirror:
            nx = 1.0 - nx
        margin = max(0.02, 0.15 / self.sensitivity)
        nx = (nx - margin) / (1 - 2 * margin)
        ny = (ny - margin) / (1 - 2 * margin)
        nx = max(0.0, min(1.0, nx))
        ny = max(0.0, min(1.0, ny))
        # map to this monitor's absolute coordinates
        x = self.mon.x + int(nx * self.mon.width)
        y = self.mon.y + int(ny * self.mon.height)
        return x, y

    def update(self, lm_norm, gesture):
        palm = _palm_center(lm_norm)
        sx, sy = self._map(palm[0], palm[1])
        sx = int(self.sx.update(sx))
        sy = int(self.sy.update(sy))

        if gesture == "move":
            if self._left_down:
                pyautogui.mouseUp(button="left")
                self._left_down = False
            if self._right_down:
                pyautogui.mouseUp(button="right")
                self._right_down = False
            self._scroll_anchor = None
            pyautogui.moveTo(sx, sy)

        elif gesture == "left":
            pyautogui.moveTo(sx, sy)
            if not self._left_down:
                pyautogui.mouseDown(button="left")
                self._left_down = True

        elif gesture == "right":
            pyautogui.moveTo(sx, sy)
            if not self._right_down:
                pyautogui.mouseDown(button="right")
                self._right_down = True

        elif gesture == "scroll":
            if self._left_down:
                pyautogui.mouseUp(button="left")
                self._left_down = False
            if self._right_down:
                pyautogui.mouseUp(button="right")
                self._right_down = False
            if self._scroll_anchor is None:
                self._scroll_anchor = (palm[0], palm[1])
            else:
                dy_norm = palm[1] - self._scroll_anchor[1]
                scroll_lines = -dy_norm * self.ch / self.SCROLL_SCALE
                if abs(scroll_lines) >= 1:
                    pyautogui.scroll(int(scroll_lines))
                    self._scroll_anchor = (palm[0], palm[1])

        else:
            self.cleanup()
            self._scroll_anchor = None

    def cleanup(self):
        if self._left_down:
            pyautogui.mouseUp(button="left")
            self._left_down = False
        if self._right_down:
            pyautogui.mouseUp(button="right")
            self._right_down = False


# ── hand selector ─────────────────────────────────────────────────────────────

def pick_hand(result, prefer: str):
    """
    Return (landmarks, handedness_label) for the preferred hand, or None.

    MediaPipe reports handedness from the image perspective (not mirrored),
    so "Left" from the model = the person's right hand when camera is mirrored.
    We flip the label to match the user's physical hand.
    """
    if not result.hand_landmarks:
        return None, None

    for lm_list, handed_list in zip(result.hand_landmarks, result.handedness):
        # top category_name is "Left" or "Right" (camera perspective)
        raw_label = handed_list[0].category_name  # "Left" or "Right"
        # flip: camera-left = user's right (typical mirrored selfie-cam)
        user_label = "Right" if raw_label == "Left" else "Left"

        if prefer == "any" or user_label.lower() == prefer.lower():
            return lm_list, user_label

    return None, None


# ── GPU delegate helper ───────────────────────────────────────────────────────

def build_hands(use_gpu: bool):
    """Build HandLandmarker, trying GPU delegate first if requested."""
    delegates = ([BaseOptions.Delegate.GPU, BaseOptions.Delegate.CPU]
                 if use_gpu else [BaseOptions.Delegate.CPU])

    for delegate in delegates:
        try:
            opts = mp_vision.HandLandmarkerOptions(
                base_options=BaseOptions(
                    model_asset_path=MODEL_PATH,
                    delegate=delegate,
                ),
                num_hands=2,  # detect up to 2 so hand selection works
                min_hand_detection_confidence=0.6,
                min_tracking_confidence=0.5,
                running_mode=mp_vision.RunningMode.IMAGE,
            )
            detector = mp_vision.HandLandmarker.create_from_options(opts)
            label = "GPU" if delegate == BaseOptions.Delegate.GPU else "CPU"
            print(f"Hand detector: {label}")
            return detector
        except Exception as e:
            if delegate == BaseOptions.Delegate.GPU:
                print(f"GPU delegate unavailable ({e}), falling back to CPU")
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
                    help="Mouse sensitivity multiplier")
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
    print(f"Hand:    {args.hand}   Sensitivity: {args.sensitivity:.1f}×")
    print("Starting — Ctrl+C to stop")

    cam  = FFmpegCamera(args.camera, args.width, args.height, args.fps)
    ctrl = MouseController(mon, args.width, args.height, args.mirror, args.sensitivity)
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

    try:
        while True:
            ok, frame = cam.read()
            if not ok or frame is None:
                time.sleep(0.01)
                continue

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = hands.detect(mp_image)

            lm_list, hand_label = pick_hand(result, args.hand)

            if lm_list is not None:
                lm = [(lk.x, lk.y, lk.z) for lk in lm_list]
                gesture, _ = classify(lm)
                ctrl.update(lm, gesture)
            else:
                ctrl.cleanup()

            if args.show:
                disp = frame.copy()
                if args.mirror:
                    disp = cv2.flip(disp, 1)
                # draw all detected hands; highlight chosen one
                for i, (hl, hd) in enumerate(zip(result.hand_landmarks, result.handedness)):
                    raw = hd[0].category_name
                    user = "Right" if raw == "Left" else "Left"
                    chosen = (args.hand == "any" or user.lower() == args.hand)
                    color = (0, 255, 0) if chosen else (100, 100, 100)
                    for lk in hl:
                        cx = int((1 - lk.x if args.mirror else lk.x) * args.width)
                        cy = int(lk.y * args.height)
                        cv2.circle(disp, (cx, cy), 4, color, -1)
                    # label
                    wrist = hl[0]
                    wx = int((1 - wrist.x if args.mirror else wrist.x) * args.width)
                    wy = int(wrist.y * args.height) + 20
                    cv2.putText(disp, user, (wx, wy),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

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
