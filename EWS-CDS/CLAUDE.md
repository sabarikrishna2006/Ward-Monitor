# Foqal CareOS — Project Instructions for Claude

## 1. This is an Ecosystem, Not Two Separate Projects

Ashmit's Hospital Efficiency system and Sabari's Ward Monitor are **one integrated product**. They share a single Cloud SQL database, a unified login flow, and are deployed together by a single script. Never treat them as independent.

Both must be running simultaneously for anything to work:

| Service | Who | Port |
|---------|-----|------|
| Main API (discharge summaries, RAG) | Ashmit | 4002 |
| Data server | Ashmit | 4003 |
| Unified login frontend | Ashmit | 5180 |
| Ward Monitor API | Sabari | 8006 |
| Ward Monitor frontend | Sabari | 5175 |

Server IP: `72.60.102.196`
Deploy command (on server): `bash deploy.sh` from inside `ashmit project/`

---

## 2. Always Edit the Correct Sabari Project Folder

There are **two copies** of `sabari_project/` in the repo:

```
EWS-CDS/
├── sabari_project/          ← ❌ WRONG — standalone dev workspace, NOT used by deploy.sh
└── ashmit project/
    ├── deploy.sh            ← the real deploy script
    └── sabari_project/      ← ✅ CORRECT — this is what runs on the server
```

**Always make code changes in `ashmit project/sabari_project/`.** The root-level `sabari_project/` is a development scratch copy. Changes there never reach the server.

---

## 3. Mandatory Testing Workflow — Never Skip Steps

```
Edit code  →  Test locally  →  User approves  →  Push to GitHub  →  Pull on server  →  bash deploy.sh
```

1. **Make changes** in `ashmit project/sabari_project/` (and Ashmit's code if needed).
2. **Test locally first** — use the `local-dev-launcher` agent or run services manually. Do not claim something works without running it.
3. **Wait for explicit user approval** before suggesting a push.
4. **Never run `git push`** without the user saying so.
5. **Never run `bash deploy.sh`** remotely without the user confirming the server pull is done.

---

## 4. Shared Cloud SQL Database — Handle with Care

Both projects share **one Cloud SQL instance**:
- Instance: `healthcare-project-496207:asia-south1:healthcare-project-496207-instance` (migrated 2026-07-02; the old `foqal-healthcare-cloud-sql-db` free-trial instance is deleted)
- Database: `postgres`
- Ashmit owns tables prefixed with `ap_*` (read-only for Sabari)
- Sabari owns tables prefixed with `ews_*` plus `active_patients`

**Rules:**
- Never run `Base.metadata.drop_all()` or `DROP TABLE` — it will wipe Ashmit's tables.
- Only TRUNCATE EWS-owned tables: `ews_vitals_timeseries`, `ews_lab_events`, `ews_medications`, `ews_escalations`, `ews_ccu_transfers`, `ews_drug_lab_actions`, `active_patients`.
- Use `CREATE TABLE IF NOT EXISTS` and `ADD COLUMN IF NOT EXISTS` in all migrations.
- Before running any migration, check it does not contain semicolons inside `--` comments (naive Python splitters will break on them).

---

## 5. Backend Code Rules (Lessons Learned — Do Not Repeat)

### Column Naming — Always Verify Before Writing DB Code
The SQLAlchemy models in `models.py` are the source of truth. Before writing any seed script, migration, or API code, cross-check the exact column names:

| Old (SQLite era, WRONG) | Current (Cloud SQL, CORRECT) |
|-------------------------|------------------------------|
| `name` | `patient_name` |
| `age` | `anchor_age` |
| `sex` | `gender` |
| `admitted` (String) | `admit_time` (DateTime) |
| `complaint` | `ews_complaint` |
| `subject_id` (PK) | `hadm_id` (PK) |
| `chart_hour` (String) | `chart_time` (DateTime) |

SQLAlchemy silently ignores unknown keyword arguments on model constructors — wrong column names produce NULLs with no error.

### No N+1 Queries
Never query inside a patient loop. Always bulk-fetch with `.in_()` before the loop:
```python
# WRONG — 3 queries per patient
for p in patients:
    vitals = db.query(VitalTimeSeries).filter(VitalTimeSeries.hadm_id == p.hadm_id).all()
    labs   = db.query(LabEvent).filter(LabEvent.hadm_id == p.hadm_id).all()
    meds   = db.query(Medication).filter(Medication.hadm_id == p.hadm_id).all()

# CORRECT — 3 queries total
ids = [p.hadm_id for p in patients]
vitals_map = group_by_hadm_id(db.query(VitalTimeSeries).filter(VitalTimeSeries.hadm_id.in_(ids)).all())
labs_map   = group_by_hadm_id(db.query(LabEvent).filter(LabEvent.hadm_id.in_(ids)).all())
meds_map   = group_by_hadm_id(db.query(Medication).filter(Medication.hadm_id.in_(ids)).all())
```
Cloud SQL is in `asia-south1` (Mumbai) since the 2026-07-02 migration — much lower latency from India, but bulk-fetching before loops still applies.

### Cache YAML/Config Files at Module Level
```python
# WRONG — re-reads file on every function call
def get_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)

# CORRECT — load once, reuse
_CACHE = None
def get_config():
    global _CACHE
    if _CACHE is None:
        with open("config.yaml") as f:
            _CACHE = yaml.safe_load(f)
    return _CACHE
```

### Patient Detail Must Not Load All Patients
`GET /api/patients/{id}` must pass `hadm_id` as a filter to `get_ward_data`, not call `get_ward_data(ward="All")` and loop through all patients.

---

## 6. Project Structure Quick Reference

```
ashmit project/
├── deploy.sh                  ← run this on the server to start everything
├── backend/app/
│   ├── main.py                ← Ashmit's main API (port 4002)
│   └── data_server.py         ← Ashmit's data server (port 4003)
├── frontend/                  ← Ashmit's React frontend (port 5180, unified login)
└── sabari_project/            ← Sabari's Ward Monitor (the LIVE copy)
    ├── backend/
    │   ├── main.py            ← FastAPI ward API (port 8006)
    │   ├── models.py          ← SQLAlchemy models — source of truth for column names
    │   ├── database.py        ← Cloud SQL connector
    │   ├── build_demo_db.py   ← seed 16 demo DCM patients (TRUNCATE, not drop)
    │   ├── mimic_sync.py      ← MIMIC-IV → ews_* ETL
    │   ├── engine/
    │   │   └── drug_lab.py    ← drug-lab rule engine (YAML-driven)
    │   └── rules/
    │       ├── drug_lab_rules.yaml
    │       └── news2_thresholds.yaml
    ├── app.js                 ← vanilla JS SPA frontend
    ├── index.html
    └── styles.css
```
