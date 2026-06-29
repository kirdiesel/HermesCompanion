$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonCandidates = @(
    (Join-Path $repo ".venv\Scripts\python.exe"),
    "C:\Users\AIuser\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
)
$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) {
    throw "No supported Python runtime found for nightly Git checkpoint."
}

$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$logPath = Join-Path $logDir "nightly_git_checkpoint.log"

$env:NIGHTLY_GIT_ALLOW_WRITE = "1"
& $python (Join-Path $PSScriptRoot "nightly_git_checkpoint.py") --repo $repo --execute 2>&1 |
    Tee-Object -FilePath $logPath -Append
exit $LASTEXITCODE
