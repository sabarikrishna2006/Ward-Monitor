# Ward Monitor Clinical Decision Support

A modern, real-time Early Warning Dashboard designed to monitor critical patients in a ward setting, featuring predictive Machine Learning insights and Clinical Decision Support (CDS) alerts.

## Project Structure

This project has been modernized and is split into two main components:
- `/ewd-frontend`: A React + Vite frontend built with TailwindCSS and Recharts for visualizing real-time vitals.
- `/ward-monitor-api`: A FastAPI Python backend that serves real clinical data from an SQLite database (derived from MIMIC-IV).

---

## 1. Running the Backend (FastAPI)

The backend provides the API endpoints for patient data, vitals history, and predictive ML risk scoring.

### Setup & Requirements
Ensure you have Python 3.9+ installed.

```bash
cd ward-monitor-api
python -m venv .venv
# Activate virtual environment
# On Windows:
.venv\Scripts\activate
# On Mac/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

*(Note: If a `requirements.txt` is not yet generated, you will need: `fastapi`, `uvicorn`, `pandas`, `sqlalchemy`)*

### Starting the Server
```bash
# From within the ward-monitor-api directory:
uvicorn main:app --reload --port 8000
```
The backend will run at `http://localhost:8000`. You can access the auto-generated API documentation at `http://localhost:8000/docs`.

---

## 2. Running the Frontend (React / Vite)

The frontend is a modern SPA (Single Page Application) that polls the backend for real-time updates.

### Setup & Requirements
Ensure you have Node.js (v16 or higher) installed.

```bash
cd ewd-frontend
npm install
```

### Starting the Dev Server
```bash
npm run dev
```
The frontend will typically run at `http://localhost:5173`. Open this URL in your browser to view the dashboard.

---

## Next Steps / Roadmap
- **Deployment:** Dockerize both components for deployment to cloud servers (e.g., AWS/GCP).
- **ML Integration:** Connect a trained XGBoost/RandomForest model in the FastAPI backend to generate real-time predictive risk scores instead of relying on basic heuristics.
- **Data Ingestion:** Create automated pipelines to sync the local database with Google BigQuery/GCS for real-time hospital streaming.
