@echo off
chcp 65001 > nul
echo ========================================
echo   Aviation MRO Dashboard Setup
echo ========================================
echo.

echo [1/3] Checking database migration...
python migrate_db.py
if errorlevel 1 (
    echo ERROR: Migration failed!
    pause
    exit /b 1
)
echo.

echo [2/3] Would you like to add test data? (Y/N)
set /p ADD_TEST="Enter choice: "
if /i "%ADD_TEST%"=="Y" (
    echo Adding test data...
    python add_test_data.py
    echo.
)

echo [3/3] Starting server...
echo.
echo ========================================
echo   Server will start at:
echo   http://localhost:8000
echo.
echo   Press Ctrl+C to stop
echo ========================================
echo.

uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
