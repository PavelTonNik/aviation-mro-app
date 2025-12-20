@echo off
chcp 65001 > nul
echo ========================================
echo   Dashboard Diagnostics
echo ========================================
echo.

echo [Step 1/3] Checking database structure...
python check_db.py
echo.

echo [Step 2/3] Testing API endpoints...
echo (Server must be running on port 8000)
python test_api.py
echo.

echo [Step 3/3] Recommendations:
echo.
echo If dashboard is empty:
echo   1. Check browser console (F12) for errors
echo   2. Make sure server is running (START.bat)
echo   3. Run: python migrate_db.py
echo   4. Run: python add_test_data.py
echo.

pause
