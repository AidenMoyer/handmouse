#Requires -Version 5.1
<#
.SYNOPSIS
    One-command setup for handmouse on Windows.
    Run from PowerShell:  .\setup_windows.ps1

.DESCRIPTION
    1. Installs ffmpeg via winget (if missing)
    2. Creates a Python venv (venv-win) and installs dependencies
    3. Downloads the MediaPipe hand-landmarker model (~8 MB)
    4. Creates a desktop shortcut that opens the GUI
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $dir

function Say($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg)  { Write-Host "  ✓ $msg"  -ForegroundColor Green }
function Warn($msg){ Write-Host "  ! $msg"  -ForegroundColor Yellow }

Say "handmouse setup"

# ── 1. ffmpeg ─────────────────────────────────────────────────────────────────
Say "[1/4] Checking ffmpeg"
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpeg) {
    Warn "ffmpeg not found — installing via winget..."
    winget install --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
    # Refresh PATH
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH","User")
    $ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
}

# Locate ffmpeg.exe (winget installs to a version-named dir)
if ($ffmpeg) {
    $ffmpegPath = $ffmpeg.Source
} else {
    $ffmpegPath = (Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Gyan.FFmpeg*" -Recurse -Filter "ffmpeg.exe" -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
}

if (-not $ffmpegPath) {
    Write-Error "Could not locate ffmpeg.exe. Install manually: winget install Gyan.FFmpeg"
}

Ok "ffmpeg at $ffmpegPath"

# Patch the path into handmouse_win.py and handmouse_gui.py
$escapedPath = $ffmpegPath -replace '\\', '\\'
foreach ($f in @("handmouse_win.py", "handmouse_gui.py")) {
    $content = Get-Content $f -Raw
    $patched = $content -replace 'FFMPEG\s*=\s*r"[^"]*"', "FFMPEG = r`"$ffmpegPath`""
    Set-Content $f $patched -NoNewline
}
Ok "ffmpeg path written to scripts"

# ── 2. Python venv ────────────────────────────────────────────────────────────
Say "[2/4] Setting up Python venv (venv-win)"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error "Python not found. Install from python.org or: winget install Python.Python.3.13"
}

if (-not (Test-Path "venv-win\Scripts\python.exe")) {
    python -m venv venv-win
    Ok "venv created"
} else {
    Ok "venv already exists"
}

$pip = "venv-win\Scripts\pip.exe"
& $pip install --upgrade pip --quiet
& $pip install mediapipe opencv-python numpy pyautogui screeninfo --quiet
Ok "Python packages installed"

# ── 3. MediaPipe model ────────────────────────────────────────────────────────
Say "[3/4] Downloading hand-landmarker model"
$modelPath = "hand_landmarker.task"
if (-not (Test-Path $modelPath)) {
    $modelUrl = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
    Invoke-WebRequest -Uri $modelUrl -OutFile $modelPath -UseBasicParsing
    Ok "Model downloaded ($([math]::Round((Get-Item $modelPath).Length/1MB, 1)) MB)"
} else {
    Ok "Model already present"
}

# ── 4. Desktop shortcut ───────────────────────────────────────────────────────
Say "[4/4] Creating desktop shortcut"
$pythonExe  = Resolve-Path "venv-win\Scripts\pythonw.exe"  # no console window
$guiScript  = Resolve-Path "handmouse_gui.py"
$shortcutPath = [System.IO.Path]::Combine(
    [System.Environment]::GetFolderPath("Desktop"), "handmouse.lnk")

$wsh = New-Object -ComObject WScript.Shell
$sc  = $wsh.CreateShortcut($shortcutPath)
$sc.TargetPath       = $pythonExe
$sc.Arguments        = "`"$guiScript`""
$sc.WorkingDirectory = $dir
$sc.Description      = "handmouse — hand tracking mouse controller"
$sc.IconLocation     = "$pythonExe,0"
$sc.Save()
Ok "Shortcut created: $shortcutPath"

Write-Host ""
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host "  Open the GUI:  double-click 'handmouse' on your Desktop"
Write-Host "  Or run:        .\venv-win\Scripts\python.exe handmouse_gui.py"
