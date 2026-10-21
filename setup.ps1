# Nova setup for Windows: a small installer window, then Nova's own first-run screens.
# Double-click setup.cmd, or run:  powershell -ExecutionPolicy Bypass -File setup.ps1
# Safe to run again: it updates everything in place.
# Unattended: setup.ps1 -Engine claude|codex -Yes   (answers yes to every question)
param([ValidateSet("", "claude", "codex")][string]$Engine = "", [switch]$Yes)
# "Continue", not "Stop": in Windows PowerShell a native tool writing to stderr would otherwise abort setup.
# Every step that matters checks its exit code and throws itself.
$ErrorActionPreference = "Continue"
$Root = $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$Py = Join-Path $Venv "Scripts\python.exe"
$PyW = Join-Path $Venv "Scripts\pythonw.exe"
$Steps = 8
$ModelBytes = 2.1GB  # shortcut: approximate size of the two speech models, only used for the progress bar

Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
Add-Type -TypeDefinition 'using System.Runtime.InteropServices; public static class NovaDpi { [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); }'
[void][NovaDpi]::SetProcessDPIAware()
$g = [Drawing.Graphics]::FromHwnd([IntPtr]::Zero); $Scale = $g.DpiX / 96; $g.Dispose()
function Px([double]$v) { [int]($v * $Scale) }
function Rgb($r, $gr, $b) { [Drawing.Color]::FromArgb($r, $gr, $b) }
$Bg, $Fg, $Dim, $Accent, $TrackColor, $Bad = (Rgb 22 22 26), (Rgb 242 242 244), (Rgb 163 163 173), (Rgb 124 92 255), (Rgb 42 42 49), (Rgb 255 122 122)

# ---------- the window ----------
$form = New-Object Windows.Forms.Form
$form.Text = "Nova setup"; $form.ClientSize = New-Object Drawing.Size((Px 560), (Px 236))
$form.FormBorderStyle = "FixedSingle"; $form.MaximizeBox = $false; $form.StartPosition = "CenterScreen"
$form.BackColor = $Bg; $form.ForeColor = $Fg; $form.Font = New-Object Drawing.Font("Segoe UI", 10)
$icoPath = Join-Path $Root "data\nova.ico"
if (Test-Path $icoPath) { $form.Icon = New-Object Drawing.Icon($icoPath) }
function Add($ctl, $x, $y, $w, $h) { $ctl.Location = New-Object Drawing.Point((Px $x), (Px $y)); $ctl.Size = New-Object Drawing.Size((Px $w), (Px $h)); $form.Controls.Add($ctl); $ctl }
$dot = Add (New-Object Windows.Forms.Panel) 28 32 12 12
$dot.BackColor = $Accent
$path = New-Object Drawing.Drawing2D.GraphicsPath; $path.AddEllipse(0, 0, (Px 12), (Px 12)); $dot.Region = New-Object Drawing.Region($path)
$title = Add (New-Object Windows.Forms.Label) 48 22 480 32
$title.Font = New-Object Drawing.Font("Segoe UI Semibold", 15); $title.Text = "Installing Nova"
$status = Add (New-Object Windows.Forms.Label) 28 66 504 24
$status.ForeColor = $Dim; $status.Text = "Getting ready"
$track = Add (New-Object Windows.Forms.Panel) 28 100 504 6
$track.BackColor = $TrackColor
$fill = New-Object Windows.Forms.Panel; $fill.BackColor = $Accent; $fill.Size = New-Object Drawing.Size(0, (Px 6)); $track.Controls.Add($fill)
$detail = Add (New-Object Windows.Forms.Label) 28 114 504 22
$detail.ForeColor = $Dim; $detail.Font = New-Object Drawing.Font("Segoe UI", 9)
$log = Add (New-Object Windows.Forms.TextBox) 28 144 504 0
$log.Multiline = $true; $log.ReadOnly = $true; $log.ScrollBars = "Vertical"; $log.BorderStyle = "None"
$log.BackColor = (Rgb 15 15 18); $log.ForeColor = $Dim; $log.Font = New-Object Drawing.Font("Consolas", 8.5); $log.Visible = $false
$toggle = Add (New-Object Windows.Forms.LinkLabel) 28 192 140 24
$toggle.Text = "Show details"; $toggle.LinkColor = $Dim; $toggle.ActiveLinkColor = $Fg; $toggle.LinkBehavior = "HoverUnderline"
$button = Add (New-Object Windows.Forms.Button) 412 184 120 34
$button.Text = "Cancel"; $button.FlatStyle = "Flat"; $button.BackColor = $TrackColor; $button.ForeColor = $Fg
$button.FlatAppearance.BorderSize = 0; $button.Cursor = "Hand"

function Layout {
    $extra = if ($log.Visible) { 150 } else { 0 }
    $log.Height = Px ($extra - 14)
    $toggle.Top = Px (192 + $extra); $button.Top = Px (184 + $extra)
    $form.ClientSize = New-Object Drawing.Size((Px 560), (Px (236 + $extra)))
    $toggle.Text = if ($log.Visible) { "Hide details" } else { "Show details" }
}
$toggle.add_LinkClicked({ $log.Visible = -not $log.Visible; Layout })
$script:cancelled = $false; $script:finished = $false
$button.add_Click({ if ($script:finished) { $form.Close() } else { $script:cancelled = $true } })
$form.add_FormClosing({ if (-not $script:finished) { $script:cancelled = $true } })
# started from a hidden console, the window would open behind everything: bring it forward once
$form.add_Shown({ $form.TopMost = $true; $form.Activate(); $form.TopMost = $false })

function Pump { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 50 }
function Progress([double]$pct) { $fill.Width = [int]($track.Width * [Math]::Min([double]1, [Math]::Max([double]0, $pct))) }
$script:n = 0
function Step($text) {
    if ($script:cancelled) { throw "Setup was cancelled." }
    $script:n++
    $status.Text = "Step $script:n of ${Steps}: $text"; $detail.Text = ""
    Progress (($script:n - 1) / $Steps); Note "== $text"; Pump
}
function Note($line) { $log.AppendText("$line`r`n") }
function Ask($question) {
    if ($Yes) { Note "$question yes"; return $true }
    [Windows.Forms.MessageBox]::Show($form, $question, "Nova setup", "YesNo", "Question") -eq "Yes"
}
function Has($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

# Run a program without freezing the window; its output streams into the details box.
function Run([string]$exe, [string[]]$argv, [scriptblock]$onTick = $null) {
    $quoted = $argv | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }
    $out = Join-Path $env:TEMP "nova-setup-$PID.out"; $err = "$out.err"
    Remove-Item $out, $err -ErrorAction SilentlyContinue
    Note "> $(Split-Path $exe -Leaf) $($quoted -join ' ')"
    $p = Start-Process -FilePath $exe -ArgumentList ($quoted -join " ") -NoNewWindow -PassThru `
        -RedirectStandardOutput $out -RedirectStandardError $err
    $null = $p.Handle  # keeps ExitCode readable after the process ends
    $shown = 0; $tick = 0
    while (-not $p.HasExited) {
        Pump
        if ($script:cancelled) { & taskkill /T /F /PID $p.Id *> $null; throw "Setup was cancelled." }
        if ((++$tick % 6) -eq 0) {
            $shown = Tail $out $err $shown
            if ($onTick) { & $onTick }
        }
    }
    $p.WaitForExit()
    [void](Tail $out $err $shown)
    return $p.ExitCode
}
function Tail($out, $err, $shown) {
    $text = ""
    foreach ($f in $out, $err) {
        try {
            $fs = [IO.File]::Open($f, "Open", "Read", "ReadWrite"); $sr = New-Object IO.StreamReader($fs)
            $text += $sr.ReadToEnd(); $sr.Close()
        } catch {}
    }
    $lines = @($text -split "`r?`n" | ForEach-Object { ($_ -split "`r")[-1] } | Where-Object { $_.Trim() })
    for ($i = $shown; $i -lt $lines.Count; $i++) { Note $lines[$i] }
    return $lines.Count
}

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
function Folder-Size($dirs) {
    $sum = 0
    foreach ($d in $dirs) { if (Test-Path $d) { $sum += (Get-ChildItem $d -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum } }
    return $sum
}

$form.Show(); Pump
try {
    # An update can't replace libraries a running Nova has loaded: stop it first
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -like "*$Root*nova.py*" -or ($_.CommandLine -like "*core.app*" -and $_.ExecutablePath -like "$Root*") } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

    Step "Finding Python"
    $Base = Find-Python
    if (-not $Base) {
        if (-not (Has "winget")) { throw "Nova needs Python 3.11 to 3.13. Install it from python.org/downloads, then run setup again." }
        if (-not (Ask "Nova needs Python 3.12, which isn't installed. Install it now? (about 30 MB, just for you, no admin needed)")) {
            throw "Nova needs Python 3.11 to 3.13."
        }
        $detail.Text = "Installing Python 3.12…"
        [void](Run "winget" @("install", "-e", "--id", "Python.Python.3.12", "--scope", "user", "--accept-source-agreements", "--accept-package-agreements"))
        Refresh-Path
        $Base = Find-Python
        if (-not $Base) { throw "Python was installed but can't be found yet. Sign out and back in, then run setup again." }
    }
    $detail.Text = "Using $Base"

    Step "Creating Nova's own Python environment"
    if (-not (Test-Path $Py)) {
        if ((Run $Base @("-m", "venv", $Venv)) -ne 0) { throw "Couldn't create Nova's Python environment (see details)." }
    }

    Step "Installing libraries"
    $detail.Text = "This takes a minute or two the first time."
    [void](Run $Py @("-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--upgrade", "pip"))
    if ((Run $Py @("-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", (Join-Path $Root "requirements.txt"))) -ne 0) {
        throw "Installing libraries failed. Check your internet connection; the details say more."
    }

    Step "Checking for an NVIDIA graphics card"
    $gpu = $false
    if (Has "nvidia-smi") { & nvidia-smi -L *> $null; $gpu = ($LASTEXITCODE -eq 0) }
    if ($gpu) {
        $detail.Text = "Found one: adding fast GPU speech recognition (about 1 GB)."
        [void](Run $Py @("-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", (Join-Path $Root "requirements-gpu.txt")))
    } else { $detail.Text = "None found: speech recognition will use the processor." }

    Step "Downloading the speech models (about 2 GB, once)"
    $hub = Join-Path $env:USERPROFILE ".cache\huggingface\hub"
    $modelDirs = @((Join-Path $hub "models--Systran--faster-whisper-small"), (Join-Path $hub "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"))
    $start = ($script:n - 1) / $Steps
    $code = Run $Py @("-c", "from faster_whisper.utils import download_model as d; d('small'); d('large-v3-turbo'); print('Models ready.')") {
        $size = Folder-Size $modelDirs
        $detail.Text = "{0:N0} MB of about {1:N0} MB" -f ($size / 1MB), ($ModelBytes / 1MB)
        Progress ($start + [Math]::Min([double]0.99, [double]($size / $ModelBytes)) / $Steps)
    }
    if ($code -ne 0) { throw "Downloading the speech models failed. Check your internet connection and run setup again." }
    New-Item -ItemType Directory -Force (Join-Path $Root "data") | Out-Null
    New-Item -ItemType File -Force (Join-Path $Root "data\models-ready") | Out-Null

    Step "Downloading Nova's natural voice (about 330 MB, once)"
    $part = Join-Path $Root "data\tts\kokoro.tar.bz2.part"
    Push-Location $Root
    $code = Run $Py @("-m", "core.tts", "download") {
        if (Test-Path $part) { $detail.Text = "{0:N0} MB of about 330 MB" -f ((Get-Item $part).Length / 1MB) } else { $detail.Text = "Unpacking…" }
    }
    Pop-Location
    if ($code -ne 0) { Note "The natural voice didn't download; Nova will use the Windows voice. Settings > Voice can retry." }

    Step "Adding Nova to the Start menu"
    Push-Location $Root; & $Py -m core.icon $icoPath; Pop-Location
    $shell = New-Object -ComObject WScript.Shell
    function Make-Shortcut($path) {
        $s = $shell.CreateShortcut($path)
        $s.TargetPath = $PyW
        $s.Arguments = "`"$(Join-Path $Root 'nova.py')`""
        $s.WorkingDirectory = $Root
        $s.IconLocation = $icoPath
        $s.Description = "Nova voice assistant"
        $s.Save()
    }
    Make-Shortcut (Join-Path ([Environment]::GetFolderPath("Programs")) "Nova.lnk")
    $startup = Join-Path ([Environment]::GetFolderPath("Startup")) "Nova.lnk"
    if (Test-Path $startup) { Make-Shortcut $startup }  # keep start-at-login pointing at this copy; the Nova window turns it on or off
    if ($Engine) {
        & $Py -c "import json, pathlib, sys; p = pathlib.Path(sys.argv[1]); c = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}; c.setdefault('brain', {})['engine'] = sys.argv[2]; p.write_text(json.dumps(c, indent=2), encoding='utf-8')" (Join-Path $Root "config.json") $Engine
    }

    Step "Running Nova's self-checks"
    Push-Location $Root; $code = Run $Py @("tests.py"); Pop-Location
    if ($code -ne 0) { throw "Nova's self-checks failed (see details). Please report this." }

    Progress 1
    $script:finished = $true
    $title.Text = "Nova is installed"
    $status.Text = "Opening Nova. It will walk you through the microphone, your AI and your shortcut."
    $detail.Text = "Nova lives in the hidden icons area next to the clock (the ^ arrow)."
    $button.Text = "Close"; $button.BackColor = $Accent
    Start-Process -FilePath $PyW -ArgumentList "`"$(Join-Path $Root 'nova.py')`"" -WorkingDirectory $Root
    $until = (Get-Date).AddSeconds(6)
    while ($form.Visible -and (Get-Date) -lt $until) { Pump }
    if ($form.Visible) { $form.Close() }
} catch {
    $script:finished = $true
    $dot.BackColor = $Bad
    $title.Text = if ($script:cancelled) { "Setup cancelled" } else { "Setup stopped" }
    $status.ForeColor = $Bad; $status.Text = "$($_.Exception.Message)"
    $detail.Text = "Nothing outside the Nova folder was changed. Run setup again any time."
    $button.Text = "Close"
    Note "ERROR: $($_.Exception.Message)"
    New-Item -ItemType Directory -Force (Join-Path $Root "data") | Out-Null
    $log.Text | Set-Content -Encoding utf8 (Join-Path $Root "data\setup.log")
    if (-not $script:cancelled) { $log.Visible = $true; Layout }
    while ($form.Visible) { Pump }
}
