# Simple startup script for Foqal CareOS
$REPO = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "=== Foqal CareOS - Starting Services ===" -ForegroundColor Cyan

Write-Host "[1/5] Main API on 7015..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$REPO'; py -m uvicorn backend.app.main:app --port 7015 --reload"
Start-Sleep 1

Write-Host "[2/5] Data Server on 7016..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$REPO'; py -m uvicorn backend.app.data_server:app --port 7016 --reload"
Start-Sleep 1

Write-Host "[3/5] Billing Frontend on 4990..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$REPO\frontend'; npm run dev -- --port 4990"
Start-Sleep 1

Write-Host "[4/5] Ward API on 7816..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$REPO\sabari_project\backend'; py -m uvicorn main:app --port 7816 --reload"
Start-Sleep 1

Write-Host "[5/5] Ward Frontend on 4985..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$REPO\sabari_project'; npm run dev -- --port 4985"

Write-Host ""
Write-Host "All services started!" -ForegroundColor Green
