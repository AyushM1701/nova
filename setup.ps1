# Nova setup for Windows. Run setup.cmd (double-click) or:
#   powershell -ExecutionPolicy Bypass -File setup.ps1
# Safe to run again: it updates everything in place.
# Unattended: setup.ps1 -Engine claude|codex -Yes   (answers yes to every question)
param([ValidateSet("", "claude", "codex")][string]$Engine = "", [switch]$Yes)
# "Continue", not "Stop": in Windows PowerShell a native tool writing to stderr would otherwise abort setup.
# Every step that matters checks $LASTEXITCODE and throws itself.
$ErrorActionPreference = "Continue"
$Root = $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$Py = Join-Path $Venv "Scripts\python.exe"
$PyW = Join-Path $Venv "Scripts\pythonw.exe"

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Ask($question) { if ($Yes) { Write-Host "$question yes"; return $true }; (Read-Host "$question [Y/n]") -notmatch '^(n|no)$' }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function Has($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Find-Python {
    # Python 3.11-3.13: the speech libraries don't ship wheels for newer versions yet
    foreach ($v in "3.13", "3.12", "3.11") {
        if (Has "py") {
            $p = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { return $p.Trim() }
        }
    }
    foreach ($cand in @("python", "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
                        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe")) {
        if (Has $cand) {
            $ok = & $cand -c "import sys; print((3, 11) <= sys.version_info[:2] <= (3, 13))" 2>$null
            if ($ok -eq "True") { return (& $cand -c "import sys; print(sys.executable)").Trim() }
        }
    }
    return $null
}

Write-Host "Nova setup: everything is installed inside $Root (plus the speech models in your user cache)."

Step "1/6  Python"
$Base = Find-Python
if (-not $Base) {
    if (-not (Has "winget")) { throw "Python 3.11-3.13 is required. Install it from https://www.python.org/downloads/ and run setup again." }
    if (-not (Ask "Python 3.12 isn't installed. Install it now with winget?")) { throw "Python 3.11-3.13 is required." }
    winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
    Refresh-Path
    $Base = Find-Python
    if (-not $Base) { throw "Python was installed but can't be found yet. Open a new terminal and run setup again." }
}
Write-Host "Using $Base"

Step "2/6  Nova's own Python environment and libraries"
if (-not (Test-Path $Py)) { & $Base -m venv $Venv }
& $Py -m pip install --quiet --upgrade pip
& $Py -m pip install --quiet -r (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Installing libraries failed (see above)." }
$gpu = $false
if (Has "nvidia-smi") { & nvidia-smi -L *> $null; $gpu = ($LASTEXITCODE -eq 0) }
if ($gpu) {
    Write-Host "NVIDIA GPU found: adding GPU speech recognition (about 1 GB)."
    & $Py -m pip install --quiet -r (Join-Path $Root "requirements-gpu.txt")
}

Step "3/6  Speech models (downloaded once, then used offline)"
& $Py -c "from faster_whisper.utils import download_model as d; d('small'); d('large-v3-turbo'); print('Models ready.')"
if ($LASTEXITCODE -ne 0) { throw "Downloading the speech models failed. Check your internet connection and run setup again." }
New-Item -ItemType Directory -Force (Join-Path $Root "data") | Out-Null
New-Item -ItemType File -Force (Join-Path $Root "data\models-ready") | Out-Null

Step "4/6  Connect an AI: Claude Code or Codex"
Write-Host "  1) Claude Code (Anthropic)   installed: $(Has 'claude')"
Write-Host "  2) Codex (OpenAI)            installed: $(Has 'codex')"
$engine = $Engine
if (-not $engine) { $engine = if ((Read-Host "Which one should Nova use? [1/2]") -eq "2") { "codex" } else { "claude" } }
if (-not (Has $engine)) {
    if (-not (Has "npm")) {
        if ((Has "winget") -and (Ask "$engine needs Node.js. Install Node.js LTS with winget?")) {
            winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
            Refresh-Path
        }
    }
    if (-not (Has "npm")) { throw "Install Node.js from https://nodejs.org, then run setup again." }
    $package = if ($engine -eq "claude") { "@anthropic-ai/claude-code" } else { "@openai/codex" }
    if (Ask "Install the $engine CLI ($package) with npm?") { npm install -g $package; Refresh-Path }
}
if (Has $engine) {
    if ($engine -eq "claude") {
        & claude auth status *> $null
        if ($LASTEXITCODE -ne 0) { Write-Host "Log in to Claude in the window that opens."; & claude auth login }
    } else {
        & codex login status *> $null
        if ($LASTEXITCODE -ne 0) { Write-Host "Log in to Codex in the window that opens."; & codex login }
    }
} else {
    Write-Host "Skipped: Nova will still do dictation, and you can connect an AI later by running setup again." -ForegroundColor Yellow
}
$cfgPath = Join-Path $Root "config.json"
& $Py -c "import json, pathlib, sys; p = pathlib.Path(sys.argv[1]); c = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}; c.setdefault('brain', {})['engine'] = sys.argv[2]; p.write_text(json.dumps(c, indent=2), encoding='utf-8')" $cfgPath $engine

Step "5/6  Start menu and start with Windows"
$icon = Join-Path $Root "data\nova.ico"
Push-Location $Root; & $Py -m core.icon $icon; Pop-Location
$shell = New-Object -ComObject WScript.Shell
function Make-Shortcut($path) {
    $s = $shell.CreateShortcut($path)
    $s.TargetPath = $PyW
    $s.Arguments = "`"$(Join-Path $Root 'nova.py')`""
    $s.WorkingDirectory = $Root
    $s.IconLocation = $icon
    $s.Description = "Nova voice assistant"
    $s.Save()
}
$programs = [Environment]::GetFolderPath("Programs")
Make-Shortcut (Join-Path $programs "Nova.lnk")
$startup = Join-Path ([Environment]::GetFolderPath("Startup")) "Nova.lnk"
if (Ask "Start Nova automatically when you sign in to Windows?") { Make-Shortcut $startup }
elseif (Test-Path $startup) { Remove-Item $startup }

Step "6/6  Starting Nova"
Push-Location $Root; & $Py tests.py; Pop-Location
Start-Process -FilePath $PyW -ArgumentList "`"$(Join-Path $Root 'nova.py')`"" -WorkingDirectory $Root
Write-Host @"

Nova is running. Its icon is in the hidden icons area: click the ^ arrow next to the clock
(drag it onto the taskbar if you want it always visible). Right-click it for settings.

  Say "Hey Nova", press Ctrl+Alt+Space, or click the small bar at the bottom of the screen.
  Say "switch to dictation" to type with your voice.

Your settings, logs and notes stay in $Root. Uninstall any time with uninstall.cmd.
"@ -ForegroundColor Green
