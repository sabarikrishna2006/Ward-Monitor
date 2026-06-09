#!/bin/bash
# ============================================================
# Foqal CareOS — Ward Monitor (Sabari Project)
# Deploy / restart script for the shared Linux server
# Run from the repo root: bash deploy.sh
# ============================================================

set -e   # exit on any error

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$REPO_DIR/backend"
VENV_DIR="$REPO_DIR/.venv"

FRONTEND_PORT=5175
BACKEND_PORT=8003

echo ""
echo "==================================================="
echo " Foqal CareOS · Ward Monitor  — Deploy"
echo " Repo  : $REPO_DIR"
echo " Ports : Frontend=$FRONTEND_PORT  Backend=$BACKEND_PORT"
echo "==================================================="
echo ""

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

# Ensure Node/NVM is available
if ! command -v npm &> /dev/null; then
    echo "      npm not found. Attempting to load NVM..."
    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
    
    if ! command -v npm &> /dev/null; then
        echo "      NVM not found. Installing Node.js via NVM..."
        curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
        export NVM_DIR="$HOME/.nvm"
        [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
        nvm install 20
        nvm use 20
    fi
fi

npm install --silent
echo "      npm packages OK"

# ── 4. Kill old screen sessions if running ──────────────────
echo "[4/5] Stopping old screen sessions (if any)..."
screen -S ward-api      -X quit 2>/dev/null && echo "      Stopped ward-api" || true
screen -S ward-frontend -X quit 2>/dev/null && echo "      Stopped ward-frontend" || true
sleep 1

# ── 5. Start backend API ─────────────────────────────────────
echo "[5a/5] Starting FastAPI backend on port $BACKEND_PORT..."
screen -dmS ward-api bash -c "
    cd '$BACKEND_DIR'
    source '$VENV_DIR/bin/activate'
    while true; do
        uvicorn main:app --host 0.0.0.0 --port $BACKEND_PORT
        echo '[ward-api] crashed, restarting in 5s...'
        sleep 5
    done
"

# ── 5. Start frontend ─────────────────────────────────────────
echo "[5b/5] Starting Vite frontend on port $FRONTEND_PORT..."
screen -dmS ward-frontend bash -c "
    export NVM_DIR=\"\$HOME/.nvm\"
    [ -s \"\$NVM_DIR/nvm.sh\" ] && \. \"\$NVM_DIR/nvm.sh\"
    cd '$REPO_DIR'
    while true; do
        npm run dev -- --host 0.0.0.0 --port $FRONTEND_PORT
        echo '[ward-frontend] crashed, restarting in 5s...'
        sleep 5
    done
"

echo ""
echo "==================================================="
echo " ✅ All services started!"
echo ""
echo " Frontend : http://72.60.102.196:$FRONTEND_PORT/"
echo " Backend  : http://72.60.102.196:$BACKEND_PORT/docs"
echo ""
echo " To check running sessions:  screen -ls"
echo " To attach to logs:          screen -r ward-api"
echo "                             screen -r ward-frontend"
echo " To stop everything:         screen -S ward-api -X quit"
echo "                             screen -S ward-frontend -X quit"
echo "==================================================="
