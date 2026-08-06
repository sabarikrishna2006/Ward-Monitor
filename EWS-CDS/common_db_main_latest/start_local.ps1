# ============================================================
# Foqal CareOS — Integrated Hospital · Local Dev Launcher
# Launches all 5 services in separate Windows PowerShell tabs
# 
# Usage: powershell -ExecutionPolicy Bypass -File start_local.ps1
# ============================================================

$ErrorActionPreference = "Continue"

$REPO_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$ASHMIT_DIR = $REPO_DIR
$SABARI_DIR = Join-Path $REPO_DIR "sabari_project"
$ASHMIT_VENV = Join-Path $ASHMIT_DIR ".venv"
$SABARI_VENV = Join-Path $SABARI_DIR ".venv"

Write-Host ""
Write-Host "==================================================="
Write-Host " Foqal CareOS · Integrated Hospital — Local Dev"
Write-Host " Repo : $REPO_DIR"
Write-Host "==================================================="
Write-Host ""

# ── Check Python ────────────────────────────────────
Write-Host "[0/5] Checking Python installation..."
try {
    $pythonVersion = python --version 2>&1
    Write-Host "      $pythonVersion ✓"
} catch {
    Write-Host "      ERROR: Python not found. Please install Python 3.8+ and add to PATH."
    Exit 1
}

# ── Check Node.js ────────────────────────────────────
Write-Host "[0/5] Checking Node.js installation..."
try {
    $nodeVersion = node --version 2>&1
    Write-Host "      Node.js $nodeVersion ✓"
} catch {
    Write-Host "      ERROR: Node.js not found. Please install Node.js 18+ globally."
    Exit 1
}

# ── Setup Ashmit's venv ──────────────────────────────
Write-Host "[ASHMIT] Setting up Python environment..."
if (-not (Test-Path $ASHMIT_VENV)) {
    Write-Host "         Creating venv..."
    python -m venv $ASHMIT_VENV
}
$activateScript = Join-Path $ASHMIT_VENV "Scripts" "Activate.ps1"
if (Test-Path $activateScript) {
    & $activateScript
    Write-Host "         Installing dependencies..."
    pip install -q -r (Join-Path $ASHMIT_DIR "requirements.txt")
    Write-Host "         Python deps OK ✓"
} else {
    Write-Host "         ERROR: Could not activate venv"
    Exit 1
}

# ── Setup Sabari's venv ──────────────────────────────
Write-Host "[SABARI] Setting up Python environment..."
if (-not (Test-Path $SABARI_VENV)) {
    Write-Host "         Creating venv..."
    python -m venv $SABARI_VENV
}
$sabariActivate = Join-Path $SABARI_VENV "Scripts" "Activate.ps1"
if (Test-Path $sabariActivate) {
    & $sabariActivate
    Write-Host "         Installing dependencies..."
    pip install -q -r (Join-Path $SABARI_DIR "backend" "requirements.txt")
    Write-Host "         Python deps OK ✓"
} else {
    Write-Host "         ERROR: Could not activate Sabari's venv"
    Exit 1
}

# ── Create startup commands ──────────────────────────
Write-Host ""
Write-Host "[STARTUP] Launching services in separate terminals..."
Write-Host ""

$startupScripts = @()

# 1. Ashmit's Main API (port 7015)
$cmd1 = @"
`$activateScript = `"$activateScript`"
if (Test-Path `$activateScript) { & `$activateScript }
Set-Location `"$ASHMIT_DIR`"
Write-Host `"[MAIN API] Starting on port 7015...`"
Write-Host `"[MAIN API] Docs available at http://localhost:7015/docs`"
while (`$true) {
    uvicorn backend.app.main:app --host 0.0.0.0 --port 7015
    Write-Host `"[MAIN API] Crashed, restarting in 5s...`"
    Start-Sleep -Seconds 5
}
"@

# 2. Ashmit's Data Server (port 7016)
$cmd2 = @"
`$activateScript = `"$activateScript`"
if (Test-Path `$activateScript) { & `$activateScript }
Set-Location `"$ASHMIT_DIR`"
Write-Host `"[DATA SERVER] Starting on port 7016...`"
Write-Host `"[DATA SERVER] Docs available at http://localhost:7016/docs`"
while (`$true) {
    uvicorn backend.app.data_server:app --host 0.0.0.0 --port 7016
    Write-Host `"[DATA SERVER] Crashed, restarting in 5s...`"
    Start-Sleep -Seconds 5
}
"@

# 3. Ashmit's Frontend (port 4990)
$cmd3 = @"
Set-Location `"$ASHMIT_DIR\frontend`"
Write-Host `"[FRONTEND] Installing dependencies...`"
npm install --silent
Write-Host `"[FRONTEND] Starting on port 4990...`"
Write-Host `"[FRONTEND] Available at http://localhost:4990`"
while (`$true) {
    npm run dev -- --host 0.0.0.0 --port 4990
    Write-Host `"[FRONTEND] Crashed, restarting in 5s...`"
    Start-Sleep -Seconds 5
}
"@

# 4. Sabari's Ward Monitor API (port 7816)
$cmd4 = @"
`$sabariActivate = `"$sabariActivate`"
if (Test-Path `$sabariActivate) { & `$sabariActivate }
Set-Location `"$SABARI_DIR\backend`"
Write-Host `"[WARD API] Starting on port 7816...`"
Write-Host `"[WARD API] Docs available at http://localhost:7816/docs`"
while (`$true) {
    uvicorn main:app --host 0.0.0.0 --port 7816
    Write-Host `"[WARD API] Crashed, restarting in 5s...`"
    Start-Sleep -Seconds 5
}
"@

# 5. Sabari's Ward Monitor Frontend (port 4985)
$cmd5 = @"
Set-Location `"$SABARI_DIR`"
Write-Host `"[WARD FRONTEND] Installing dependencies...`"
npm install --silent
Write-Host `"[WARD FRONTEND] Starting on port 4985...`"
Write-Host `"[WARD FRONTEND] Available at http://localhost:4985`"
`$env:VITE_PORT=4985
`$env:VITE_HOST=0.0.0.0
`$env:VITE_API_URL=http://localhost:7816
while (`$true) {
    npm run dev -- --host 0.0.0.0 --port 4985
    Write-Host `"[WARD FRONTEND] Crashed, restarting in 5s...`"
    Start-Sleep -Seconds 5
}
"@

# ── Launch all 5 terminals ──────────────────────────
Write-Host "[STARTUP] Opening Terminal 1: Main API (port 7015)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd1

Write-Host "[STARTUP] Opening Terminal 2: Data Server (port 7016)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd2

Write-Host "[STARTUP] Opening Terminal 3: Ashmit Frontend (port 4990)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd3

Write-Host "[STARTUP] Opening Terminal 4: Ward Monitor API (port 7816)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd4

Write-Host "[STARTUP] Opening Terminal 5: Ward Monitor Frontend (port 4985)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd5

# ── Display status ───────────────────────────────────
Write-Host ""
Start-Sleep -Seconds 3
Write-Host "==================================================="
Write-Host " ✅ All services launching!"
Write-Host ""
Write-Host " ASHMIT'S PROJECT:"
Write-Host "   Frontend (Login)       : http://localhost:4990"
Write-Host "   Main API (RAG/Summary) : http://localhost:7015/docs"
Write-Host "   Data Server            : http://localhost:7016/docs"
Write-Host ""
Write-Host " SABARI'S WARD MONITOR:"
Write-Host "   Frontend (Dashboard)   : http://localhost:4985"
Write-Host "   API                    : http://localhost:7816/docs"
Write-Host ""
Write-Host " NEXT STEPS:"
Write-Host "   1. Open http://localhost:4990 in your browser"
Write-Host "   2. Log in as ward/charge nurse"
Write-Host "   3. You'll be redirected to Ward Monitor at http://localhost:4985"
Write-Host ""
Write-Host " MONITORING:"
Write-Host "   • Check all 5 terminal windows are running without errors"
Write-Host "   • Services auto-restart on crash (5s delay)"
Write-Host "   • Check Ctrl+Shift+Esc for process list (powershell.exe)"
Write-Host ""
Write-Host " TO STOP:"
Write-Host "   • Close each terminal window OR"
Write-Host "   • Run: Stop-LocalServices.ps1 (when created)"
Write-Host "==================================================="
Write-Host ""
