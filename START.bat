@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ================================
echo   STARTING FASTAPI SERVER
echo ================================
echo.
start cmd /k "python run_server.py"
