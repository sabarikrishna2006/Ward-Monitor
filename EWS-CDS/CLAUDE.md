# Foqal CareOS — Project Instructions for Claude

## 1. This Is an Ecosystem, Not Two Separate Projects

Ashmit's Hospital Efficiency system and Sabari's Ward Monitor are **one integrated product**. They share a single Cloud SQL database, a unified login flow, and are deployed together by a single script. Never treat them as independent.

Both must be running simultaneously for anything to work:

| Service | Who | Port |
|---------|-----|------|
| Main API (discharge summaries, RAG) | Ashmit | 6010 |
| Data server | Ashmit | 6020 |
| Unified login frontend | Ashmit | 6001 |
| Ward Monitor API | Sabari | 6030 |
| Ward Monitor frontend | Sabari | 6040 |

Server IP: `72.60.102.196`
Deploy command (on server): `bash deploy.sh` from inside `common_db_main_latest/`

Port numbers have drifted before without this file being updated (an older scheme — 4002/4003/5180/8006/5175 — still exists in a stale `deploy.sh` copy elsewhere in the repo; do not use it). Before trusting any port number, including the ones above, verify against the live server directly:
```
curl -s -o /dev/null -w "%{http_code}" http://72.60.102.196:<port>/
```

The frontend's shared port config lives in `common_db_main_latest/frontend/config.js` and is environment-aware (different values for local dev vs. production, auto-detected by hostname/port). If you change local dev ports, update the local branch there; if you change production ports, update the production branch there **and** the table above **and** `common_db_main_latest/deploy.sh` together. These three have gone out of sync before — it breaks the login → ward-monitor redirect with a dead connection and no error message, so it's easy to miss until someone actually clicks through.

---

## 2. There Is Exactly One Real Copy of Each Project

`common_db_main_latest/` is the current, correct, actually-deployed root for both projects:

```
common_db_main_latest/
├── deploy.sh                  ← the real deploy script — matches the live server's ports
├── backend/app/                ← Ashmit's backend
├── frontend/                   ← Ashmit's frontend + shared config.js
└── sabari_project/             ← Sabari's Ward Monitor — the LIVE copy
```

Other copies exist elsewhere in the repo (`EWS-CDS/sabari_project/`, `EWS-CDS/ashmit project/sabari_project/`) — these are stale leftovers from an earlier project layout and are **not** deployed. Confirmed via `git log`/`git status` (only `common_db_main_latest` has commits reaching `origin`) and via direct verification against the live server. If you find yourself editing anything outside `common_db_main_latest`, stop and re-verify which copy you're in before continuing.

**Always make code changes in `common_db_main_latest/sabari_project/`** (Sabari's side) or `common_db_main_latest/backend/` + `common_db_main_latest/frontend/` (Ashmit's side).

---

## 3. Mandatory Testing Workflow — Never Skip Steps

```
Edit code  →  Test locally  →  User approves  →  Push to GitHub  →  Pull on server  →  bash deploy.sh
```

1. **Make changes** in `common_db_main_latest/sabari_project/` (and Ashmit's code if needed).
2. **Test locally first.** The Ward Monitor backend serves its own frontend as static files (`uvicorn main:app --port 8006` from `sabari_project/backend/` is enough for local testing — no separate dev server needed). Hit real endpoints with curl or a browser. Do not claim something works without running it.
3. **Wait for explicit user approval** before suggesting a push.
4. **Never run `git push`** without the user saying so.
5. **Never run `bash deploy.sh`** remotely without the user confirming the server pull is done.
6. **After any deploy-affecting change** (ports, shared config, new dependencies), verify directly against the live server rather than assuming a passing local test guarantees the deploy will also work — some classes of bug (config drift, environment-specific paths) only show up once actually deployed.

---

## 4. Shared Cloud SQL Database — Handle With Care

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
- The connection pool is small (`pool_size=2, max_overflow=3` per service — the Cloud SQL instance's `max_connections` is 25 total, shared across all three backend processes). Don't raise these without checking the actual ceiling first.

---

## 5. Backend Code Rules — Lessons Learned, Kept Current

These are bugs that actually happened in this codebase, not generic advice. When a new one costs real debugging time, add it here rather than letting this list go stale.

### Timestamps from MIMIC-sourced data are not trustworthy at face value
MIMIC de-identifies admission dates by shifting them, sometimes by decades (an observed case: a patient's `admit_time` landed in the year 2150). Vitals timestamps for the same patient may have been separately re-anchored to a realistic recent timeline by a sync job, so `admit_time` and `chart_time` can end up on completely different clocks for the same patient. Any feature computed as `(now - admit_time)` or similar must be sanity-bounded — reject negative or multi-year durations and fall back to something derived from the patient's own already-fetched data — or it silently feeds a wildly out-of-range value straight into a model.

### Never derive a new row's timestamp from a global MAX() across the whole table
`chart_time = MAX(chart_time) across ALL patients` is only ever correct if the table is empty. In practice it means every new insert reuses whatever the single most-recent timestamp anywhere in the table happens to be — harmless the first time, but a guaranteed unique-constraint collision the moment the same patient gets a second reading submitted shortly after, because the timestamp never advanced. For a live data-entry endpoint, use real wall-clock time (optionally bumped past the patient's own last record if that's later), never a global aggregate.

### Stateful logic that must survive a restart cannot live in an in-process variable
A latch/hysteresis mechanism implemented as a plain in-memory dict keyed by patient ID resets to empty on every process restart or redeploy — an alarm that should stay latched until vitals genuinely improve can silently un-latch on restart, with no error and no obvious symptom until someone specifically tests a restart. If a decision needs to persist across restarts, derive it fresh each time by replaying the relevant history from the database — don't cache it in memory.

### A shortened poll interval needs a concurrency guard
Reducing a frontend auto-refresh interval to feel more responsive is fine on its own, but if any single refresh can be slow (a cold cache, a heavy query), a naive `setInterval` fires the next poll before the previous one returns — stacking concurrent slow requests against a connection pool that may only have single-digit capacity. Any time a poll interval is shortened, add an in-flight guard that skips a tick if the previous one hasn't resolved yet.

### Shared cross-app config must be environment-aware and verified, never assumed
A config file shared between the login app and the ward-monitor frontend that hardcodes one fixed set of ports works fine until local dev needs different ports than production — at which point it silently sends the wrong environment to the wrong place, breaking a redirect with a dead connection and no error message. Any shared inter-service config needs to branch on environment (hostname/port detection), and after any change, verify by actually curling the endpoints it points at rather than trusting that a value looks plausible.

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

### No N+1 Queries — Including Model-Scoring Loops
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
The same shape of cost applies to any per-patient loop that calls an ML model, not just DB queries — scoring 50 patients one at a time, each with multiple booster evaluations, is slow enough to matter. Batch it the same way: assemble the full input set first, score once.

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
common_db_main_latest/
├── deploy.sh                  ← run this on the server to start everything
├── backend/app/
│   ├── main.py                ← Ashmit's main API (port 6010)
│   └── data_server.py         ← Ashmit's data server (port 6020)
├── frontend/                  ← Ashmit's frontend (port 6001, unified login)
│   └── config.js              ← shared port config, environment-aware — see §1
└── sabari_project/            ← Sabari's Ward Monitor (the LIVE copy)
    ├── backend/
    │   ├── main.py            ← FastAPI ward API (port 6030 in production; 8006 is the common local-testing port)
    │   ├── models.py          ← SQLAlchemy models — source of truth for column names
    │   ├── database.py        ← Cloud SQL connector
    │   ├── escalation_model.py← ML deterioration-risk scoring module
    │   ├── model/              ← served model artefacts (boosters, calibrators, serving_meta.json)
    │   ├── build_demo_db.py   ← seed demo patients (TRUNCATE, not drop)
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

---

## 7. Before Trusting Anything In This File

Every fact above — ports, file locations, which copy is real — has drifted at least once without this file being updated to match, and each time cost real debugging effort to rediscover. When in doubt on anything environment- or deployment-related, verify directly (curl the live server, check `git log`/`git status`, read the actual running config) rather than trusting this document at face value. If something here turns out to be wrong, fix it in place — don't quietly work around it and leave the next person to hit the same wall.
