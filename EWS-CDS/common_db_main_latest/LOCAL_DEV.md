# Local Development Guide — Foqal CareOS

This guide explains how to run all 5 services locally on your Windows machine for development and testing.

## 📋 Prerequisites

Before starting local services, ensure you have:

- **Python 3.8+** installed and in your PATH
  - Verify: `python --version`
  
- **Node.js 18+** installed globally
  - Verify: `node --version` and `npm --version`

- **Cloud SQL credentials** (if you need database access)
  - The `.env.secrets` file should exist in the repo root
  - Contact the team if this file is missing

## 🚀 Quick Start

### Step 1: Start All Services

From the repo root directory, open PowerShell and run:

```powershell
powershell -ExecutionPolicy Bypass -File start_local.ps1
```

This will:
1. Check Python and Node.js installations
2. Create Python virtual environments (if needed)
3. Install all dependencies
4. Open **5 separate terminal windows**, each running one service

### Step 2: Monitor Service Startup

Each terminal window will show startup messages. Wait 10-15 seconds for all services to initialize:

```
[MAIN API] Starting on port 7015...
[MAIN API] Docs available at http://localhost:7015/docs

[DATA SERVER] Starting on port 7016...
[DATA SERVER] Docs available at http://localhost:7016/docs

[FRONTEND] Starting on port 4990...
[FRONTEND] Available at http://localhost:4990

[WARD API] Starting on port 7816...
[WARD API] Docs available at http://localhost:7816/docs

[WARD FRONTEND] Starting on port 4985...
[WARD FRONTEND] Available at http://localhost:4985
```

### Step 3: Verify Services Are Running

From a new PowerShell window, run:

```powershell
powershell -ExecutionPolicy Bypass -File verify_services.ps1
```

Expected output:
```
✓ Main API (port 7015): RUNNING
✓ Data Server (port 7016): RUNNING
✓ Ashmit Frontend (port 4990): RUNNING
✓ Ward Monitor API (port 7816): RUNNING
✓ Ward Monitor Frontend (port 4985): RUNNING

✅ All services are healthy!
```

## 🌐 Access Your Services

| Service | Port | URL | Purpose |
|---------|------|-----|---------|
| **Ashmit Frontend** | 4990 | http://localhost:4990 | Main login page & dashboards |
| **Main API** | 7015 | http://localhost:7015/docs | RAG & discharge summary (Swagger docs) |
| **Data Server** | 7016 | http://localhost:7016/docs | Data fetch layer (Swagger docs) |
| **Ward Monitor** | 4985 | http://localhost:4985 | Ward dashboard |
| **Ward API** | 7816 | http://localhost:7816/docs | Ward backend (Swagger docs) |

## 🧪 Testing Workflow

### Test the Full Login Flow

1. Open http://localhost:4990 in your browser
2. Log in with credentials for **ward** or **charge nurse**
3. You should be redirected to Ward Monitor at http://localhost:4985
4. Verify the ward dashboard loads correctly

### Test API Endpoints

Each backend service exposes Swagger documentation:

- Main API: http://localhost:7015/docs → Try `/discharge-summary`, `/rag-search` endpoints
- Data Server: http://localhost:7016/docs → Try `/fetch-patient-data` endpoints
- Ward API: http://localhost:7816/docs → Try `/patients`, `/alerts` endpoints

### View Logs

Each terminal shows real-time logs for its service. Check for:
- Startup errors or port conflicts
- Request logs as you test endpoints
- Crash messages (services auto-restart after 5 seconds if they crash)

## 🛑 Stopping Services

### Option 1: Close All Terminal Windows
Simply close each of the 5 terminal windows.

### Option 2: Use Stop Script
From a new PowerShell window, run:

```powershell
powershell -ExecutionPolicy Bypass -File stop_local.ps1
```

This gracefully stops all Python and Node.js processes.

## 🔧 Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'backend'"
- **Cause**: Python venv not activated or dependencies not installed
- **Fix**: Delete `.venv` folders and re-run `start_local.ps1`

### Issue: "Port 7015 already in use"
- **Cause**: A service is already running on that port
- **Fix**: Run `stop_local.ps1` to kill all processes, then restart

### Issue: "npm not found"
- **Cause**: Node.js not in PATH
- **Fix**: Install Node.js from https://nodejs.org/ and restart PowerShell

### Issue: ".env.secrets not found" error
- **Cause**: Cloud SQL credentials file missing
- **Fix**: 
  - If you don't need database access, comment out `CLOUD_SQL_PASS` in the backend code
  - Otherwise, request `.env.secrets` from the team and place it in the repo root

### Issue: Frontend doesn't connect to backend
- **Cause**: CORS or API URL misconfiguration
- **Fix**: Check that `VITE_API_URL=http://localhost:7816` is set in the Ward Monitor terminal

## 📝 Development Workflow

### Making Backend Changes

1. Edit Python files in `backend/app/` or `sabari_project/backend/`
2. The service will auto-reload when you save (watch mode enabled)
3. Check the terminal for any errors

### Making Frontend Changes

1. Edit HTML/JS/CSS in `frontend/` or `sabari_project/`
2. The Vite dev server auto-refreshes your browser
3. No need to restart

### Database Changes

If you change the database schema:
1. Update `backend/app/models.py` or `sabari_project/backend/models.py`
2. The backend will connect with the new schema on restart
3. For migrations, follow the team's migration strategy

## 📊 Service Dependencies

```
Ashmit Frontend (4990)
  ↓
  ├─→ Main API (7015) — handles auth, discharge summaries
  └─→ Data Server (7016) — fetches patient data

Ward Monitor Frontend (4985)
  ↓
  └─→ Ward Monitor API (7816) — handles ward-specific logic
```

All services connect to **Cloud SQL** for persistent data (if `.env.secrets` is available).

## 💡 Tips

- **Check processes**: `Get-Process | Where-Object { $_.ProcessName -like "python" -or $_.ProcessName -like "node" }`
- **Kill a specific service**: `Stop-Process -Name python -Force` (kills all Python processes)
- **Monitor resource usage**: Open Task Manager (Ctrl+Shift+Esc) and watch powershell.exe processes
- **Use Chrome DevTools**: Press F12 in the frontend to debug frontend issues

## 🆘 Getting Help

If services won't start:

1. Check the terminal output for specific error messages
2. Run `verify_services.ps1` to see which services are failing
3. Check the `.env.secrets` file exists for backend services
4. Review logs in each terminal for detailed error traces

---

**Last Updated**: 2026-07-05  
**Created By**: Local Dev Launcher  
**For**: Foqal CareOS Integrated Hospital Project
