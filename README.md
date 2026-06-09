# Foqal CareOS — Ward Monitor (Early Warning System)

A clinical decision support tool for bedside and charge nurses in a cardiac ward, providing real-time NEWS2 early warning scores, escalation workflows, and drug-lab interaction alerts.

## Demo Credentials

| Role | Username | Password |
|---|---|---|
| Ward / Bedside Nurse | `rekha.devi` | `WardNurse@2026` |
| Charge Nurse | `leena.kurup` | `ChargeNurse@2026` |

## Tech Stack

- **Frontend**: Vanilla HTML + JavaScript, served by Vite
- **Backend**: Python FastAPI
- **Database**: SQLite (local demo) → Google Cloud SQL (production)

---

## Running Locally (Windows / Mac)

```bash
# 1. Start the backend
cd backend
pip install -r requirements.txt
python build_demo_db.py    # builds the SQLite database once
uvicorn main:app --reload  # runs on port 8000

# 2. In another terminal, start the frontend
cd ..   # back to sabari_project root
npm install
npm run dev                # runs on port 5174
```

Open `http://localhost:5174/`

---

## Deploying to the Linux Server (http://72.60.102.196)

The project runs on **port 5175** (frontend) and **port 8003** (backend API) on the shared server.

### One-time setup

```bash
# SSH into the server (ask Ashmit for the SSH details)
ssh ubuntu@72.60.102.196

# Clone the repo
git clone https://github.com/YOUR_GITHUB_USERNAME/sabari-ward-monitor ~/sabari_project
cd ~/sabari_project

# Run the deploy script (handles everything)
bash deploy.sh
```

### After that, your project is live at:
- **Frontend**: `http://72.60.102.196:5175/`
- **Backend API docs**: `http://72.60.102.196:8003/docs`

### To update after code changes:
```bash
# SSH into the server
cd ~/sabari_project
git pull
bash deploy.sh
```

### Useful server commands:
```bash
screen -ls                   # list all running sessions
screen -r ward-api           # attach to backend logs
screen -r ward-frontend      # attach to frontend logs
# Press Ctrl+A then D to detach without stopping
```

---

## Project Structure

```
sabari_project/
├── index.html          # Login page (Ashmit-style design, RBAC)
├── app.js              # Single-page app — all screens
├── styles.css          # Global styles
├── vite.config.js      # Vite config (env-variable driven)
├── deploy.sh           # Server deployment script
└── backend/
    ├── main.py             # FastAPI app — all endpoints
    ├── models.py           # SQLAlchemy ORM models
    ├── database.py         # DB connection (SQLite → Cloud SQL switchable)
    ├── build_demo_db.py    # Generates 16 realistic DCM demo patients
    ├── bigquery_pipeline.py # Real MIMIC-IV extraction (needs GCP credentials)
    ├── requirements.txt
    ├── engine/
    │   └── drug_lab.py     # Drug-Lab interaction rules engine
    └── rules/
        └── drug_lab_rules.yaml  # Clinical rules (T1/T2 tiers)
```

---

## What Gets Committed to GitHub

✅ Commit:
- `index.html`, `app.js`, `styles.css`, `vite.config.js`
- `backend/main.py`, `backend/models.py`, `backend/database.py`
- `backend/build_demo_db.py`, `backend/bigquery_pipeline.py`
- `backend/requirements.txt`
- `backend/engine/`, `backend/rules/`
- `deploy.sh`, `.gitignore`, `package.json`, `package-lock.json`

❌ Do NOT commit:
- `backend/data/ward_careos.db` (SQLite database — built fresh on server)
- `node_modules/` (installed fresh via `npm install`)
- `*.json` credentials files
- `__pycache__/`, `.venv/`
