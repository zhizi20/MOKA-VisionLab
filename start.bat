@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PATH=%ProgramFiles%\nodejs;%ProgramFiles(x86)%\nodejs;%PATH%"

echo.
echo ==============================================
echo  Web UI:  http://127.0.0.1:5174
echo  Login:   http://127.0.0.1:5174/login
echo  Account: admin / admin123
echo  API:     http://127.0.0.1:8000
echo ==============================================
echo.

if not exist "backend\.venv\Scripts\python.exe" (
  echo [ERROR] backend\.venv not found.
  echo Run: powershell -File backend\scripts\setup_venv.ps1
  pause
  exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] npm not found. Install Node.js, then retry.
  pause
  exit /b 1
)

if not exist "frontend\node_modules\" (
  echo Installing frontend dependencies...
  pushd frontend
  call npm install
  if errorlevel 1 (
    echo [ERROR] npm install failed.
    popd
    pause
    exit /b 1
  )
  popd
)

start "MOKA-VisionLab-Backend" /D "%~dp0backend" cmd /k ".venv\Scripts\python.exe app.py"
start "MOKA-VisionLab-Frontend" /D "%~dp0frontend" cmd /k "npm run dev"

timeout /t 5 /nobreak >nul
start "" "http://127.0.0.1:5174"

echo Started two windows: Backend and Frontend.
echo Close those two windows to stop.
echo Open: http://127.0.0.1:5174
echo.
pause
