param([int]$Port = 8001)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'Run uv sync --locked from Content-Agent first.'
}
Push-Location -LiteralPath $taskRoot
try {
    & $taskPython -m scripts.check_readiness
    if ($LASTEXITCODE -ne 0) { throw 'Complete the configuration checks above before starting.' }
    & $taskPython -m uvicorn app.main:app --host 127.0.0.1 --port $Port `
        --proxy-headers --forwarded-allow-ips '127.0.0.1,::1'
} finally {
    Pop-Location
}
