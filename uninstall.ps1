# Remove Nova from Windows: stops it, removes its shortcuts, and optionally its libraries and speech models.
# Your settings, logs and notes in this folder are left alone; delete the folder to remove those too.
$Root = $PSScriptRoot
function Ask($question) { (Read-Host "$question [y/N]") -match '^(y|yes)$' }

Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -like "*$Root*nova.py*" -or ($_.CommandLine -like "*core.app*" -and $_.ExecutablePath -like "$Root*") } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
foreach ($lnk in @((Join-Path ([Environment]::GetFolderPath("Programs")) "Nova.lnk"),
                   (Join-Path ([Environment]::GetFolderPath("Startup")) "Nova.lnk"))) {
    if (Test-Path $lnk) { Remove-Item $lnk }
}
Write-Host "Nova stopped and its shortcuts removed."

if (Ask "Also delete Nova's Python libraries (.venv)?") { Remove-Item -Recurse -Force (Join-Path $Root ".venv") }
$cache = Join-Path $env:USERPROFILE ".cache\huggingface\hub"
$models = @(Get-ChildItem $cache -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -in "models--Systran--faster-whisper-small", "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo" })
if ($models -and (Ask "Also delete the downloaded speech models (about 2 GB)?")) { $models | Remove-Item -Recurse -Force }
$voice = Join-Path $Root "data\tts"
if ((Test-Path $voice) -and (Ask "Also delete Nova's natural voice (about 380 MB)?")) { Remove-Item -Recurse -Force $voice }
Write-Host "Done. Claude Code / Codex were left installed; remove them separately if you want."
