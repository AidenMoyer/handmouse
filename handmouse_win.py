"""handmouse_win.py — Windows-native hand tracking mouse controller.

Uses ffmpeg (DShow) to capture camera frames, MediaPipe Hands for tracking,
and pyautogui to control the Windows mouse. No WSL required.

Usage:
    python handmouse_win.py [--camera "1080P Pro Stream"] [--width 640] [--height 480]
                            [--fps 30] [--mirror] [--show]

Gesture map:
    Open hand (all fingers up)        → move mouse
    Pinch thumb+index                 → left click (hold to drag)
    Pinch thumb+middle + move         → scroll
    Pinch thumb+pinky                 → right click
    Fist / no hand                    → idle
"""

import argparse
import os
import subprocess
import sys
import threading
import time
import numpy as np
import pyautogui
import mediapipe as mp
from mediapipe.tasks.python import vision as mp_vision
from mediapipe.tasks.python import BaseOptions
import cv2

from gestures import classify, _palm_center, WRIST

MODEL_PATH = os.path.join(os.path.dirname(__file__), "hand_landmarker.task")

FFMPEG = r"C:\Users\TylerMass\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffmpeg.exe"

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0


# ── smoothing ──────────────────────────────────────────────────────────────────
class EMA:
    def __init__(self, alpha=0.4):
        self.alpha = alpha
        self.val = None

    def update(self, v):
        self.val = v if self.val is None else self.alpha * v + (1 - self.alpha) * self.val
        return self.val


# ── ffmpeg frame reader ────────────────────────────────────────────────────────
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


# ── gesture → mouse ────────────────────────────────────────────────────────────
class MouseController:
    SCROLL_SCALE = 15   # pixels of hand movement per scroll line

    def __init__(self, screen_w, screen_h, cam_w, cam_h, mirror, sensitivity=1.0):
        self.sw, self.sh = screen_w, screen_h
        self.cw, self.ch = cam_w, cam_h
        self.mirror = mirror
        self.sensitivity = sensitivity  # shrinks the dead-zone margin so movement maps to more screen
        self.sx = EMA(0.35)
        self.sy = EMA(0.35)
        self._prev_gesture = "none"
        self._scroll_anchor = None   # (palm_x, palm_y) when scroll started
        self._left_down = False
        self._right_down = False

    def _map(self, nx, ny):
        # nx, ny are normalized [0,1] from mediapipe
        if self.mirror:
            nx = 1.0 - nx
        # margin shrinks with sensitivity so higher sensitivity = less hand movement needed
        margin = max(0.02, 0.15 / self.sensitivity)
        nx = (nx - margin) / (1 - 2 * margin)
        ny = (ny - margin) / (1 - 2 * margin)
        nx = max(0.0, min(1.0, nx))
        ny = max(0.0, min(1.0, ny))
        return int(nx * self.sw), int(ny * self.sh)

    def update(self, lm_norm, gesture):
        palm = _palm_center(lm_norm)   # normalized coords
        sx, sy = self._map(palm[0], palm[1])
        sx = int(self.sx.update(sx))
        sy = int(self.sy.update(sy))

        prev = self._prev_gesture

        if gesture == "move":
            # release any held buttons
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
                # positive dy_norm = hand moved down = scroll down
                scroll_lines = -dy_norm * self.ch / self.SCROLL_SCALE
                if abs(scroll_lines) >= 1:
                    pyautogui.scroll(int(scroll_lines))
                    self._scroll_anchor = (palm[0], palm[1])

        else:  # none / idle
            if self._left_down:
                pyautogui.mouseUp(button="left")
                self._left_down = False
            if self._right_down:
                pyautogui.mouseUp(button="right")
                self._right_down = False
            self._scroll_anchor = None

        self._prev_gesture = gesture

    def cleanup(self):
        if self._left_down:
            pyautogui.mouseUp(button="left")
        if self._right_down:
            pyautogui.mouseUp(button="right")


# ── main ───────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", default="1080P Pro Stream",
                    help="DShow device name (run: ffmpeg -list_devices true -f dshow -i dummy)")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--mirror", action="store_true", default=True,
                    help="Mirror camera (default on, use --no-mirror to disable)")
    ap.add_argument("--no-mirror", dest="mirror", action="store_false")
    ap.add_argument("--show", action="store_true", help="Show camera window (requires display)")
    ap.add_argument("--sensitivity", type=float, default=1.0,
                    help="Mouse sensitivity multiplier (default 1.0, higher = less hand movement needed)")
    ap.add_argument("--list", action="store_true",
                    help="List available DShow camera devices and exit")
    args = ap.parse_args()

    if args.list:
        result = subprocess.run(
            [FFMPEG, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True, text=True
        )
        print(result.stderr)
        return

    sw, sh = pyautogui.size()
    print(f"Screen: {sw}x{sh}")
    print(f"Camera: {args.camera!r} @ {args.width}x{args.height} {args.fps}fps  sensitivity={args.sensitivity:.1f}x")
    print("Starting — Ctrl+C to stop")

    cam = FFmpegCamera(args.camera, args.width, args.height, args.fps)
    ctrl = MouseController(sw, sh, args.width, args.height, args.mirror, args.sensitivity)

    hand_options = mp_vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=MODEL_PATH),
        num_hands=1,
        min_hand_detection_confidence=0.6,
        min_tracking_confidence=0.5,
        running_mode=mp_vision.RunningMode.IMAGE,
    )
    hands = mp_vision.HandLandmarker.create_from_options(hand_options)

    # wait for first frame
    print("Waiting for camera feed...", end="", flush=True)
    for _ in range(100):
        ok, _ = cam.read()
        if ok:
            break
        time.sleep(0.05)
    else:
        print("\nERROR: no frames from camera. Check device name with --list")
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

            if result.hand_landmarks:
                hl = result.hand_landmarks[0]
                lm = [(lk.x, lk.y, lk.z) for lk in hl]
                gesture, _ = classify(lm)
                ctrl.update(lm, gesture)
            else:
                ctrl.cleanup()  # release any held buttons when hand lost

            if args.show:
                disp = frame.copy()
                if args.mirror:
                    disp = cv2.flip(disp, 1)
                if result.hand_landmarks:
                    for lk in result.hand_landmarks[0]:
                        cx = int((1 - lk.x if args.mirror else lk.x) * args.width)
                        cy = int(lk.y * args.height)
                        cv2.circle(disp, (cx, cy), 4, (0, 255, 0), -1)
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
