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

Step "Transcripts in Roman letters" $train @("helpers\hinglish_train\romanize.py")
Step "LibriSpeech punctuation" $nova @("helpers\hinglish_train\punctuate.py")
Step "Training trial" $train @("helpers\hinglish_train\train.py", "--batch", "4", "--max-steps", "20")
Step "Training" $train @("helpers\hinglish_train\train.py", "--batch", "4")
Step "Scores" $nova @("helpers\hinglish_train\evaluate.py")
Step "Model card" $train @("helpers\hinglish_train\publish.py", "--card-only")
Write-Host "`nDone $(Get-Date -Format HH:mm). Scores: data\hinglish-ship\scores.json"
