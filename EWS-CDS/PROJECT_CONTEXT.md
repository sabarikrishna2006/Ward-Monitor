# Foqal CareOS — Complete Project Context

> Hand this file to any AI assistant to give full project context before asking it to work on code.

---

## 1. What This Project Is

**Foqal CareOS** is a clinical decision support system for Indian hospital cardiology wards (DCM / HFrEF focus). It is built by two interns working together:

| Intern | System | Purpose |
|---|---|---|
| **Ashmit** | Hospital Efficiency / Discharge AI | Discharge summary generation using Gemini 2.5 Flash + MIMIC-IV data. Manages billing admission flow, doctor queue, and NABH-compliant discharge summaries. |
| **Sabari** | Ward Monitor / EWS | Early Warning Score (NEWS2) dashboard, nurse workflows, escalation chain, drug-lab interaction checks, CCU↔GW step-down. |

These are **one integrated product**, not two separate apps. They share a single Cloud SQL database (`postgres` schema) and a single deployment script (`deploy.sh`).

---

## 2. Five Running Services

| Service | Owner | Port | What it does |
|---|---|---|---|
| **Main API** | Ashmit | 4002 | Discharge summaries, RAG, Gemini, MIMIC data fetch |
| **Data Server** | Ashmit | 4003 | Auxiliary data endpoints for frontend |
| **Unified Login Frontend** | Ashmit | 5180 | React SPA — login, billing, doctor queue, discharge review |
| **Ward Monitor API** | Sabari | 8006 | FastAPI — NEWS2, escalation, drug-lab, step-down workflows |
| **Ward Monitor Frontend** | Sabari | 5175 | Vanilla JS SPA — ward dashboard, nurse screens |

**Server IP:** `72.60.102.196`
**Deploy command (on server):** `bash deploy.sh` from inside the repo root.

---

## 3. Repository Layout

```
common_db_main_latest/          ← THE LIVE REPO (git tracked, deployed to server)
│
├── deploy.sh                   ← Start all 5 services
├── seed_demo_ccu.py            ← Non-destructive demo seeder (6 CCU patients, IDs 91001-91006)
├── build_erd.js                ← ERD generator
├── apply_026.py                ← Migration script
│
├── backend/app/                ← Ashmit's backend (port 4002 + 4003)
│   ├── main.py                 ← Main API: discharge summary, RAG, Gemini, MIMIC pipeline
│   ├── data_server.py          ← Auxiliary data server (port 4003)
│   ├── cloud_sql_db.py         ← Cloud SQL connection (Ashmit's copy)
│   ├── cloud_sql_app_db.py     ← App DB operations (encounters, summaries, hospitals)
│   ├── bigquery_mimic_loader.py← BigQuery → Cloud SQL ETL (prefetch-all)
│   ├── bigquery_pipeline.py    ← Alternate/older BQ pipeline
│   ├── chunker.py              ← Text chunking for RAG
│   ├── embedder.py             ← MedCPT embeddings for RAG
│   ├── qdrant_store.py         ← Qdrant vector store client
│   ├── loader.py               ← Document loading utilities
│   ├── cims_drug_map.py        ← Indian CIMS drug name normalization
│   ├── synthetic_demo.py       ← Synthetic demo patients for discharge AI (IDs 9900001-9900005)
│   └── models.py               ← Ashmit's SQLAlchemy models (ap_* tables)
│
├── frontend/                   ← Ashmit's React frontend (port 5180)
│   ├── index.html              ← Entry point / unified login
│   ├── billing.html            ← HIS admission screen (bill guy admits patients)
│   ├── dashboard.html          ← Resident doctor dashboard (discharge review)
│   ├── doctor-queue.html       ← Doctor pending queue
│   ├── ward-admin.html         ← Ward admin panel
│   ├── upload.html             ← File upload for clinical data
│   ├── config.js               ← Frontend configuration (API URLs)
│   ├── state.js                ← Global state management
│   ├── shell.js                ← App shell / routing
│   ├── api-client.js           ← API call wrappers
│   └── screens/                ← Screen-specific JS modules
│       ├── doctor-dashboard.js ← Resident discharge summary review
│       ├── doctor-queue.js     ← Doctor pending queue logic
│       ├── review-v2.js        ← Discharge summary review workflow
│       ├── amendment.js        ← Summary amendment flow
│       ├── signoff.js          ← Discharge sign-off
│       ├── signed.js           ← Signed summary view
│       ├── dl.js               ← Drug-lab screen
│       └── rejection-flow.js   ← Rejection workflow
│
└── sabari_project/             ← Sabari's Ward Monitor (port 8006 + 5175)
    ├── app.js                  ← Entire Ward Monitor SPA (vanilla JS, ~1600 lines)
    ├── index.html              ← Entry point
    ├── styles.css              ← All Ward Monitor CSS
    ├── vite.config.js          ← Vite config (dev proxy to port 8006)
    └── backend/
        ├── main.py             ← FastAPI ward API (port 8006, ~1500 lines)
        ├── models.py           ← SQLAlchemy models — SOURCE OF TRUTH for column names
        ├── database.py         ← Cloud SQL connector (Google Cloud SQL Python Connector)
        ├── mimic_sync.py       ← MIMIC-IV → EWS table bridge (see section 8)
        ├── build_demo_db.py    ← DESTRUCTIVE seeder — 16 DCM demo patients (IDs 10001-10016)
        │                          TRUNCATES all EWS tables before seeding. Use with caution.
        ├── seed_demo_ccu.py    ← (at root) Non-destructive 6-patient seeder
        ├── engine/
        │   └── drug_lab.py     ← YAML-driven drug-lab rule engine
        └── rules/
            ├── drug_lab_rules.yaml     ← 13 NABH DL2 drug-lab interaction rules
            └── news2_thresholds.yaml   ← NEWS2 scoring bands (AVPU, SpO2, HR, RR, BP, Temp)
```

---

## 4. Shared Cloud SQL Database

**Instance:** `healthcare-project-496207:asia-south1:healthcare-project-496207-instance` (PostgreSQL 18, db-f1-micro — migrated 2026-07-02 from the deleted free-trial instance `foqal-healthcare-cloud-sql-db`; full dump backup at `gs://foqal-db-migration-496207/postgres-full.sql.gz`)
**Database:** `postgres`
**Connection:** Google Cloud SQL Python Connector (pg8000 driver), credentials from `healthcare-project-db-creds.json`

### Schema ownership

| Prefix | Owner | Purpose |
|---|---|---|
| `ap_*` | Ashmit (READ-ONLY for Sabari) | MIMIC-IV data mirrored from BigQuery |
| `ews_*` | Sabari | Ward Monitor operational tables |
| `active_patients` | Shared | Admission master — hub linking both systems |
| `app_encounters` | Ashmit | Discharge summary workflow state |
| `hospital_core.*` | Ashmit | Schema — hospitals, wards, patients, admissions |

### `ap_*` tables (MIMIC-IV data, read-only for Sabari)

| Table | Contents |
|---|---|
| `ap_admissions` | Patient demographics + admission/discharge times |
| `ap_diagnoses` | ICD-10/9 diagnoses (primary at seq_num=1) |
| `ap_chartevents` | ICU vital signs (itemid-based, from MIMIC MetaVision) |
| `ap_labevents` | Lab results (K+, creatinine, BNP, troponin, etc.) |
| `ap_prescriptions` | Medication orders (drug, dose, route, frequency) |
| `ap_outputevents` | Urine output volumes |
| `ap_icustays` | ICU stay records (stay_id, LOS, first/last careunit) |
| `ap_transfers` | Ward transfer records |
| `ap_microbiologyevents` | Blood culture / microbiology results |
| `ap_procedures` | Procedure records |
| `ap_noteevents` | Clinical notes (discharge notes, radiology, etc.) |

### `ews_*` tables (Sabari's ward operational data)

| Table | Contents |
|---|---|
| `ews_vitals_timeseries` | Nurse-charted vitals: HR, RR, SpO2, SBP, DBP, Temp, AVPU, O2, urine |
| `ews_lab_events` | Lab results: K+, creatinine, INR, lactate, eGFR, BNP, troponin, Na, Hgb |
| `ews_medications` | Active medication list for ward dashboard |
| `ews_escalations` | NEWS2 escalation records — who escalated, to what level, when resolved |
| `ews_ccu_transfers` | CCU→GW step-down recommendations and decisions |
| `ews_drug_lab_actions` | NABH DL2 drug-lab safety actions — what was held/adjusted and why |

---

## 5. SQLAlchemy Models — Column Name Source of Truth

**ALWAYS check `sabari_project/backend/models.py` before writing any DB code.** SQLAlchemy silently ignores wrong column names.

Key column name mapping (old SQLite era vs current Cloud SQL):

| Wrong (old) | Correct (current) |
|---|---|
| `name` | `patient_name` |
| `age` | `anchor_age` |
| `sex` | `gender` |
| `admitted` (String) | `admit_time` (DateTime) |
| `complaint` | `ews_complaint` |
| `subject_id` (PK) | `hadm_id` (PK on `active_patients`) |
| `chart_hour` (String) | `chart_time` (DateTime) |

Primary key of `active_patients` is `hadm_id` (Integer) — **there is no `id` field on Patient model**.

---

## 6. Patient Lifecycle — End-to-End Flow

```
Bill guy (billing.html)
    │  POST /api/patients  (Ashmit port 4002)
    │  Creates active_patients row + app_encounters row
    ▼
prefetch-all  (Ashmit port 4002)
    │  BigQuery → Cloud SQL: fills ap_chartevents, ap_labevents,
    │  ap_prescriptions, ap_diagnoses, ap_noteevents, ap_procedures...
    ▼
sync-vitals  (Sabari port 8006)
    │  POST /api/patients/{hadm_id}/sync-vitals
    │  mimic_sync.py reads ap_* → writes ews_vitals_timeseries,
    │  ews_lab_events, ews_medications
    ▼
Ward Monitor dashboard (port 5175)
    │  Nurses see patient with NEWS2 score, vitals, labs, meds
    │  Nurse actions generate: ews_escalations, ews_drug_lab_actions,
    │  ews_ccu_transfers
    ▼
GW Nurse clicks "Initiate Discharge"  (port 5175)
    │  POST /api/patients/{hadm_id}/initiate-discharge (Sabari port 8006)
    │  Sets active_patients.status = 'discharge_initiated'
    │  Sets app_encounters.status = 'Ready for Review'  (via Ashmit's DB)
    │  Patient stays visible in ward dashboard with "Discharge Pending" badge
    ▼
Resident Doctor (dashboard.html, port 5180)
    │  Sees patient in queue because app_encounters.status = 'Ready for Review'
    │  Clicks "Generate Discharge Summary"
    ▼
generate_summary  (Ashmit port 4002)
    │  1. Reads ALL ap_* tables for this hadm_id from Cloud SQL/BigQuery
    │  2. Calls _ews_overlay_lines(hadm_id) — reads ews_* tables for ward activity
    │  3. build_clinical_context() — combines MIMIC data + EWS overlay
    │  4. Gemini 2.5 Flash generates NABH-compliant discharge summary
    │  5. Saves to summaries table, updates encounter status
    ▼
Doctor reviews → signs off → discharge complete
```

**Two separate status fields** control visibility:
- `active_patients.status` → controls ward dashboard (nurses see patient)
- `app_encounters.status` → controls doctor queue (resident sees patient)

These are **independent**. Changing `active_patients.status` to `'discharge_initiated'` does NOT affect the doctor queue. Resident sees patient because `app_encounters.status = 'Ready for Review'`.

---

## 7. Role-Based Navigation in Ward Monitor (app.js)

The Ward Monitor SPA uses a single `APP.user.role` to decide which screen to show at login.

| Role | Login goes to | What they do |
|---|---|---|
| `gw_nurse` | `n1` — GW ward dashboard | Manage General Ward patients, initiate discharge |
| `nurse` | `n1` — CCU dashboard | Manage CCU patients, submit step-down transfers |
| `charge_nurse` | `n5` — Escalation queue | Review active escalations, approve/reject step-downs |
| `doctor` / `resident` | `n5` — Doctor acknowledge | Acknowledge escalations from nurses |
| `admin` | `n7` — Admin panel | Ward administration |

Screen codes: `n1`=ward list, `n1b`=patient detail, `n2`=vitals entry, `n3`=escalation form, `n4`=drug-lab, `n5`=charge nurse queue, `n6`=handoff, `n6b`=handoff complete, `n7`=admin, `n_discharge`=discharge status, `n_demo_replay`=patient arc.

---

## 8. MIMIC-IV Sync Engine — `mimic_sync.py` (Critical: Read Carefully)

### What it reads

| `ap_*` table | What it extracts |
|---|---|
| `ap_chartevents` | 12 vital sign itemids: HR (220045), SBP (220179/220050), DBP (220180/220051), SpO2 (220277), RR (220210), Temp °C/°F (223762/223761), Weight (224639/226512), GCS (226755), O2 flow (223834) |
| `ap_labevents` | 10 lab itemids: K+ (50971), Creatinine (50912), Lactate (50813), INR (51237), ALT (50861), BNP (50963/51921), Troponin (51003), Na (50983), Hgb (51222) |
| `ap_prescriptions` | All MAIN-type drugs (deduped by drug name, latest dose) |
| `ap_outputevents` | 7 urine output itemids → aggregated per 4-hour bucket |

### What it writes

| `ews_*` table | How |
|---|---|
| `ews_vitals_timeseries` | Vitals bucketed into 4-hour windows, re-stamped to "now - 30 min" |
| `ews_lab_events` | One row per calendar day, eGFR computed via CKD-EPI 2021 |
| `ews_medications` | Clears existing meds, inserts deduplicated drug list |
| `active_patients` | Updates `nyha_class` (BNP→EF→NEWS2 fallback) and `bnp_baseline` |

### CRITICAL — What mimic_sync does NOT bring

**`ap_icustays` is NOT read by mimic_sync.** ICU stay timestamps, LOS, care unit transfers, first/last ICU careunit — **none of this flows into ews_* tables.**

**`ap_transfers` is NOT read by mimic_sync.** Ward-to-ward transfer history from MIMIC is not synced.

**Worsening events / deterioration timestamps from MIMIC history are NOT synced.** The EWS system only tracks deterioration that happens live (nurses chart vitals → NEWS2 calculated → nurse submits escalation → stored in `ews_escalations`). The patient arc ("patient arc replay") uses vitals trajectory from `ews_vitals_timeseries`, not MIMIC ICU event logs.

### The non-ICU patient problem

`ap_chartevents` in MIMIC only contains data from ICU stays (MetaVision bedside monitors). A DCM patient admitted to a general medical ward in MIMIC will have zero chartevents rows.

**Result:** `_sync_vitals()` finds 0 rows → triggers fallback → seeds 12 synthetic stable vitals (HR 62-78, RR 13-17, SpO2 96-99%) using `random.seed(hadm_id)` for reproducibility. **This is why all billing-admitted patients appear stable on the ward dashboard.**

### Vital count for ICU patients

For patients with real ICU stays: `ap_chartevents` is limited by Ashmit's prefetch ETL to ~50 rows total across all itemids. After bucketing into 4-hour windows, this produces roughly **3–12 unique time points** in `ews_vitals_timeseries`. Not a 24-hour detailed picture.

---

## 9. NEWS2 Scoring System

Computed in `sabari_project/backend/main.py:calculate_news2()` using thresholds from `news2_thresholds.yaml`.

**Inputs:** HR, RR, SpO2, SBP, Temperature (°C), consciousness (A/V/P/U), O2 delivery (Air/Oxygen), hypercapnic failure flag.

**Score interpretation:**
- ≥ 7 → CRITICAL (red) — escalate to doctor
- 5–6 → WARNING (amber) — increased monitoring
- < 5 → STABLE (green)

NEWS2 is recalculated on every vitals entry. The drug-lab rule engine (`engine/drug_lab.py`) runs separately on meds + labs — it doesn't use NEWS2.

---

## 10. Drug-Lab Rule Engine

**File:** `sabari_project/backend/engine/drug_lab.py`
**Rules:** `sabari_project/backend/rules/drug_lab_rules.yaml` (13 rules, 153 lines)

Rules are sourced from: CSI (Cardiological Society of India), CDSCO, RSSDI, ICMR, ESC, FDA.

Each rule has:
- `trigger` — a lab name + numeric condition (e.g., `potassium > 5.5`)
- `medications` — list of drug class names from `DRUG_CLASS_MAP`
- `severity` — `CRITICAL` or `WARNING`
- `message`, `action`, `guideline`

The engine fires when: **lab condition is true AND patient has a matching drug active.**

| Rule | Lab | Condition | Drug class | Severity |
|---|---|---|---|---|
| Hyperkalemia + ACE inhibitor | potassium | > 5.5 | ace_inhibitors, k_sparing_diuretics | CRITICAL |
| Lactic acidosis + metformin | eGFR | < 30 | metformin | CRITICAL |
| AKI + NSAID | creatinine | > 1.5 | nsaids, ace_inhibitors | WARNING |
| Bleeding + anticoagulant | INR | > 3.5 | anticoagulants | CRITICAL |
| Lactate elevation (sepsis) | lactate | > 2.0 | (none — fires always) | WARNING |
| Digoxin toxicity + hypokalemia | potassium | < 3.5 | digoxin | CRITICAL |
| Amiodarone + anticoagulant | INR | > 2.5 | anticoagulants | WARNING |
| ... | ... | ... | ... | ... |

The engine runs on every vitals POST (`POST /api/vitals`). Nurses see alerts on the drug-lab tab (screen `n4`) and record actions in `ews_drug_lab_actions`.

**Pre-seeded DL flags** in demo patients (91001-91006):
- Lakshmi Menon (91002): K+ 5.7 + Ramipril → CRITICAL
- Govind Rao (91003): Creatinine 2.1 + Ibuprofen → WARNING

---

## 11. Discharge Summary — What the AI Gets

`generate_summary()` in `backend/app/main.py` (port 4002) assembles clinical context from two sources:

### Source 1 — MIMIC ground truth (`ap_*` tables)
Read directly from Cloud SQL (originally from BigQuery):
- Patient demographics, admit/discharge times
- All ICD diagnoses (primary + secondary)
- Full medication list from `ap_prescriptions`
- Lab trends from `ap_labevents` (K+, Cr, BNP, Hgb, etc.)
- Vital sign extremes from `ap_chartevents`
- Procedure records from `ap_procedures`
- ICU LOS from `ap_icustays`
- Clinical notes from `ap_noteevents` (if available)
- Microbiology from `ap_microbiologyevents` (if available)

### Source 2 — EWS ward activity overlay (`_ews_overlay_lines()`)
Read from `ews_*` tables via Sabari's Cloud SQL connection:
- Total nurse-charted vital sets + date range + extremes (from `ews_vitals_timeseries`)
- All NEWS2 escalations with timestamps, observations, interventions, resolution notes (from `ews_escalations`)
- All drug-lab safety actions with rule name, action taken, cosigner (from `ews_drug_lab_actions`)
- CCU→GW step-down events with rationale and outcome (from `ews_ccu_transfers`)

This overlay is clearly labelled `[WARD-GENERATED — EWS]` in the context so Gemini knows the provenance.

**What the discharge summary does NOT get:**
- ICU transfer timestamps or worsening event timelines from MIMIC (not synced to EWS)
- Escalations / DL flags for patients who were admitted but never had nurse interactions

---

## 12. Demo Patient Strategy — Two Separate Populations

| Population | ID range | Seeder | Purpose | Discharge summary? |
|---|---|---|---|---|
| **MIMIC billing patients** | Real MIMIC hadm_ids | Bill guy admission screen | Discharge summary generation demo | ✅ Yes — real MIMIC data |
| **Demo CCU patients** | 91001–91006 | `seed_demo_ccu.py` | NEWS2 / escalation / DL flag demo | ❌ No — synthetic vitals only |
| **Old demo patients** | 10001–10016 | `build_demo_db.py` (DESTRUCTIVE) | Same as above | ❌ No |
| **Synthetic demo** | 9900001–9900005 | `synthetic_demo.py` | Ashmit's discharge AI demo patients | ✅ Yes — pre-built cases |

**Never run `build_demo_db.py` when real patients exist** — it truncates all EWS tables.

**`seed_demo_ccu.py`** is idempotent (check-before-insert) and coexists with real admitted patients safely.

---

## 13. Patient Arc Replay — `list_dcm_patients()` Flow

The arc replay picker (`n_demo_replay` screen) calls `GET /api/mimic/dcm-patients` → `list_dcm_patients()` in `mimic_sync.py`.

**Priority logic:**
1. Query `ap_admissions JOIN ap_diagnoses` for ICD codes `I42%` (DCM family) or `425%` (ICD-9 equivalent). If results → return them.
2. **Fallback** (added recently): If no MIMIC DCM admits exist, query `active_patients WHERE EXISTS(ews_vitals_timeseries)`. Returns demo patients (91001-91006 or 10001-10016) so the arc is always functional.

The arc replay itself (`GET /api/demo/replay/{hadm_id}`) reads `ews_vitals_timeseries` ordered by time to produce the frame-by-frame trajectory.

**Current situation:** The fallback code is written but not yet deployed to the server. The server is running old code that only queries `ap_admissions`. The fix needs a git push + server restart.

---

## 14. Active Safety Rules for Database Operations

```
❌ NEVER:  Base.metadata.drop_all()  — wipes Ashmit's tables
❌ NEVER:  DROP TABLE  — same
❌ NEVER:  git push  — without explicit user approval
❌ NEVER:  bash deploy.sh  — without user confirming server pull is done

✅ ONLY truncate these EWS-owned tables:
   ews_vitals_timeseries, ews_lab_events, ews_medications,
   ews_escalations, ews_ccu_transfers, ews_drug_lab_actions, active_patients

✅ Always use:  CREATE TABLE IF NOT EXISTS
✅ Always use:  ADD COLUMN IF NOT EXISTS
✅ Test locally first, wait for user approval before pushing
```

---

## 15. Pending Deployment (as of this writing)

These local code changes need `git push` + server `git pull && bash deploy.sh` before they are live:

| File | Change | Effect when deployed |
|---|---|---|
| `sabari_project/backend/mimic_sync.py` | `list_dcm_patients` fallback to `active_patients` | Arc picker shows demo patients when no MIMIC DCM admits |
| `sabari_project/backend/main.py` | `initiate_discharge` sets `'discharge_initiated'` instead of `'data_ready'` | Discharge badge shows on ward dashboard |
| `sabari_project/app.js` | Full toast system, discharge badge, discharge banner | All notifications are hospital-grade toasts, no browser alerts |
| `sabari_project/styles.css` | Toast CSS, discharge badge CSS | Visual styles for above |
| `sabari_project/backend/build_demo_db.py` | Escalation + DL flag seeding added | 16-patient set has pre-seeded escalations and DL flags |
| `seed_demo_ccu.py` | Fixed `id` field bug, added escalation + DL seeding | 6-patient CCU seeder works correctly with escalations |

**Data already deployed to Cloud SQL (done via local run connecting to Cloud SQL):**
- 6 demo patients 91001-91006 are live in `active_patients`, `ews_vitals_timeseries`, `hospital_core.admissions`

---

## 16. Typical Q&A for an AI Receiving This Context

**Q: Where is the live code?**
All live code is in `common_db_main_latest/`. The root `sabari_project/` folder (if it exists outside `common_db_main_latest/`) is an old dev scratch copy — never edit it.

**Q: Which `main.py` is Sabari's?**
`common_db_main_latest/sabari_project/backend/main.py` (port 8006).

**Q: Which `main.py` is Ashmit's?**
`common_db_main_latest/backend/app/main.py` (port 4002).

**Q: Does mimic_sync bring ICU transfer timestamps or worsening event history?**
**No.** `mimic_sync.py` does not read `ap_icustays` or `ap_transfers`. It only reads chartevents (vitals), labevents (labs), prescriptions (meds), and outputevents (urine). ICU stay LOS is read by Ashmit's discharge engine directly from `ap_icustays` for the summary. Ward-level deterioration events are only recorded live through nurse escalation actions (`ews_escalations`).

**Q: Why do all billing-admitted patients show as Stable?**
MIMIC chartevents only exist for ICU patients. Most DCM/general ward MIMIC patients never had an ICU stay → zero chartevents → `mimic_sync.py` seeds 12 synthetic stable vitals (deterministic, seeded by hadm_id). For critical patient demos, use `seed_demo_ccu.py` patients (91001-91006).

**Q: How does the discharge summary know about ward events?**
`_ews_overlay_lines(hadm_id)` in `backend/app/main.py:3062` queries the 4 EWS tables and appends them to the clinical context as a `[WARD-GENERATED — EWS]` section before the Gemini call.

**Q: What triggers the drug-lab engine?**
Every `POST /api/vitals` call. The engine reads the patient's current meds from `ews_medications` and latest labs from `ews_lab_events`, runs them through `check_patient_against_rules()`, and returns alerts to the frontend. Nurses then record actions in `ews_drug_lab_actions`.
