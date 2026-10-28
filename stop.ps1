$ErrorActionPreference = 'Stop'
$taskPidFile = Join-Path $PSScriptRoot '.workbench\server.pid'
if (-not (Test-Path -LiteralPath $taskPidFile)) {
    Write-Host 'No background server PID file found. For a foreground server, press Ctrl+C.'
    exit 0
}
$taskServerId = [int](Get-Content -LiteralPath $taskPidFile)
$taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$taskServerId"
if ($null -eq $taskProcess) {
    Write-Host 'Server has already stopped.'
    exit 0
}
$taskExpectedPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (($taskProcess.ExecutablePath -ne $taskExpectedPython) -or
    ($taskProcess.CommandLine -notmatch 'harness_workbench\.cli.*serve')) {
    throw 'PID belongs to a different process. Refusing to stop it.'
}
& taskkill.exe /PID $taskServerId /T /F | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'Could not stop the verified server process tree.'
}
Write-Host 'Background workbench server stopped.'

