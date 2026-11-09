# v2 of the master model, unattended (Windows), on the data run_all.ps1 already prepared: a trial, training with
# code-mix splicing and the encoder's top layers, then scores and its model card. Earlier models keep their scores
# (scores.json), so only this run is scored. Start it as its own process, so closing a terminal (or the app it runs in)
# doesn't stop it:
#   Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','helpers\hinglish_train\run_v2.ps1','-Name','v2b' -RedirectStandardOutput data\hinglish-ship\v2b.log -WindowStyle Hidden
param([string]$Name = "v2", [int]$Batch = 4, [int]$Accumulate = 1)
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
$train = "data\hinglish-train\.venv\Scripts\python.exe"
$nova = ".venv\Scripts\python.exe"
$v2 = @("--name", $Name, "--splice", "0.2", "--encoder-layers", "4", "--batch", "$Batch", "--accumulate", "$Accumulate")

function Step($label, $exe, $arguments) {
    Write-Host "`n=== $label ($(Get-Date -Format HH:mm)) ==="
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "$label failed (exit $LASTEXITCODE)" }
}

Step "Training trial" $train (@("helpers\hinglish_train\train.py") + $v2 + @("--max-steps", "20"))
Step "Training $Name" $train (@("helpers\hinglish_train\train.py") + $v2)
Step "Scores" $nova @("helpers\hinglish_train\evaluate.py", "--model", "$Name=data\hinglish-ship\$Name\ct2:hi")
Step "Model card" $train @("helpers\hinglish_train\publish.py", "--dir", $Name, "--card-only")
Write-Host "`nDone $(Get-Date -Format HH:mm). Scores: data\hinglish-ship\scores.json"
