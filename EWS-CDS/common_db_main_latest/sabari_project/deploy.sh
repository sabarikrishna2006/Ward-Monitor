#!/bin/bash
# ============================================================
# Foqal CareOS — Ward Monitor (Sabari Project)
# Deploy / restart script for the Linux server
# Run from the repo root: bash deploy.sh
# ============================================================

set -e   # exit on any error

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$REPO_DIR/backend"
VENV_DIR="$REPO_DIR/.venv"
LOG_DIR="$REPO_DIR/logs"

FRONTEND_PORT=6040
BACKEND_PORT=6030

mkdir -p "$LOG_DIR"

echo ""
echo "==================================================="
echo " Foqal CareOS · Ward Monitor  — Deploy"
echo " Repo  : $REPO_DIR"
echo " Ports : Frontend=$FRONTEND_PORT  Backend=$BACKEND_PORT"
echo " Logs  : $LOG_DIR/"
echo "==================================================="
echo ""

# ── 0. Ensure Node/NVM is available ─────────────────────────
echo "[0/5] Checking for Node.js..."
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"   # load nvm if already installed

if ! command -v npm &> /dev/null; then
    echo "      npm not found — installing NVM + Node.js 20..."
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
    nvm install 20
    nvm use 20
else
    echo "      Node $(node -v) / npm $(npm -v)"
fi

# ── 1. Python virtualenv ─────────────────────────────────────
echo "[1/5] Setting up Python virtualenv..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
pip install -r "$BACKEND_DIR/requirements.txt" -q
echo "      Python deps OK"

# ── 2. Build the SQLite demo database ────────────────────────
echo "[2/5] Building demo database (SQLite)..."
cd "$BACKEND_DIR"
mkdir -p data
if [ ! -f "data/ward_careos.db" ]; then
    python3 build_demo_db.py
    echo "      Database created at backend/data/ward_careos.db"
else
    echo "      Database already exists — skipping rebuild."
    echo "      (Delete backend/data/ward_careos.db to force rebuild)"
fi
cd "$REPO_DIR"

# ── 3. Node modules ──────────────────────────────────────────
echo "[3/5] Installing npm packages..."
npm install --silent
echo "      npm packages OK"

# ── 4. Kill old screen sessions if running ──────────────────
echo "[4/5] Stopping old screen sessions (if any)..."
screen -S ward-api      -X quit 2>/dev/null && echo "      Stopped ward-api" || true
screen -S ward-frontend -X quit 2>/dev/null && echo "      Stopped ward-frontend" || true
sleep 2

# ── 5a. Start FastAPI backend ─────────────────────────────────
echo "[5a/5] Starting FastAPI backend on port $BACKEND_PORT..."
echo "       Logs → $LOG_DIR/ward-api.log"
screen -dmS ward-api bash -c "
    cd '$BACKEND_DIR'
    source '$VENV_DIR/bin/activate'
    echo '[ward-api] Starting uvicorn on port $BACKEND_PORT...'
    while true; do
        uvicorn main:app --host 0.0.0.0 --port $BACKEND_PORT 2>&1 | tee -a '$LOG_DIR/ward-api.log'
        echo '[ward-api] crashed — restarting in 5s...' | tee -a '$LOG_DIR/ward-api.log'
        sleep 5
    done
"

# Wait 3 seconds and verify backend is actually listening
sleep 3
if curl -s "http://localhost:$BACKEND_PORT/docs" > /dev/null 2>&1; then
    echo "      ✅ Backend is UP at http://localhost:$BACKEND_PORT"
else
    echo "      ⚠️  Backend may still be starting. Check logs: tail -f $LOG_DIR/ward-api.log"
fi

# ── 5b. Start Vite frontend ───────────────────────────────────
echo "[5b/5] Starting Vite frontend on port $FRONTEND_PORT..."
echo "       Proxy: /api → http://localhost:$BACKEND_PORT"
echo "       Logs  → $LOG_DIR/ward-frontend.log"
screen -dmS ward-frontend bash -c "
    export NVM_DIR=\"\$HOME/.nvm\"
    [ -s \"\$NVM_DIR/nvm.sh\" ] && \. \"\$NVM_DIR/nvm.sh\"
    cd '$REPO_DIR'
    echo '[ward-frontend] Starting Vite on port $FRONTEND_PORT...'
    while true; do
        VITE_API_URL=http://localhost:$BACKEND_PORT \
            npm run dev -- --host 0.0.0.0 --port $FRONTEND_PORT 2>&1 | tee -a '$LOG_DIR/ward-frontend.log'
        echo '[ward-frontend] crashed — restarting in 5s...' | tee -a '$LOG_DIR/ward-frontend.log'
        sleep 5
    done
"

echo ""
echo "==================================================="
echo " ✅ All services started!"
echo ""
echo " Ward Monitor  : http://72.60.102.196:$FRONTEND_PORT/"
echo " Backend Docs  : http://72.60.102.196:$BACKEND_PORT/docs"
echo ""
echo " Demo Logins:"
echo "   Ward Nurse  : rekha.devi   / WardNurse@2026"
echo "   Charge Nurse: leena.kurup  / ChargeNurse@2026"
echo ""
echo " Check running  : screen -ls"
echo " Backend logs   : tail -f $LOG_DIR/ward-api.log"
echo " Frontend logs  : tail -f $LOG_DIR/ward-frontend.log"
echo " Attach backend : screen -r ward-api"
echo " Attach frontend: screen -r ward-frontend"
echo " Stop all       : screen -S ward-api -X quit; screen -S ward-frontend -X quit"
echo "==================================================="
