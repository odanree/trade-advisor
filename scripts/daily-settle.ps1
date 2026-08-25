# daily-settle.ps1 -- Run `trade-advisor settle` and append output to a dated log file.
# PowerShell 5.1-compatible (no && chains, no ternaries). Exits with the command's exit code.

Set-Location -Path 'C:\Users\Danh\Documents\Projects\trade-advisor'

$logsDir = Join-Path (Get-Location) 'logs'
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}

$env:PYTHONUNBUFFERED = '1'

$dateStamp = Get-Date -Format 'yyyy-MM-dd'
$logFile = Join-Path $logsDir "settle-$dateStamp.log"

& '.venv\Scripts\trade-advisor.exe' settle *>&1 | Out-File -FilePath $logFile -Append -Encoding utf8

exit $LASTEXITCODE
