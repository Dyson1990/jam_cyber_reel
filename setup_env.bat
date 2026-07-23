@echo off
cd /d "%~dp0"

if exist ".venv" (
    echo .venv already exists.
    exit /b
)

echo Creating .venv ...
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
echo Done.
