@echo off
title RTJobs Status
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0status.ps1"
echo.
pause
