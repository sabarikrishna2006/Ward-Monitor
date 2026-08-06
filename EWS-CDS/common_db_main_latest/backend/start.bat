@echo off
echo Starting Discharge Summary AI backends...

:: Kill any existing servers on these ports
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":7015 " ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":7016 " ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>&1

timeout /t 1 /nobreak >nul

echo [1/2] Starting DATA server on port 7016 (no reload - stable)...
start "DATA SERVER :7016" cmd /k "cd /d %~dp0 && python -m uvicorn app.data_server:app --port 7016"

timeout /t 2 /nobreak >nul

echo [2/2] Starting UI server on port 7015 (with reload for dev)...
start "UI SERVER :7015" cmd /k "cd /d %~dp0 && python -m uvicorn app.main:app --port 7015 --reload"

echo.
echo Both servers starting. Wait ~10 seconds for data server to load admissions cache.
echo UI:   http://localhost:7015
echo Data: http://localhost:7016
