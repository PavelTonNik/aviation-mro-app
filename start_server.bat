@echo off
cd /d "%~dp0"
echo ================================
echo   STARTING FASTAPI SERVER
echo ================================
echo.
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
pause
