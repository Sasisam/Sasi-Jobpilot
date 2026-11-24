@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Select an installed Python. Prefer versions with broad package compatibility.
set "PY_LAUNCHER="
where py >nul 2>nul
if not errorlevel 1 (
  py -3.12 --version >nul 2>nul && set "PY_LAUNCHER=py -3.12"
  if not defined PY_LAUNCHER py -3.11 --version >nul 2>nul && set "PY_LAUNCHER=py -3.11"
  if not defined PY_LAUNCHER py -3.10 --version >nul 2>nul && set "PY_LAUNCHER=py -3.10"
  if not defined PY_LAUNCHER py -3.15 --version >nul 2>nul && set "PY_LAUNCHER=py -3.15"
  if not defined PY_LAUNCHER py -3.14 --version >nul 2>nul && set "PY_LAUNCHER=py -3.14"
  if not defined PY_LAUNCHER py -3.13 --version >nul 2>nul && set "PY_LAUNCHER=py -3.13"
)
if not defined PY_LAUNCHER (
  where python >nul 2>nul
  if not errorlevel 1 set "PY_LAUNCHER=python"
)
if not defined PY_LAUNCHER (
  echo ERROR: Python was not found.
  echo Install Python 3.12 from https://www.python.org/downloads/ and enable Add Python to PATH.
  pause
  exit /b 1
)

echo Using Python:
%PY_LAUNCHER% --version
%PY_LAUNCHER% -c "import sys; print('Interpreter:', sys.executable); print('Version:', sys.version.split()[0])"

REM Recreate the virtual environment if it was created with a different Python version.
if exist ".venv\Scripts\python.exe" (
  %PY_LAUNCHER% -c "import sys,subprocess; p=subprocess.check_output(['.venv\\Scripts\\python.exe','-c','import sys; print(str(sys.version_info.major)+\'.\'+str(sys.version_info.minor))'],text=True).strip(); raise SystemExit(0 if p == str(sys.version_info.major)+'.'+str(sys.version_info.minor) else 1)"
  if errorlevel 1 (
    echo Existing virtual environment uses a different Python version. Recreating it...
    rmdir /s /q .venv
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating JobPilot virtual environment...
  %PY_LAUNCHER% -m venv .venv
  if errorlevel 1 goto :error
)

echo.
echo Installing and checking JobPilot dependencies...
".venv\Scripts\python.exe" -m ensurepip --upgrade
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :dependency_error

".venv\Scripts\python.exe" -c "import fastapi, uvicorn; print('FastAPI and Uvicorn are installed successfully.')"
if errorlevel 1 goto :dependency_error

echo.
echo Installing Playwright Chromium browser...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 echo WARNING: Chromium installation failed. The dashboard may run, but browser automation may not work.

if not exist ".env" copy ".env.example" ".env" >nul

echo.
echo Starting JobPilot at http://127.0.0.1:8000
echo Close this window or press Ctrl+C to stop.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
if errorlevel 1 goto :error
exit /b 0

:dependency_error
echo.
echo ERROR: One or more Python packages could not be installed for this Python version.
echo Python 3.15 support depends on the availability of compatible package releases.
echo Recommended fix: install Python 3.12, then run this file again.
echo Download: https://www.python.org/downloads/release/python-31210/
pause
exit /b 1

:error
echo.
echo ERROR: JobPilot setup or startup failed. Read the message above.
echo Check your internet connection and Python installation.
pause
exit /b 1
