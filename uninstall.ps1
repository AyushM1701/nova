# Remove Nova from Windows: stops it, removes its shortcuts, and optionally its libraries and speech models.
# Your settings, logs and notes in this folder are left alone; delete the folder to remove those too.
$Root = $PSScriptRoot
function Ask($question) { (Read-Host "$question [y/N]") -match '^(y|yes)$' }

Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -like "*$Root*nova.py*" } |
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
Write-Host "Done. Claude Code / Codex were left installed; remove them separately if you want."
