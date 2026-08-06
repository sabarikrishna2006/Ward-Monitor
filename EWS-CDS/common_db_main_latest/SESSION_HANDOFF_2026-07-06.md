# Session Handoff — Foqal CareOS Ward Monitor pilot-fixes-batch-2

Written 2026-07-06 to continue in a new chat. Point a fresh Claude session at this file plus `PROJECT_CONTEXT.md` and `CLAUDE.md`.

## Current git state

- Branch: `pilot-fixes-batch-2`
- Pushed and confirmed live on `origin` (https://github.com/sabarikrishna2006/Ward-Monitor): commit `ef02e85`
- **Uncommitted local changes exist right now** (see "In-progress, NOT yet committed" below) — a new chat should check `git status` first thing.

## What was fixed this session, file by file (all in commits `1aa383d` and `ef02e85`, already pushed)

**`backend/app/bq_mimic_loader.py`**
- Parallelized `fetch_patient_display`'s 7 sequential BigQuery queries via ThreadPoolExecutor (was 15-45s sequential).
- **Root-cause fix for the "0 vitals / stale patient" bug**: the chartevents fetch applied one global `LIMIT 100` across all 13 vital itemids combined. A patient with frequent BP/SpO2/RR readings could fill that budget alone, starving out Heart Rate/Temperature entirely — reproduced directly on hadm_id 20026625 (30 real HR readings existed in MIMIC, zero synced). Fixed with `ROW_NUMBER() OVER (PARTITION BY itemid ...)` so every vital type gets its own top-15 window regardless of how often other itemids are charted.

**`backend/app/bigquery_mimic_loader.py`**
- Parallelized the 10-tab lazy-load loop the same way.
- Fixed the actual root cause of "long sync time / patient stuck on Syncing forever": the ETL now flips `data_fetch_status` to `'fetched'` directly, in-process, right after its own EWS sync succeeds. Previously it deliberately set `'partial'` and depended on a *separate* HTTP call to the ward API to flip it back — if that call failed/was slow/hit the wrong port, the patient stayed "Syncing…" forever.

**`backend/app/data_server.py`**
- Stopped the status flip from being clobbered back to `'partial'` after the ETL already set `'fetched'`.
- Shortened the now-redundant HTTP nudge's timeout (it's just a cache-invalidation hint now, not load-bearing).

**`backend/app/cloud_sql_db.py`** and **`sabari_project/backend/database.py`**
- This Cloud SQL instance's `max_connections` is **25** (checked directly — smallest tier). Three backend services at the old `pool_size=5/max_overflow=10` could together demand 45 connections. Reproduced the failure live (`FATAL 53300: remaining connection slots are reserved`). Reduced both to `pool_size=2/max_overflow=3`.
- `database.py`'s `init_db()` now also runs two `CREATE UNIQUE INDEX IF NOT EXISTS` statements on every ward-API startup (self-healing schema migration — see mimic_sync.py entry below for why they're needed).

**`sabari_project/backend/mimic_sync.py`**
- Fixed a real concurrency bug: three independent code paths (billing's in-process sync, the ward API's own `/sync-vitals` endpoint, and the ward dashboard's background auto-sync thread) could all fire for the same patient simultaneously. Their check-then-insert pattern wasn't atomic → race → Postgres "current transaction is aborted" → silent partial/zero sync.
  - First attempted fix (`pg_advisory_lock`, session-scoped) caused a real deadlock — a connection returned to SQLAlchemy's pool without unlocking, permanently blocking future syncs for that patient. Traced via `pg_stat_activity`/`pg_locks`.
  - Correct fix: `pg_advisory_xact_lock` (auto-releases on commit) + the whole sync is now one atomic transaction (removed all interior `db.commit()` calls from `_sync_vitals`/`_sync_urine`/`_sync_labs`/`_sync_meds`).
  - Fixed `_sync_diagnosis`'s swallowed exceptions to `db.rollback()` instead of silently poisoning the rest of the transaction.
  - Added `ON CONFLICT (hadm_id, chart_time) DO NOTHING` to the real-data vitals insert (needs the new unique index above — without it, Postgres throws `42P10: no unique constraint matching ON CONFLICT`, which is what the pre-existing synthetic-fallback code path had been silently doing for a while).
  - Added a gap-fill fallback: if a vital type is genuinely never charted in MIMIC for a specific patient, fill only that missing field with a plausible stable value — never overwrites real data.

**`sabari_project/backend/main.py`**
- Added NEWS2-descending sort to `get_ward_data()` — dashboard rows are now always sorted most-critical-first.
- Fixed a bug where the arc-replay feature's global `REPLAY_OFFSET` was applied to *every* normal dashboard read, silently skipping the newest vitals for anyone who'd ever used replay (`safe_offset` now only applies `if replay`).
- Added `db_status` to the ward-data response (raw `active_patients.status`, separate from the computed clinical tier) — needed so the frontend can correctly detect `discharge_initiated`.
- Added `GET /api/escalations/{id}` — the status-log timeline screen was calling an endpoint that didn't exist.

**`sabari_project/app.js`**
- **Fixed the actual landing-page bug**: login boot code called `nav()` before the script finished evaluating `const SCREENS`, hitting a temporal-dead-zone error that silently killed the first render (no console error surfaced — page just looked blank until 30s auto-refresh or a manual click). Wrapped in `setTimeout(..., 0)`.
- Fixed 6 hardcoded `"NEWS2 Dashboard"` breadcrumbs (escalation flow n2/n3/n4, shift handoff, discharge screen) that ignored role — wrong label for GW nurses, and for charge nurses linked to a screen not even in her sidebar. Added a `dashboardCrumbHtml()` role-aware helper.
- **Charge nurse workflow fix**: she previously had to submit a CCU→GW transfer recommendation to herself and separately approve it. She can now transfer a patient in one click (`submitTransfer()` auto-approves when `APP.role === 'charge'`); if a bedside nurse already submitted a pending recommendation, she gets direct Approve/Reject buttons on the same screen instead of only "withdraw".
- Added cache-busting query strings (`?v=20260706`) to `app.js`/`styles.css` in `index.html` so browsers stop serving stale files after deploys — **note: `index.html` shows a linter-modified version with this already at `?v=20260706`; verify this matches what actually gets served.**

**`sabari_project/styles.css`**
- Actions column was clipped by `overflow:hidden`; fixed to scroll, then upgraded further to `position:sticky; right:0` so Escalate/Ack/Enter Vitals buttons are always fully visible with zero horizontal scrolling needed.

**`sabari_project/clean_test_patient.py`**
- Removed a hardcoded Postgres password (introduced by a parallel edit from "Antigravity", another AI tool the user is also using) — reverted to the env-var pattern (`CLOUD_SQL_PASS` must be exported, no fallback).

## In-progress, NOT yet committed (as of end of this session)

The user asked for a **manual vitals entry/override control** available for *any* patient at *any* time (not just stale/zero-vitals ones), so that if the real MIMIC sync still produces a gap somewhere, a nurse can always manually fix it — and so demo patients can be manually pushed into a stable state on demand. Findings and changes so far:

1. **Backend already supports this with zero changes needed** — `POST /api/patients/{id}/vitals` in `sabari_project/backend/main.py` has no restrictions; it accepts a fresh vitals row for any patient at any time. Confirmed by reading the code.
2. **Frontend gap found**: the "Enter Vitals" button only appeared on the dashboard row for `isStale` or zero-vitals patients — no way to manually correct/override vitals for a normal patient. **Fixed**: added a persistent `✎ Enter/Override Vitals` button to the patient-detail (`n1b`) action row, always visible regardless of status, for every role.
3. **Second gap found while fixing #2**: the vitals-entry form (`SCREENS.n_vitals`) had *empty* inputs (placeholder text only, not pre-filled with current values), and silently did nothing (no error toast) if any field was left blank — meaning a nurse could not correct just one wrong value without knowing/retyping all six. **Fixed**:
   - Form inputs now pre-fill with the patient's latest recorded vitals (`APP.data.n_vitals_latest`), so editing one field naturally preserves the rest.
   - Blank/invalid submission now shows a toast naming exactly which field(s) are missing, instead of silently doing nothing.

**These three `app.js` edits were made but NOT yet verified in a browser and NOT yet committed.** Next step for the new session: restart the local ward backend (`sabari_project/backend`, `uvicorn main:app --port 4985`, needs `.env.secrets` sourced first), navigate to any patient's detail page, confirm the "Enter/Override Vitals" button appears, click it, confirm the form is pre-filled with real values, test submitting a partial correction, then commit.

## Verified-stable real MIMIC hadm_ids for demo (step-down + discharge summary flow)

Synthetic patients (91001-91006 range) **cannot** generate discharge summaries by design — `generate_summary` reads only `ap_*` tables (real MIMIC data via BigQuery), and the endpoint explicitly 409s with "Clinical data not loaded for this patient" for synthetic-only patients. Confirmed by testing hadm_id 91001 directly.

| hadm_id | Name shown | Verified NEWS2 | Status |
|---|---|---|---|
| **20003014** | Divya Trivedi | 0 | Fully tested end-to-end THIS session: admission (56s) → complete vitals → escalation → resolve → step-down eligibility → transfer → charge-nurse one-click approval → GW → discharge-initiated → resident queue → discharge summary generation (11 tables, 247 records, EWS overlay correctly captured the escalation). Already stepped down/discharged from this testing — re-admitting will show existing state. |
| **20026625** | Neha Desai | 0 | Fully tested through step-down transfer earlier this session — this was the patient used to find and prove the vitals-starvation bug fix. Already stepped down to GW. |
| **20001395** | Ajay Choudhary | 2 | Fully tested through discharge summary generation earlier this session. Already discharge-initiated. |

Screened for good vitals but not personally walked through end-to-end:
- **20031593** (aortic valve stenosis, 67M) — HR 85, RR 16, SpO2 96%, BP 139
- **20004226** (recovered pulmonary embolism, 35F) — HR 90, RR 18, SpO2 95%, BP 107
- Also screened OK: 20002003, 20003008, 20004004, 20013244, 20022241, 20024373, 20025356, 20025423, 20026038

For a **completely fresh, untouched** patient, pick any hadm_id from the "screened but not walked through" list, or re-run the batch screening query (see `PROJECT_CONTEXT.md` or ask a new session to re-derive it from `backend/app/bq_mimic_loader.py`'s `_cardio_filter`).

Real drug-lab interaction demo (not a clean step-down case, but proves DL flags fire on real data): **20003174** (Deepak Singh) — genuinely stable vitals (HR78, RR14, SpO2 96%, BP122/68) but NEWS2 forced to 7/critical by a real amiodarone+digoxin+creatinine interaction in her actual MIMIC medication history.

## Known limitations, honestly stated

- **Gemini-generated summary text was never verified by me** — no `GEMINI_API_KEY` in the local dev environment all session. Everything up to that call (data fetch, clinical context, EWS overlay) is proven correct; the actual LLM output text is not something I've seen. Should be fine on the deployed server if the key is configured there (normal case).
- **The deployed server (72.60.102.196) was confirmed stale mid-session** — its live `app.js`/`styles.css` were missing fixes that had already been sitting in git history for a while. This was a deployment gap (git pull / redeploy didn't happen), not a code gap. **A new session should verify the server has actually pulled `ef02e85` and been redeployed (full `bash deploy.sh`, not a partial restart) before assuming any of the above fixes are live there.**
- **Architectural note for future work, not an active bug**: the whole EWS system works by restamping historical MIMIC timestamps to "now" to simulate a live ward. This is *why* patients can silently go stale mid-session (a single inserted vitals row ages out of the monitoring interval as real wall-clock time passes) and why real terminal/near-death MIMIC vitals can appear as "critical right now" for an unrelated demo patient. Not fixed this session (out of scope for bug-fixing) — flagged as a genuine design tension worth a proper heartbeat/simulated-clock redesign if this becomes a real pilot rather than a demo.
- No automated tests exist in either project — all verification this session (and prior sessions) has been manual (curl/API-level + targeted browser checks with DOM inspection, not automated regression tests).

## Local dev environment quick-start

```bash
# From common_db_main_latest/, always source secrets first:
source .env.secrets   # requires CLOUD_SQL_PASS; create from .env.secrets.example if missing

# Ward API (sabari) — port 4985
cd sabari_project/backend && source ../../.env.secrets && py -3 -m uvicorn main:app --port 4985

# Main API (ashmit) — port 7015
py -3 -m uvicorn backend.app.main:app --port 7015

# Data server (ashmit) — port 7016, must point WARD_API_BASE at the ward API above
WARD_API_BASE=http://localhost:4985 py -3 -m uvicorn backend.app.data_server:app --port 7016

# Unified login frontend — port 4990 (plain static serve)
cd frontend && py -3 -m http.server 4990
```

Demo login shortcuts (on the unified login page, port 4990):
- Bedside/CCU Nurse: `rekha.devi` / `WardNurse@2026`
- GW Nurse: `prathima.m` / `GWNurse@2026`
- Charge Nurse: `leena.kurup` / `ChargeNurse@2026`
- Resident: `dr.anand` / `Resident@2026`

Real BigQuery access requires gcloud ADC (`gcloud auth login` as the IIIT account) — confirmed available and working this session.

## Deploy note

`deploy.sh` was independently modified during this session (by the user or a linter, not by me) — ports changed to 7025 (main)/7026 (data)/5000 (ashmit frontend)/7826 (ward API)/4995 (ward frontend). **A new session should re-read the current `deploy.sh` before assuming any port numbers** — the ones in this handoff's "quick-start" section above (7015/7016/4990/4985) reflect what I was actually running locally this session, which may now be stale relative to the just-edited `deploy.sh`.
