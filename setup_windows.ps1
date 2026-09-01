#Requires -Version 5.1
<#
.SYNOPSIS
    One-command setup for handmouse on Windows.
    Run from PowerShell (as regular user):  .\setup_windows.ps1
.DESCRIPTION
    1. Checks/installs winget
    2. Checks/installs Python 3.11
    3. Checks/installs ffmpeg
    4. Checks/installs Visual C++ redistributable
    5. Creates Python venv and installs all packages
    6. Downloads the MediaPipe hand-landmarker model
    7. Creates a Desktop shortcut
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptPath = $MyInvocation.MyCommand.Path
$dir = if ($scriptPath) { Split-Path -Parent $scriptPath } else { $PWD.Path }
Set-Location $dir

function Say([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok([string]$msg)  { Write-Host "  OK  $msg" -ForegroundColor Green }
function Warn([string]$msg){ Write-Host "  !   $msg" -ForegroundColor Yellow }

Say 'handmouse setup'
Write-Host ''

# ---------------------------------------------------------------------------
# 0. winget
# ---------------------------------------------------------------------------
Say '[0/7] Checking winget'
$wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
if (-not $wingetCmd) {
    Warn 'winget not found. It ships with Windows 10 21H2+ and Windows 11.'
    Write-Host '  Install "App Installer" from the Microsoft Store, then re-run.'
    Write-Host '  Or visit: https://aka.ms/getwinget'
    Read-Host 'Press Enter after installing winget, or Ctrl+C to abort'
    $wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $wingetCmd) { Write-Error 'winget still not found. Aborting.' }
}
Ok 'winget available'

# ---------------------------------------------------------------------------
# 1. Git
# ---------------------------------------------------------------------------
Say '[1/7] Checking git'
$gitCmd = Get-Command git -ErrorAction SilentlyContinue
if (-not $gitCmd) {
    Warn 'git not found -- installing Git for Windows via winget...'
    winget install --id Git.Git --accept-source-agreements --accept-package-agreements
    $machinePath = [System.Environment]::GetEnvironmentVariable('PATH', 'Machine')
    $userPath    = [System.Environment]::GetEnvironmentVariable('PATH', 'User')
    $env:PATH    = "$machinePath;$userPath"
    $gitCmd = Get-Command git -ErrorAction SilentlyContinue
    if (-not $gitCmd) {
        Warn 'git still not in PATH. Close and reopen PowerShell, then re-run setup.'
        Write-Error 'git not found after install.'
    }
}
Ok "git $( & git --version )"

# ---------------------------------------------------------------------------
# 2. Python
# ---------------------------------------------------------------------------
Say '[2/7] Checking Python'
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Warn 'Python not found -- installing Python 3.11 via winget...'
    winget install --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements
    # Refresh PATH without relying on a new shell
    $machinePath = [System.Environment]::GetEnvironmentVariable('PATH', 'Machine')
    $userPath    = [System.Environment]::GetEnvironmentVariable('PATH', 'User')
    $env:PATH    = "$machinePath;$userPath"
    $python = Get-Command python -ErrorAction SilentlyContinue
}
if (-not $python) {
    Write-Error 'Python not found after install. Install from https://python.org and re-run.'
}

# Verify tkinter (missing from Microsoft Store Python builds)
$null = & python -c 'import tkinter' 2>&1
if ($LASTEXITCODE -ne 0) {
    Warn 'tkinter not available in this Python install.'
    Write-Host '  Reinstall Python from https://python.org'
    Write-Host '  and tick "tcl/tk and IDLE" during setup.'
    Write-Error 'tkinter required -- cannot continue.'
}
$pyVersion = (& python --version 2>&1)
Ok "Python $pyVersion with tkinter"

# ---------------------------------------------------------------------------
# 2. ffmpeg
# ---------------------------------------------------------------------------
Say '[3/7] Checking ffmpeg'
$ffmpegCmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpegCmd) {
    Warn 'ffmpeg not found -- installing via winget...'
    winget install --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
    $machinePath = [System.Environment]::GetEnvironmentVariable('PATH', 'Machine')
    $userPath    = [System.Environment]::GetEnvironmentVariable('PATH', 'User')
    $env:PATH    = "$machinePath;$userPath"
    $ffmpegCmd   = Get-Command ffmpeg -ErrorAction SilentlyContinue
}

if ($ffmpegCmd) {
    $ffmpegPath = $ffmpegCmd.Source
} else {
    $searchRoot = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
    $ffmpegPath = (
        Get-ChildItem "$searchRoot\Gyan.FFmpeg*" -Recurse -Filter 'ffmpeg.exe' -ErrorAction SilentlyContinue |
        Select-Object -First 1
    ).FullName
}
if (-not $ffmpegPath) {
    Write-Error 'Cannot find ffmpeg.exe. Run: winget install Gyan.FFmpeg'
}
Ok "ffmpeg at $ffmpegPath"

# Patch the hard-coded path into the Python scripts
foreach ($f in @('handmouse_win.py', 'handmouse_gui.py')) {
    $content = Get-Content $f -Raw -Encoding UTF8
    $patched = $content -replace 'FFMPEG\s*=\s*r"[^"]*"', "FFMPEG = r`"$ffmpegPath`""
    [System.IO.File]::WriteAllText((Join-Path $dir $f), $patched, [System.Text.Encoding]::UTF8)
}
Ok 'ffmpeg path written to scripts'

# ---------------------------------------------------------------------------
# 3. Visual C++ redistributable
# ---------------------------------------------------------------------------
Say '[4/7] Checking Visual C++ redistributable'
$vcKey = 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64'
$vcOk  = (Test-Path $vcKey) -and (
    (Get-ItemProperty $vcKey -ErrorAction SilentlyContinue).Installed -eq 1
)
if (-not $vcOk) {
    Warn 'VC++ runtime not detected -- installing via winget...'
    try {
        winget install --id Microsoft.VCRedist.2015+.x64 `
            --accept-source-agreements --accept-package-agreements --silent
        Ok 'VC++ runtime installed'
    } catch {
        Warn 'Auto-install failed. If mediapipe errors on launch, download manually:'
        Warn '  https://aka.ms/vs/17/release/vc_redist.x64.exe'
    }
} else {
    Ok 'VC++ redistributable present'
}

# ---------------------------------------------------------------------------
# 4. Python venv + packages
# ---------------------------------------------------------------------------
Say '[5/7] Setting up Python venv (venv-win)'
$venvPython = Join-Path $dir 'venv-win\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    python -m venv venv-win
    Ok 'venv created'
} else {
    Ok 'venv already exists'
}

# Use 'python -m pip' -- more reliable than calling pip.exe directly on a fresh venv
Write-Host '  Upgrading pip...'
& $venvPython -m pip install --upgrade pip --quiet

Write-Host '  Installing Python packages...'
& $venvPython -m pip install --upgrade `
    'mediapipe>=1.0.1' `
    'opencv-python>=4.9.0' `
    'numpy>=1.26' `
    'pyautogui>=0.9.54' `
    'screeninfo>=0.8.1' `
    --quiet

if ($LASTEXITCODE -ne 0) {
    Write-Error 'pip install failed -- see output above.'
}
Ok 'Python packages installed'

# ---------------------------------------------------------------------------
# 5. MediaPipe model
# ---------------------------------------------------------------------------
Say '[6/7] Downloading hand-landmarker model'
$modelPath = Join-Path $dir 'hand_landmarker.task'
if (-not (Test-Path $modelPath)) {
    $modelUrl = 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task'
    Write-Host '  Downloading from Google storage (~8 MB)...'
    try {
        Invoke-WebRequest -Uri $modelUrl -OutFile $modelPath -UseBasicParsing
        $mb = [math]::Round((Get-Item $modelPath).Length / 1MB, 1)
        Ok "Model downloaded ($mb MB)"
    } catch {
        Write-Error "Download failed: $_`nManual URL: $modelUrl"
    }
} else {
    $mb = [math]::Round((Get-Item $modelPath).Length / 1MB, 1)
    Ok "Model already present ($mb MB)"
}

# ---------------------------------------------------------------------------
# 6. Desktop shortcut
# ---------------------------------------------------------------------------
Say '[7/7] Creating desktop shortcut'
$pythonwExe = Join-Path $dir 'venv-win\Scripts\pythonw.exe'
if (-not (Test-Path $pythonwExe)) {
    $pythonwExe = Join-Path $dir 'venv-win\Scripts\python.exe'
    Warn 'pythonw.exe not found -- shortcut will show a console window'
}
$guiScript    = Join-Path $dir 'handmouse_gui.py'
$desktopDir   = [System.Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopDir 'handmouse.lnk'

$wsh = New-Object -ComObject WScript.Shell
$sc  = $wsh.CreateShortcut($shortcutPath)
$sc.TargetPath       = $pythonwExe
$sc.Arguments        = "`"$guiScript`""
$sc.WorkingDirectory = $dir
$sc.Description      = 'handmouse hand-tracking mouse controller'
$sc.IconLocation     = "$pythonwExe,0"
$sc.Save()
Ok "Shortcut created: $shortcutPath"

# ---------------------------------------------------------------------------
Write-Host ''
Write-Host '  Setup complete!' -ForegroundColor Green
Write-Host ''
Write-Host '  Open the GUI:  double-click handmouse on your Desktop'
Write-Host '  Or run:        .\venv-win\Scripts\python.exe handmouse_gui.py'
Write-Host ''
Write-Host '  Note: GPU checkbox has no effect -- pip mediapipe on Windows is CPU-only.' -ForegroundColor Yellow
