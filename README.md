# Foqal CareOS: Early Warning System (EWS) & Clinical AI Monitor

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-00a393)
![Vite](https://img.shields.io/badge/Vite-5.0-646CFF)
![Google Cloud SQL](https://img.shields.io/badge/GCP-Cloud_SQL-4285F4)

**Foqal CareOS** is a production-grade, highly concurrent clinical backend system designed to monitor real-time patient vitals, predict clinical deterioration, and automate escalation workflows across intensive care units (CCU) and general wards. 

This repository contains the integrated ecosystem combining the **Clinical Discharge AI** and the **EWS Ward Monitor**, engineered for massive scalability using Google Cloud SQL (PostgreSQL), FastAPI, and BigQuery data ingestion (MIMIC-IV dataset).

---

## 🏗️ Architecture & Tech Stack

*   **Backend Framework:** FastAPI (Python) for asynchronous, high-throughput API endpoints.
*   **Database:** Google Cloud SQL (PostgreSQL). Schema consists of 48 normalized tables with composite indexing to handle high-frequency vitals telemetry.
*   **Data Ingestion:** Automated BigQuery pipelines extracting and transforming raw MIMIC-IV EHR data.
*   **Frontend:** Vanilla JS / HTML5 powered by Vite, utilizing dynamic DOM rendering for real-time dashboard updates without framework bloat.
*   **AI Integration:** MedCPT vector embeddings and Google Gemini AI for automated clinical NLP and Drug-Lab interaction analysis.
*   **Auth & Security:** 5-Tier Role-Based Access Control (RBAC) with bcrypt password hashing.

---

## 🚀 Getting Started

### Prerequisites
*   Node.js (v20+)
*   Python (3.9+)
*   Google Cloud Service Account credentials (`foqal-healthcare-project-google.json`)
*   Access to the Foqal Cloud SQL Instance.

### Installation & Deployment

We provide an automated deployment script that spins up both the Main Hospital API and the EWS Ward Monitor simultaneously using `screen` sessions.

```bash
# Clone the repository
git clone https://github.com/sabarikrishna2006/Ward-Monitor.git
cd Ward-Monitor/common_db_main_latest

# Execute the deployment script
bash deploy.sh
```

**Services Started by `deploy.sh`:**
*   **Main Hospital App:** `http://localhost:4990/`
*   **Main Hospital API (Swagger):** `http://localhost:7015/docs`
*   **EWS Ward Monitor App:** `http://localhost:4985/`
*   **EWS API (Swagger):** `http://localhost:7816/docs`

*(Note: The deployment script maps these to specific IPs in production environments. Please check the terminal output for exact URLs upon running).*

---

## 👥 Demo Users & Role-Based Access Control

The system comes pre-seeded with clinical demo accounts demonstrating the 5-tier RBAC system. You can log in via the Main Hospital App, and relevant roles will be seamlessly redirected to the EWS Ward Monitor.

| Role | Email / Username | Password | Access Level |
| :--- | :--- | :--- | :--- |
| **Ward Nurse** | `rekha.devi@foqal.in` | `WardNurse@2026` | Monitor CCU vitals, escalate deteriorating patients. |
| **Charge Nurse** | `leena.kurup@foqal.in` | `ChargeNurse@2026` | Review escalations, manage CCU step-down transfers, override Drug-Lab flags. |
| **GW Nurse** | `prathima.m@foqal.in` | `GWNurse@2026` | Acknowledge step-down transfers in the General Ward. |
| **Resident Doctor**| `dr.anand@foqal.in` | `Resident@2026` | Full clinical oversight and discharge summary generation. |

> **Security Note:** Default plain-text passwords are automatically upgraded to `bcrypt` hashes upon first login via the `015_unified_staff_auth.sql` migration trigger.

---

## 🧪 Synthetic Data Seeding

To properly demonstrate the Drug-Lab interaction engine and NEWS2 escalation trajectories, you must seed the synthetic CCU patients.

Ensure the virtual environment is activated, then run:
```bash
# Clears existing synthetic patients (leaves real MIMIC data intact)
python clear_all_patients.py

# Seeds the 6 Demo CCU patients (IDs 91001-91006)
python seed_demo_ccu.py
```
This generates 12-hour continuous vital trajectories, labs, and medications designed to trigger specific clinical alerts (e.g., Amiodarone + Hypokalemia).

---

## 📁 Repository Structure

```text
common_db_main_latest/
├── backend/                  # Hospital Efficiency Core API (FastAPI)
├── frontend/                 # Main Login & Hospital Dashboards
├── sabari_project/           # EWS Ward Monitor Sub-Project
│   ├── backend/              # EWS Specific API endpoints & MIMIC Sync
│   ├── app.js                # EWS Core Frontend Logic
│   └── ...
├── notebooks/                # ML Data Exploration & Model Training Scripts
├── deploy.sh                 # Unified Deployment Script
├── seed_demo_ccu.py          # Synthetic Data Generator
├── clear_all_patients.py     # Database cleanup utility
└── foqal-healthcare-...json  # GCP Service Account (Required for DB/BigQuery)
```

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
