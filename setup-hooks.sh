#!/bin/bash
# Run once on the server to install git hooks

HOOK=.git/hooks/post-merge

cat > $HOOK << 'EOF'
#!/bin/bash
cd ~/Hospital_Efficiency
source .venv/bin/activate
pip install -r requirements.txt -q

screen -S main -X quit 2>/dev/null
screen -dmS main bash -c "source ~/.venv/bin/activate 2>/dev/null; source ~/Hospital_Efficiency/.venv/bin/activate 2>/dev/null; cd ~/Hospital_Efficiency && uvicorn backend.app.main:app --host 0.0.0.0 --port 7015"

screen -S data -X quit 2>/dev/null
screen -dmS data bash -c "source ~/Hospital_Efficiency/.venv/bin/activate; cd ~/Hospital_Efficiency && uvicorn backend.app.data_server:app --host 0.0.0.0 --port 7016"

screen -S frontend -X quit 2>/dev/null
screen -dmS frontend bash -c "cd ~/Hospital_Efficiency/frontend && npm run dev -- --host 0.0.0.0"

echo "[deploy] All servers restarted after git pull"
EOF

chmod +x $HOOK
echo "Hook installed at $HOOK — servers will auto-restart on every git pull"
