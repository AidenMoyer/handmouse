# handmouse

Control your mouse with your hand using a webcam. No special hardware needed.

## Quick install (Windows)

Open **PowerShell** (search "PowerShell" in Start — does **not** need to be run as Administrator) and run these commands in order:

```powershell
# 1. Allow PowerShell scripts to run (only needed once per machine)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# 2. Clone the repo and run setup
git clone https://github.com/AidenMoyer/handmouse
cd handmouse
.\setup_windows.ps1
```

That's it. The setup script will:
- Install Python 3.11 if missing (via winget)
- Install ffmpeg if missing (via winget)
- Install the Visual C++ runtime (required by mediapipe / opencv)
- Create a Python virtual environment and install all packages
- Download the MediaPipe hand-landmarker model (~8 MB)
- Create a **handmouse** shortcut on your Desktop

After setup, double-click the **handmouse** shortcut on your Desktop to open the control panel.

---

## Requirements

| Requirement | Notes |
|---|---|
| Windows 10 21H2+ or Windows 11 | winget must be available |
| A webcam | Any USB or built-in camera |
| Python 3.9–3.12 | Auto-installed if missing |
| ffmpeg | Auto-installed if missing |

> **GPU acceleration** is listed in the settings but has no effect — the standard
> `pip install mediapipe` on Windows is compiled without GPU support.
> The app runs on CPU+XNNPACK (multi-threaded) which is fast enough for real-time use.

---

## Gestures

| Gesture | Action |
|---|---|
| Open hand (all fingers extended) | Move mouse |
| Thumb + index finger pinch | Left click / drag |
| Thumb + middle finger pinch | Scroll |
| Thumb + pinky finger pinch | Right click |
| Closed fist | Pause — cursor freezes |

**Tracking modes** (selectable in the GUI):

- **Relative (trackpad)** *(default)* — works like a trackpad. Fist to pause, open hand to resume from the same spot. Cursor moves freely across all monitors.
- **Absolute** — hand position in the camera frame maps directly to the selected monitor.

---

## Settings

All settings are saved automatically in `settings.json` next to the scripts and restored on next launch.

| Setting | Description |
|---|---|
| Camera | Which webcam to use |
| Control monitor | Which monitor to control (absolute mode only) |
| Resolution | Camera capture resolution (higher = more CPU; inference always runs at 640×480) |
| FPS | Camera frame rate |
| Track hand | Which hand to track — any, left, or right |
| Tracking mode | Relative (trackpad) or Absolute |
| Sensitivity | How much cursor movement per hand movement |
| Mirror | Flip camera so left/right match your perspective |
| Preview window | Show camera feed with landmark overlay |

---

## Troubleshooting

**"setup_windows.ps1 is not recognized" or "running scripts is disabled"**
PowerShell's default security policy blocks `.ps1` files. Run this once first, then try again:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**"repository not found" when cloning**
Make sure you use the exact URL: `https://github.com/AidenMoyer/handmouse` — note the username is **AidenMoyer**, not the email address.

**"No frames — check device name with --list"**
The camera name in settings doesn't match what Windows sees. Hit **↻ Refresh cameras & monitors** in the GUI, then re-select your camera from the dropdown.

**"tkinter not found"**
Your Python was installed from the Microsoft Store — it strips tkinter. Uninstall it and reinstall Python from [python.org](https://python.org), making sure to check **tcl/tk and IDLE** during setup.

**Cursor drifts when hand is still**
Lower the sensitivity slider. The dead zone already filters sub-pixel noise; very high sensitivity amplifies any residual motion.

**Hand not detected**
Make sure you're in good lighting. The hand should be clearly visible against the background. Try moving the camera or adjusting your position.

**Scroll not working**
Use a thumb + middle finger pinch. Make sure your middle finger is the closest fingertip to your thumb (the app picks the nearest finger to avoid false triggers from adjacent fingers).
