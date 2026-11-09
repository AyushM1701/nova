# v2 of the master model, unattended (Windows), on the data run_all.ps1 already prepared: a trial, training with
# code-mix splicing and the encoder's top layers, then scores for turbo, v1, v2 and Oriserve's model (when converted:
# train.py --convert Oriserve/Whisper-Hindi2Hinglish-Prime).
#   powershell -ExecutionPolicy Bypass -File helpers\hinglish_train\run_v2.ps1 [-Batch 2 -Accumulate 2]
param([int]$Batch = 4, [int]$Accumulate = 1)
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
$train = "data\hinglish-train\.venv\Scripts\python.exe"
$nova = ".venv\Scripts\python.exe"
$v2 = @("--name", "v2", "--splice", "0.2", "--encoder-layers", "4", "--batch", "$Batch", "--accumulate", "$Accumulate")

function Step($name, $exe, $arguments) {
    Write-Host "`n=== $name ($(Get-Date -Format HH:mm)) ==="
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "$name failed (exit $LASTEXITCODE)" }
}

Step "Training trial" $train (@("helpers\hinglish_train\train.py") + $v2 + @("--max-steps", "20"))
Step "Training v2" $train (@("helpers\hinglish_train\train.py") + $v2)
$models = @("--model", "today: turbo + Hinglish prompt=large-v3-turbo:en-prompt",
            "--model", "trained=data\hinglish-ship\ct2:hi", "--model", "v2=data\hinglish-ship\v2\ct2:hi")
if (Test-Path "data\whisper-hindi2hinglish-prime-ct2") {
    $models += @("--model", "Oriserve Prime=data\whisper-hindi2hinglish-prime-ct2:en")
}
Step "Scores" $nova (@("helpers\hinglish_train\evaluate.py") + $models)
Step "Model card" $train @("helpers\hinglish_train\publish.py", "--dir", "v2", "--card-only")
Write-Host "`nDone $(Get-Date -Format HH:mm). Scores: data\hinglish-ship\scores.json"
