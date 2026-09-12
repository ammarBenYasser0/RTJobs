param()

# Move to the script's directory so docker compose finds the yaml file
Set-Location -Path $PSScriptRoot

Write-Host "=== Pausing RTJobs Safely ===" -ForegroundColor Cyan
Write-Host "Sending graceful stop signal (15s grace period for active transactions)..." -ForegroundColor Yellow

docker compose stop -t 15

Write-Host ""
Write-Host "Container Status:" -ForegroundColor Yellow
docker compose ps -a

Write-Host ""
Write-Host "RTJobs has been safely paused." -ForegroundColor Green
Write-Host "No active database writes or browser locks remain. You can now safely restart or shut down your computer." -ForegroundColor Green
