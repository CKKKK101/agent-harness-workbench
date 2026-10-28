param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'Missing .venv. Run: py -m uv sync --extra dev --frozen'
}
Write-Host "Harness Studio: http://127.0.0.1:$Port/"
Write-Host "API documentation: http://127.0.0.1:$Port/docs"
& $taskPython -m harness_workbench.cli serve --port $Port
exit $LASTEXITCODE

