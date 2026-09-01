# handmouse

Control your Windows mouse with hand gestures using your webcam. No WSL required — runs natively on Windows.

## Quick install (one command)

Open PowerShell and run:

```powershell
git clone https://github.com/moyeraiden1014/handmouse.git
cd handmouse
.\setup_windows.ps1
```

That's it. A **handmouse** shortcut will appear on your Desktop.

## What it does

| Gesture | Action |
|---|---|
| Open hand (all fingers extended) | Move mouse |
| Pinch **thumb + index** | Left click (hold to drag) |
| Pinch **thumb + middle** + move | Scroll |
| Pinch **thumb + pinky** | Right click |
| Fist / no hand visible | Idle |

## GUI

Double-click the **handmouse** desktop shortcut (or run `handmouse_gui.py`) to open the control panel:

- **Camera** — pick from all detected webcams
- **Resolution** — VGA up to 4K (camera must support it)
- **FPS** — 15 / 24 / 30 / 60
- **Sensitivity** — how much hand movement maps to screen movement
- **Mirror** — flip horizontally (on by default, natural selfie-cam feel)
- **Preview window** — show the camera feed with landmark dots

## Manual usage

```powershell
cd handmouse

# list cameras
.\venv-win\Scripts\python.exe handmouse_win.py --list

# run (default settings)
.\venv-win\Scripts\python.exe handmouse_win.py

# full HD, higher sensitivity, show preview
.\venv-win\Scripts\python.exe handmouse_win.py --width 1280 --height 720 --sensitivity 1.5 --show
```

## Requirements

- Windows 10/11
- Python 3.11+ (installed separately or via `winget install Python.Python.3.13`)
- A USB webcam (Logitech C920 or similar)
- ffmpeg (installed automatically by `setup_windows.ps1`)

## Files

| File | Purpose |
|---|---|
| `handmouse_gui.py` | Tkinter GUI — start here |
| `handmouse_win.py` | Core tracker (camera + hand detection + mouse) |
| `gestures.py` | Finger / pinch gesture classifier |
| `protocol.py` | Wire protocol (used by the legacy WSL relay) |
| `mouse_relay.py` | Legacy WSL→Windows relay (not needed for Windows-native) |
| `setup_windows.ps1` | One-command setup script |
| `hand_landmarker.task` | MediaPipe model (downloaded by setup) |
