@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PATH=%ProgramFiles%\nodejs;%ProgramFiles(x86)%\nodejs;%PATH%"

set "LAN_IP="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$wlan = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.InterfaceAlias -match 'WLAN|Wi-?Fi' -and $_.IPAddress -like '192.168.*' } | Select-Object -ExpandProperty IPAddress -First 1; if ($wlan) { $wlan; exit }; $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notmatch '^127\\.' -and $_.IPAddress -notmatch '^169\\.254\\.' } | Select-Object -ExpandProperty IPAddress; $pick = $ips | Where-Object { $_ -like '192.168.*' } | Select-Object -First 1; if (-not $pick) { $pick = $ips | Where-Object { $_ -like '10.*' } | Select-Object -First 1 }; if (-not $pick) { $pick = $ips | Select-Object -First 1 }; if ($pick) { $pick }"`) do set "LAN_IP=%%I"
if not defined LAN_IP set "LAN_IP=127.0.0.1"

echo.
echo ==============================================
echo  You:       http://%LAN_IP%:5174/login
echo  Colleagues (same Wi-Fi):
echo             http://%LAN_IP%:5174/login
echo  Account:   admin / admin123
echo  Keep this PC and the two black windows running.
echo ==============================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0open-lan.ps1" -Quiet >nul 2>&1

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
start "" "http://%LAN_IP%:5174/login"

echo Started two windows: Backend and Frontend.
echo Close those two windows to stop.
echo Open: http://%LAN_IP%:5174/login
echo.
pause
