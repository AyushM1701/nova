# Steps 2-5 after prepare.py, unattended (Windows): transcripts, training, scores, model card. Nova can keep running.
#   powershell -ExecutionPolicy Bypass -File helpers\hinglish_train\run_all.ps1
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
$train = "data\hinglish-train\.venv\Scripts\python.exe"  # the training environment (PyTorch)
$nova = ".venv\Scripts\python.exe"                       # Nova's own (faster-whisper), for the scores

function Step($name, $exe, $arguments) {
    Write-Host "`n=== $name ($(Get-Date -Format HH:mm)) ==="
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "$name failed (exit $LASTEXITCODE)" }
}

# a failed call leaves its lines out; each pass retries them, and training waits until 95% are ready (a usage
# limit can stop every call for hours: then this stops, and running it again later carries on where it left off)
foreach ($pass in 1..3) {
    Write-Host "`n=== Transcripts, pass $pass ($(Get-Date -Format HH:mm)) ==="
    & $train "helpers\hinglish_train\romanize.py"
    if ($LASTEXITCODE -eq 0) { break }
    if ($pass -eq 3) { throw "Transcripts aren't ready (a usage limit?): run this again later" }
}
Step "Training trial" $train @("helpers\hinglish_train\train.py", "--batch", "4", "--max-steps", "20")
Step "Training" $train @("helpers\hinglish_train\train.py", "--batch", "4")
Step "Scores" $nova @("helpers\hinglish_train\evaluate.py")
Step "Model card" $train @("helpers\hinglish_train\publish.py", "--card-only")
Write-Host "`nDone $(Get-Date -Format HH:mm). Scores: data\hinglish-ship\scores.json"
