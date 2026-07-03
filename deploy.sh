#!/bin/bash
# ============================================================
# Foqal CareOS — Integrated Hospital · Full Deploy Script
# Starts both Ashmit's Hospital Efficiency and
# Sabari's Ward Monitor projects together.
#
# Run from repo root:  bash deploy.sh
# ============================================================

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
ASHMIT_DIR="$REPO_DIR"            # Hospital_Efficiency root
SABARI_DIR="$REPO_DIR/sabari_project"

# ── Local secrets (never committed — see .env.secrets.example) ──────────────
# Exported here so every screen session below inherits them automatically.
if [ -f "$REPO_DIR/.env.secrets" ]; then
    set -a
    source "$REPO_DIR/.env.secrets"
    set +a
    echo "Loaded secrets from .env.secrets"
else
    echo "WARNING: $REPO_DIR/.env.secrets not found — CLOUD_SQL_PASS must already be exported in this shell, or the backends will crash-loop."
fi

echo ""
echo "==================================================="
echo " Foqal CareOS · Integrated Hospital — Full Deploy"
echo " Repo : $REPO_DIR"
echo "==================================================="
echo ""

# ── 0. Ensure Node.js & npm (via NVM) ────────────────────────
echo "[0/5] Checking for Node.js (npm)..."
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
else
    echo "      Node.js & npm are installed."
fi
echo ""


# ── Ashmit's project ─────────────────────────────────────────
echo "[ASHMIT] Setting up Python environment..."
if [ ! -d "$ASHMIT_DIR/.venv" ]; then
    python3 -m venv "$ASHMIT_DIR/.venv"
fi
source "$ASHMIT_DIR/.venv/bin/activate"
pip install -r "$ASHMIT_DIR/requirements.txt" -q
echo "         Python deps OK"

echo "[ASHMIT] Stopping old screen sessions..."
screen -S main      -X quit 2>/dev/null && echo "         Stopped main"      || true
screen -S data      -X quit 2>/dev/null && echo "         Stopped data"      || true
screen -S frontend  -X quit 2>/dev/null && echo "         Stopped frontend"  || true
sleep 1

echo "[ASHMIT] Starting backend main API (port 7015)..."
screen -dmS main bash -c "
    cd '$ASHMIT_DIR'
    source .venv/bin/activate
    while true; do
        uvicorn backend.app.main:app --host 0.0.0.0 --port 7015
        echo '[main] crashed, restarting in 8s...'; sleep 8
    done
"

echo "[ASHMIT] Starting data server (port 7016)..."
screen -dmS data bash -c "
    cd '$ASHMIT_DIR'
    source .venv/bin/activate
    while true; do
        uvicorn backend.app.data_server:app --host 0.0.0.0 --port 7016
        echo '[data] crashed, restarting in 8s...'; sleep 8
    done
"

echo "[ASHMIT] Starting frontend Vite dev server (port 4990)..."
screen -dmS frontend bash -c "
    export NVM_DIR=\"\$HOME/.nvm\"
    [ -s \"\$NVM_DIR/nvm.sh\" ] && \. \"\$NVM_DIR/nvm.sh\"
    cd '$ASHMIT_DIR/frontend'
    npm install --silent
    while true; do
        npm run dev -- --host 0.0.0.0 --port 4990
        echo '[frontend] crashed, restarting in 5s...'; sleep 5
    done
"

# ── Sabari's Ward Monitor ─────────────────────────────────────
echo ""
echo "[SABARI] Setting up Ward Monitor..."
if [ ! -d "$SABARI_DIR" ]; then
    echo "ERROR: sabari_project/ directory not found in repo root!"
    echo "       Make sure the sabari branch has the sabari_project/ folder."
    exit 1
fi

if [ ! -d "$SABARI_DIR/.venv" ]; then
    python3 -m venv "$SABARI_DIR/.venv"
fi
source "$SABARI_DIR/.venv/bin/activate"
pip install -r "$SABARI_DIR/backend/requirements.txt" -q
echo "         Python deps OK"

echo "[SABARI] Cloud SQL mode — no local database build needed."
mkdir -p "$SABARI_DIR/backend/data"

echo "[SABARI] Stopping old Ward Monitor screen sessions..."
screen -S ward-api      -X quit 2>/dev/null && echo "         Stopped ward-api"      || true
screen -S ward-frontend -X quit 2>/dev/null && echo "         Stopped ward-frontend" || true
sleep 1

echo "[SABARI] Starting Ward Monitor backend (port 7816)..."
screen -dmS ward-api bash -c "
    cd '$SABARI_DIR/backend'
    source '$SABARI_DIR/.venv/bin/activate'
    while true; do
        uvicorn main:app --host 0.0.0.0 --port 7816
        echo '[ward-api] crashed, restarting in 5s...'; sleep 5
    done
"

echo "[SABARI] Starting Ward Monitor frontend (port 4985)..."
screen -dmS ward-frontend bash -c "
    export NVM_DIR=\"\$HOME/.nvm\"
    [ -s \"\$NVM_DIR/nvm.sh\" ] && \. \"\$NVM_DIR/nvm.sh\"
    cd '$SABARI_DIR'
    npm install --silent
    while true; do
        VITE_PORT=4985 VITE_HOST=0.0.0.0 VITE_API_URL=http://localhost:7816 \
            npm run dev -- --host 0.0.0.0 --port 4985
        echo '[ward-frontend] crashed, restarting in 5s...'; sleep 5
    done
"

echo ""
echo "==================================================="
echo " ✅ All services started!"
echo ""
echo " Ashmit's App (main login) : http://72.60.102.196:4990/"
echo " Ashmit's API              : http://72.60.102.196:7015/docs"
echo " Ashmit's Data Server      : http://72.60.102.196:7016/docs"
echo ""
echo " Sabari's Ward Monitor     : http://72.60.102.196:4985/"
echo " Sabari's API              : http://72.60.102.196:7816/docs"
echo ""
echo " Login as ward/charge nurse from Ashmit's page and you"
echo " will be redirected instantly to Sabari's Ward Monitor."
echo ""
echo " Check sessions : screen -ls"
echo " Attach to logs : screen -r ward-api | screen -r ward-frontend"
echo "                  screen -r main     | screen -r frontend"
echo "==================================================="
