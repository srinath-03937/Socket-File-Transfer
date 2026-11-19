@echo off
REM run_client.bat — Windows convenience script to start the file-transfer client.
REM Open a NEW terminal window and run this script for each client instance.

echo ============================================================
echo   Multi-Threaded File Transfer Client — Starting...
echo ============================================================
echo.

cd /d "%~dp0\client"
python client.py

pause
