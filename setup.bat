@echo off
cd /d "%~dp0"
echo Creating virtual environment...
python -m venv .venv || (echo Python not found. Install it from python.org and tick "Add to PATH". & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist .env copy .env.example .env >nul
echo.
echo Done. Next: run check.bat, then run.bat
pause
