#Requires -Version 5.1
<#
.SYNOPSIS
    One-command setup for handmouse on Windows.
    Run from PowerShell (as regular user):  .\setup_windows.ps1

.DESCRIPTION
    1. Installs winget if missing
    2. Installs Python 3.11 if missing
    3. Installs ffmpeg via winget
    4. Installs Visual C++ redistributable (required by mediapipe/opencv)
    5. Creates a Python venv (venv-win) and installs all Python dependencies
    6. Downloads the MediaPipe hand-landmarker model (~8 MB)
    7. Creates a desktop shortcut that opens the GUI
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $dir

function Say($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg)  { Write-Host "  OK $msg" -ForegroundColor Green }
function Warn($msg){ Write-Host "  !  $msg" -ForegroundColor Yellow }
function Err($msg) { Write-Host "  X  $msg" -ForegroundColor Red }

Say "handmouse setup"
Write-Host ""

# ── 0. Winget ─────────────────────────────────────────────────────────────────
Say "[0/6] Checking winget"
$winget = Get-Command winget -ErrorAction SilentlyContinue
if (-not $winget) {
    Warn "winget not found."
    Write-Host "  winget ships with Windows 11 and Windows 10 21H2+."
    Write-Host "  Install it from the Microsoft Store: 'App Installer'"
    Write-Host "  Or visit: https://aka.ms/getwinget"
    Write-Host ""
    Read-Host "Press Enter after installing winget, or Ctrl+C to abort"
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) { Write-Error "winget still not found. Aborting." }
}
Ok "winget available"

# ── 1. Python ─────────────────────────────────────────────────────────────────
Say "[1/6] Checking Python"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Warn "Python not found — installing Python 3.11 via winget..."
    winget install --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements
    # Refresh PATH
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH","User")
    $python = Get-Command python -ErrorAction SilentlyContinue
}
if (-not $python) {
    Write-Error "Python still not found after install. Please install from https://python.org and re-run."
}

# Verify tkinter is available (missing on some minimal installs)
$tkCheck = & python -c "import tkinter" 2>&1
if ($LASTEXITCODE -ne 0) {
    Warn "tkinter not found in this Python install."
    Write-Host "  If you installed Python from the Microsoft Store, tkinter may be missing."
    Write-Host "  Please reinstall Python from https://python.org (check 'tcl/tk and IDLE' during setup)."
    Write-Error "tkinter required — cannot continue."
}
Ok "Python $( & python --version ) with tkinter"

# ── 2. ffmpeg ─────────────────────────────────────────────────────────────────
Say "[2/6] Checking ffmpeg"
$ffmpegCmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpegCmd) {
    Warn "ffmpeg not found — installing via winget..."
    winget install --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH","User")
    $ffmpegCmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
}

# Resolve absolute path (winget installs to a version-stamped directory)
if ($ffmpegCmd) {
    $ffmpegPath = $ffmpegCmd.Source
} else {
    $ffmpegPath = (Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Gyan.FFmpeg*" `
                    -Recurse -Filter "ffmpeg.exe" -ErrorAction SilentlyContinue |
                    Select-Object -First 1).FullName
}
if (-not $ffmpegPath) {
    Write-Error "Could not locate ffmpeg.exe after install. Try: winget install Gyan.FFmpeg"
}
Ok "ffmpeg at $ffmpegPath"

# Patch the hard-coded path into the scripts
$escapedPath = $ffmpegPath -replace '\\', '\\'
foreach ($f in @("handmouse_win.py", "handmouse_gui.py")) {
    $content = Get-Content $f -Raw
    $patched = $content -replace 'FFMPEG\s*=\s*r"[^"]*"', "FFMPEG = r`"$ffmpegPath`""
    Set-Content $f $patched -NoNewline
}
Ok "ffmpeg path written to scripts"

# ── 3. Visual C++ redistributable ─────────────────────────────────────────────
Say "[3/6] Checking Visual C++ redistributable"
# mediapipe and opencv need the VC++ 2015-2022 runtime DLLs
$vcKey = "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
$vcOk  = (Test-Path $vcKey) -and ((Get-ItemProperty $vcKey -ErrorAction SilentlyContinue).Installed -eq 1)
if (-not $vcOk) {
    Warn "VC++ runtime not detected — installing via winget..."
    try {
        winget install --id Microsoft.VCRedist.2015+.x64 `
            --accept-source-agreements --accept-package-agreements --silent
        Ok "VC++ runtime installed"
    } catch {
        Warn "Could not auto-install VC++ runtime. If mediapipe fails to import, download manually:"
        Warn "  https://aka.ms/vs/17/release/vc_redist.x64.exe"
    }
} else {
    Ok "VC++ redistributable present"
}

# ── 4. Python venv + packages ─────────────────────────────────────────────────
Say "[4/6] Setting up Python venv (venv-win)"
if (-not (Test-Path "venv-win\Scripts\python.exe")) {
    python -m venv venv-win
    Ok "venv created"
} else {
    Ok "venv already exists"
}

$pip = "venv-win\Scripts\pip.exe"
Write-Host "  Upgrading pip..."
& $pip install --upgrade pip --quiet

Write-Host "  Installing Python packages..."
& $pip install --upgrade `
    "mediapipe>=1.0.1" `
    "opencv-python>=4.9.0" `
    "numpy>=1.26" `
    "pyautogui>=0.9.54" `
    "screeninfo>=0.8.1" `
    --quiet

if ($LASTEXITCODE -ne 0) {
    Write-Error "pip install failed — see output above."
}
Ok "Python packages installed"

# ── 5. MediaPipe model ────────────────────────────────────────────────────────
Say "[5/6] Downloading hand-landmarker model"
$modelPath = "hand_landmarker.task"
if (-not (Test-Path $modelPath)) {
    $modelUrl = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
    Write-Host "  Downloading from Google storage (~8 MB)..."
    try {
        Invoke-WebRequest -Uri $modelUrl -OutFile $modelPath -UseBasicParsing
        Ok "Model downloaded ($([math]::Round((Get-Item $modelPath).Length/1MB, 1)) MB)"
    } catch {
        Write-Error "Download failed: $_`nManual download: $modelUrl"
    }
} else {
    Ok "Model already present ($([math]::Round((Get-Item $modelPath).Length/1MB, 1)) MB)"
}

# ── 6. Desktop shortcut ───────────────────────────────────────────────────────
Say "[6/6] Creating desktop shortcut"
$pythonwExe = Resolve-Path "venv-win\Scripts\pythonw.exe" -ErrorAction SilentlyContinue
if (-not $pythonwExe) {
    # Fallback: pythonw.exe may not exist in all venvs — use python.exe
    $pythonwExe = Resolve-Path "venv-win\Scripts\python.exe"
    Warn "pythonw.exe not found, shortcut will use python.exe (a console window will appear)"
}
$guiScript    = Resolve-Path "handmouse_gui.py"
$shortcutPath = [System.IO.Path]::Combine(
    [System.Environment]::GetFolderPath("Desktop"), "handmouse.lnk")

$wsh = New-Object -ComObject WScript.Shell
$sc  = $wsh.CreateShortcut($shortcutPath)
$sc.TargetPath       = $pythonwExe
$sc.Arguments        = "`"$guiScript`""
$sc.WorkingDirectory = $dir
$sc.Description      = "handmouse — hand-tracking mouse controller"
$sc.IconLocation     = "$pythonwExe,0"
$sc.Save()
Ok "Shortcut created: $shortcutPath"

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Open the GUI:   double-click 'handmouse' on your Desktop"
Write-Host "  Or run:         .\venv-win\Scripts\python.exe handmouse_gui.py"
Write-Host ""
Write-Host "  Note: GPU acceleration is not available in the standard mediapipe" -ForegroundColor Yellow
Write-Host "  pip package on Windows — the GPU checkbox has no effect." -ForegroundColor Yellow
