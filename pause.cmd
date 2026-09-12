@echo off
title Pausing RTJobs
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pause.ps1"
echo.
pause
