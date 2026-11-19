@echo off
REM run_dashboard.bat — Launch the web dashboard (Windows)
REM Double-click this file OR run it from any terminal.
REM Then open  http://127.0.0.1:8080  in your browser.

echo ============================================================
echo   Socket File Transfer — Web Dashboard
echo   Opening at http://127.0.0.1:8080
echo ============================================================
echo.

cd /d "%~dp0"
start "" http://127.0.0.1:8080
python dashboard\app.py

pause
