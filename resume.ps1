param()

# Move to the script's directory so docker compose finds the yaml file
Set-Location -Path $PSScriptRoot

Write-Host "=== Resuming RTJobs ===" -ForegroundColor Cyan
Write-Host "Starting scheduler and scraper containers..." -ForegroundColor Yellow

docker compose up -d

Write-Host ""
Write-Host "Checking Container Health:" -ForegroundColor Yellow
docker ps --format "table {{.Names}}`t{{.Status}}`t{{.RunningFor}}" | Select-String -Pattern "rtjobs|ofelia|NAMES"

Write-Host ""
Write-Host "RTJobs has been resumed successfully." -ForegroundColor Green
Write-Host "Tip: Run '.\status.ps1' to check recent runs and database status." -ForegroundColor Cyan
