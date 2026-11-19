@echo off
REM run_server.bat — Windows convenience script to start the file-transfer server.
REM Double-click this file or run it from a Command Prompt / PowerShell terminal.

echo ============================================================
echo   Multi-Threaded File Transfer Server — Starting...
echo ============================================================
echo.

cd /d "%~dp0\server"
python server.py

pause
