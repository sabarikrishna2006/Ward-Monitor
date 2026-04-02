# Ward Monitor — Clinical Decision Support Dashboard

A clinical decision support tool for ward-based patient monitoring. Displays real-time vital signs, NEWS2 scoring, drug-lab interaction alerts, and sepsis/AKI flags.

## Features

- **12-bed ward overview** with patients ranked by acuity (red → amber → green)
- **NEWS2 scoring** (National Early Warning Score 2) with clinical response guidance
- **Sparkline trends** — 24-hour vital sign trends at a glance
- **Drug-lab interaction alerts** — catches dangerous combinations (e.g., high K+ on ACE inhibitor)
- **Sepsis/AKI flags** — highlights patients meeting deterioration criteria
- **Auto-refresh** — updates every 30 seconds
- **Dark theme** — designed for nurse station night shifts
- **Patient detail view** — full vitals history, labs, medications, alert timeline

## Quick Start

```bash
cd ward-monitor
pip install -r requirements.txt
python3 app.py
```

Open http://localhost:5001

The database is auto-seeded on first run with realistic mock patient data.

## Tech Stack

- **Backend:** Flask, SQLite
- **Frontend:** Jinja2, Bootstrap 5, vanilla JavaScript, Chart.js (detail view only)
- **Scoring:** NEWS2 calculator (engine/ews.py)
- **Alerts:** YAML-driven drug-lab rule engine (engine/drug_lab.py)

## Project Structure

```
ward-monitor/
├── app.py                    # Flask entry point
├── config.py                 # Settings
├── modules/
│   ├── dashboard.py          # Main ward routes + API
│   └── alerts.py             # Alert API endpoints
├── engine/
│   ├── ews.py                # NEWS2 score calculator
│   ├── drug_lab.py           # Drug-lab interaction rule engine
│   └── mock_replay.py        # Vitals time-series retrieval
├── templates/
│   ├── base.html             # Base layout (dark theme)
│   ├── ward.html             # Main ward dashboard
│   └── patient_detail.html   # Expanded patient view
├── static/
│   ├── css/style.css
│   └── js/
│       ├── dashboard.js      # Data fetching, DOM updates
│       └── sparkline.js      # Lightweight sparkline renderer
├── rules/
│   └── drug_lab_rules.yaml   # Drug-lab interaction rules
└── utils/
    ├── db.py                 # SQLite helpers
    └── seed.py               # Mock data seeder
```

## Mock Data Scenarios

| Bed | Patient | Scenario |
|-----|---------|----------|
| 3 | Sharma, R. | Sepsis deterioration — NEWS2 high, red flag |
| 7 | Patel, A. | AKI developing — rising creatinine, metformin alert |
| 9 | Menon, D. | Hyperkalemia — K+ 5.8, lisinopril interaction |
| 12 | Rao, B. | Sepsis criteria met, no antibiotics — clinical alert |
| Others | Various | Stable patients, green flags |
