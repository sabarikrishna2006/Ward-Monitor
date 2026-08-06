# ============================================================
# Foqal CareOS — Local Dev Launcher (CORRECTED)
# Launches all 5 services in separate terminal tabs
# ============================================================

$ErrorActionPreference = "Continue"

$REPO_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$ASHMIT_DIR = $REPO_DIR
$SABARI_DIR = Join-Path $REPO_DIR "sabari_project"

Write-Host ""
Write-Host "=================================================="
Write-Host " Foqal CareOS — Starting All 5 Services"
Write-Host "=================================================="
Write-Host ""

# ── Activate Python Ashmit ──────────────────────────
Write-Host "[1/5] Starting Main API (port 7015)..."
$ashmitActivate = Join-Path $ASHMIT_DIR ".venv" "Scripts" "Activate.ps1"
if (Test-Path $ashmitActivate) {
    Start-Process powershell -ArgumentList "-NoExit", "-Command", ". '$ashmitActivate'; cd '$ASHMIT_DIR'; py -m uvicorn backend.app.main:app --host 0.0.0.0 --port 7015 --reload"
    Write-Host "         Main API started on port 7015 ✓"
}

# ── Data Server ─────────────────────────────────────
Write-Host "[2/5] Starting Data Server (port 7016)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", ". '$ashmitActivate'; cd '$ASHMIT_DIR'; py -m uvicorn backend.app.data_server:app --host 0.0.0.0 --port 7016 --reload"
Write-Host "         Data Server started on port 7016 ✓"

# ── Frontend Ashmit ─────────────────────────────────
Write-Host "[3/5] Starting Unified Login Frontend (port 4990)..."
$frontendDir = Join-Path $ASHMIT_DIR "frontend"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$frontendDir'; npm run dev -- --host 0.0.0.0 --port 4990"
Write-Host "         Frontend started on port 4990 ✓"

# ── Ward Monitor API ────────────────────────────────
Write-Host "[4/5] Starting Ward Monitor API (port 7816)..."
$sabariActivate = Join-Path $SABARI_DIR ".venv" "Scripts" "Activate.ps1"
if (Test-Path $sabariActivate) {
    Start-Process powershell -ArgumentList "-NoExit", "-Command", ". '$sabariActivate'; cd '$SABARI_DIR'; cd backend; py -m uvicorn main:app --host 0.0.0.0 --port 7816 --reload"
    Write-Host "         Ward API started on port 7816 ✓"
}

# ── Ward Monitor Frontend ───────────────────────────
Write-Host "[5/5] Starting Ward Monitor Frontend (port 4985)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$SABARI_DIR'; npm run dev -- --host 0.0.0.0 --port 4985"
Write-Host "         Ward Frontend started on port 4985 ✓"

Write-Host ""
Write-Host "=================================================="
Write-Host " 🚀 All 5 Services Started!"
Write-Host "=================================================="
Write-Host ""
Write-Host " 📍 Access Points:"
Write-Host "    Unified Login   : http://localhost:4990"
Write-Host "    Ward Monitor    : http://localhost:4985"
Write-Host "    Main API Docs   : http://localhost:7015/docs"
Write-Host "    Data Server Docs: http://localhost:7016/docs"
Write-Host "    Ward API Docs   : http://localhost:7816/docs"
Write-Host ""
Write-Host " 🔧 Ports:"
Write-Host "    Ashmit Main API      : 7015"
Write-Host "    Ashmit Data Server   : 7016"
Write-Host "    Ashmit Frontend      : 4990"
Write-Host "    Sabari Ward API      : 7816"
Write-Host "    Sabari Ward Frontend : 4985"
Write-Host ""
Write-Host " ⏹️  To stop: Close the terminal windows"
Write-Host "=================================================="
