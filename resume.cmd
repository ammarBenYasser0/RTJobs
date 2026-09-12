@echo off
title Resuming RTJobs
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0resume.ps1"
echo.
pause
