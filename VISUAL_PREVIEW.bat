@echo off
chcp 65001 > nul
echo ========================================
echo   Quick Visual Setup
echo ========================================
echo.

echo This will prepare dashboard for visual preview
echo (all data will be 0 until you enter real data)
echo.
pause

echo.
echo [1/3] Running migration...
python migrate_db.py
echo.

echo [2/3] Creating basic structure...
python init_visual.py
echo.

echo [3/3] Starting server...
echo.
echo ========================================
echo   Opening dashboard...
echo   http://localhost:8000
echo.
echo   You will see:
echo   - 3 aircraft cards (BAT, BAR, BAQ)
echo   - All values at 0.0 hrs / 0 cyc
echo   - 4 engine positions (all empty)
echo.
echo   Press Ctrl+C to stop server
echo ========================================
echo.

start http://localhost:8000
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
