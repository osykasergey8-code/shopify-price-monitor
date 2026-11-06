@echo off
REM Runs the monitor every day at 08:00 via Windows Task Scheduler.
cd /d "%~dp0"
schtasks /Create /F /SC DAILY /ST 08:00 /TN "Shopify Price Monitor" /TR "\"%~dp0run.bat\" auto"
echo.
echo Scheduled: every day at 08:00. To remove: schtasks /Delete /TN "Shopify Price Monitor" /F
pause
