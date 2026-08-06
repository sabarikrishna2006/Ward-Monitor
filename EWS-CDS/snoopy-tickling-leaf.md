# Foqal CareOS — Pilot-Hardening Review & Action Plan (`common_db_main_latest`)

## Context

We are hardening the integrated EWS-CDS + Discharge AI system and **deploying it to the server today** (no live hospital testing today — the real Indian-hospital pilot follows, with soak time on the server in between). The target is `common_db_main_latest/` — the merged monorepo (root `deploy.sh` is the orchestrator; `backend/`+`frontend/` = Ashmit's Discharge AI, `sabari_project/` = Sabari's Ward Monitor). The bar is "everything works perfectly on the server." Because the eventual environment is zero-tolerance clinical (a name/ID mix-up at discharge is a patient-safety and legal NABH event, not a cosmetic bug), we fix to clinical-grade quality now.

This plan delivers: (1) a deep critique, (2) concrete fixes for the 4 named critical bugs, (3) fixes for additional patient-safety/liability flaws found during the trace, and (4) an automated + manual test plan proving the patient journey end-to-end.

**Decisions locked with the user:** patients arrive **both live (HIS admit) and pre-seeded**; `active_patients.patient_name` is the **single source of truth** for ward-originated identity; scope is **full coverage of all flaws**; automated testing = **backend pytest + extended `verify_*.py` E2E**.

### Engineering note (full coverage is now reasonable)
Since today's deploy is to the **server, not to live patients**, full coverage (P0+P1+P2) is the right call — there is soak time before the hospital pilot, so a thorough rewrite can be validated on the server first. The work is still **tiered by risk** so that if anything destabilizes, P0 (patient-safety) and P1 (UX) can be shipped independently of the P2 ops/security cleanup. Order of execution: P0 → P1 → P2, with the test suite green before push.

---

## System map (verified)

| Service | Source | Port | Start (root `deploy.sh`) |
|---|---|---|---|
| Main API (encounters, summary gen) | Ashmit | 4002 | `uvicorn backend.app.main:app` |
| Data server (display/MIMIC tabs) | Ashmit | 4003 | `uvicorn backend.app.data_server:app` |
| Unified login frontend (Vite) | Ashmit | 5180 | `npm run dev` |
| Ward Monitor API | Sabari | 8006 | `uvicorn main:app` |
| Ward Monitor frontend (Vite) | Sabari | 5175 | `VITE_API_URL=...:8006 npm run dev` |

Identity key across both systems = **`hadm_id`** (PK of `active_patients`). Bridge: `hospital_core.admissions(hadm_id UNIQUE → uhid)`. Demo IDs: seeded 91001–91006; live admits 10100+ — both deliberately non-MIMIC.

---

## Critique by risk tier (with evidence)

### P0 — Patient safety / data integrity (MUST fix before any deploy)
1. **Identity fragmentation at GW→Resident handoff.** Two name-resolution paths can disagree:
   - Doctor side: `/api/patient/{hadm_id}/display` prefers MIMIC `ap_admissions` and only falls back to `active_patients.patient_name` via `_synth_display` (`backend/app/data_server.py:464–528`, `_synth_display:118–145`).
   - Ward side: `active_patients.patient_name` (`sabari_project/backend/models.py`).
   - Trigger: `initiate-discharge` sets `data_fetch_status='fetched'` (`sabari_project/backend/main.py:1291–1327`) while `ap_diagnoses` is empty → display endpoint **re-runs BigQuery ETL** (`data_server.py:491–511`). On a non-MIMIC id ETL fails → name becomes `"Demo Patient"` ("lost"); on any id collision it returns a *different* real patient ("changed"). Also `_display_memory_cache` can serve stale identity.
2. **Empty/blank patient cards.** No guard for missing vitals; rows render with all `--` (`sabari_project/app.js:420–541`; backend emits `"--"` at `sabari_project/backend/main.py:804–810`). A nurse cannot distinguish "no data yet" from "all-normal" — clinically dangerous.
3. **`LEFT JOIN` can surface encounters with NULL clinical metadata** in the doctor queue (`backend/app/cloud_sql_app_db.py:393–415`) — discharge proceeds with missing provenance.

### P1 — Demo-blocking UX (fix today)
4. **Blocking/synchronous load — white screen until data arrives.** `nav()` is `await`-ed on fetch before first paint; no skeleton/spinner (`sabari_project/app.js:77–135`, called un-awaited at `:244–256`; `#main` empty in `index.html`). Contrast Ashmit's shell-first + skeleton pattern (`frontend/state.js:34–70` `_applyRender`/`renderApp`, `frontend/dashboard.html:109–179` skeleton CSS).
5. **Scroll lost on resize/minimize.** `#layout{position:fixed}` (desktop) flips to `position:relative` at `@media(max-width:768px)` while `#content{overflow:hidden}` clips; fixed-height flex chain doesn't reflow (`sabari_project/styles.css:40–63, 264–279`).

### P2 — Architecture / security / ops (recommend follow-up, not same-day)
6. **`nginx.conf` is stale** — routes to 8001/8002/5173, not the real 4002/4003/5180 (`nginx.conf`). If nginx is in the serving path, the demo breaks.
7. **CORS wide open with credentials on Sabari** (`allow_origins=["*"]`, `allow_credentials=True`, `sabari_project/backend/main.py:58–64`) — invalid/unsafe combination.
8. **`hospital_core.admissions.status` not advanced at discharge** (`sabari_project/backend/main.py:1291–1327`) — bridge state drifts from reality (audit/NABH gap).
9. **Audit-trail completeness:** Ashmit has `app_audit_log` (`cloud_sql_app_db.py:664`); confirm the ward side logs escalations/discharge actions for NABH. (Verify before asserting a fix.)

---

## Action plan — the 4 critical bugs

### Fix 1 — Unify patient identity (P0)
Make `active_patients.patient_name` authoritative for ward-originated (non-MIMIC) patients so ETL can never overwrite it.
- **`backend/app/data_server.py` `get_patient_display` (464–528):** before any BQ ETL re-run, detect ward-origin (e.g. `hadm_id` not a MIMIC id / `active_patients` row exists with a real name) and return `_synth_display` directly — **never** enter the ETL branch (491–511) for these. Always overlay `active_patients.patient_name` onto the returned payload so `patient_name`/`full_name` are correct even on the MIMIC path.
- **`_synth_display` (118–145):** stop defaulting to `"Demo Patient"`; if `active_patients.patient_name` is missing, surface the de-identified `patient_code`/`HADM ID` (matches existing de-identification choice) rather than a wrong-looking placeholder.
- **Cache safety:** key/guard `_display_memory_cache` so a re-admit or status change invalidates the entry; `initiate-discharge` should clear it (it already clears `_ward_cache`).
- **`sabari_project/backend/main.py` `initiate-discharge` (1291–1327):** also set `ward_location='GENERAL_WARD'` and advance `hospital_core.admissions.status`; ensure the `app_encounters` row carries `patient_name`/`display_id` so the doctor queue never depends on the join alone.
- **`backend/app/cloud_sql_app_db.py` `list_encounters` (393–415):** add `ap.patient_name` to the SELECT so the queue card has a guaranteed name independent of `/display`.

### Fix 2 — Async shell-first loading (P1)
Port Ashmit's pattern into Sabari's vanilla SPA.
- **`sabari_project/index.html`:** render the shell (header/sidebar) immediately; give `#main` initial skeleton markup.
- **`sabari_project/app.js` (`nav` 77–135, `onFoqalLogin` 244–256):** paint shell + skeleton **before** `await fetch`; render data on resolve; show an error/retry state on failure (mirror `frontend/screens/doctor-queue.js:33–63` timeout+retry).
- **`sabari_project/styles.css`:** add `.skeleton` shimmer (copy from `frontend/dashboard.html:109–111`).

### Fix 3 — Empty-state handling (P0/P1)
- **`sabari_project/app.js` render loop (420–541):** if a patient has no usable vitals AND is not `status==='loading'`, either filter out or render an explicit "Awaiting first vitals" state — never a silent all-`--` row. Keep `loading` patients visible.
- Confirm backend `--` sentinels (`main.py:804–810`) map to this state, not to false "Stable".

### Fix 4 — Responsive scroll (P1)
- **`sabari_project/styles.css` (40–63, 264–279):** make the scroll container own a real, reflowing height (`min-height:0` on flex children; `overflow-y:auto` on `#main`; avoid `position:fixed` height traps). Verify at desktop, 768px, and minimized widths.

### Additional (P2, include if shipping the rewrite)
- Repoint `nginx.conf` to 4002/4003/5180 (or confirm nginx is bypassed in the demo).
- Fix Sabari CORS: explicit origin allowlist when `allow_credentials=True`.
- Advance `hospital_core.admissions.status` + verify ward-side audit logging for NABH.

---

## Test plan

### Automated (backend pytest + extend `verify_*.py`)
- Extend `verify_his_flow.py` to assert **name integrity**: live admit → ward shows name N → `initiate-discharge` → `/api/encounters` card name == N → `/api/patient/{hadm_id}/display` `patient_name` == N → never `"Demo Patient"`, never a different name. Run for **both** a live-admitted (10100+) and a seeded (91001–91006) patient.
- `test_patient_fetch.py` / `backend/tests/`: unit-test `get_patient_display` ward-origin branch (no ETL re-run; name overlay), `_synth_display` no-placeholder behavior, and `list_encounters` returning `patient_name`.
- Empty-vitals: assert a patient with null vitals is filtered/flagged, never rendered as a silent all-`--` row (test the data the frontend consumes).

### Manual matrix (Test Case → Expected → Actual)
| # | Scenario | Expected |
|---|---|---|
| 1 | Live admit → CCU ward | Card shows correct name + first vitals; no blank card |
| 2 | Seeded patient (9100x) on ward | Identical behavior to live |
| 3 | CCU → GW step-down | Same `hadm_id`, name unchanged, appears in GW view |
| 4 | GW nurse → Initiate Discharge | Patient appears in Resident queue with **same name + ID** |
| 5 | Resident → Generate summary | `/display` name == ward name; never "Demo Patient"/other |
| 6 | Patient with no vitals yet | "Awaiting vitals" state, not blank/all-`--` |
| 7 | Resize desktop→768px→minimized | Dashboard stays scrollable; no clipped content |
| 8 | Cold load of dashboard | Shell + skeleton paints instantly; data fills in async |
| 9 | Backend down on load | Error/retry state, not infinite white screen |
| 10 | Re-admit reusing an id | No stale cached identity served |

### Rollout sequence
1. Apply P0+P1 in `common_db_main_latest/` (per CLAUDE.md: edit the live copy, test locally first).
2. Run pytest + `verify_his_flow.py` locally until green (capture output — no success claims without it).
3. Manual matrix locally via root `deploy.sh` (5 services).
4. User approves → push → pull on server (`72.60.102.196`) → `bash deploy.sh`.
5. Decide P2 inclusion at this gate (recommend defer).

---

## Critical files
- Identity: `backend/app/data_server.py` (464–528, 118–145), `backend/app/cloud_sql_app_db.py` (393–415), `sabari_project/backend/main.py` (1291–1327, 298–392)
- Frontend bugs: `sabari_project/app.js` (77–135, 244–256, 420–541), `sabari_project/index.html`, `sabari_project/styles.css` (40–63, 264–279)
- Reference pattern: `frontend/state.js` (34–70), `frontend/dashboard.html` (109–179), `frontend/screens/doctor-queue.js` (33–63)
- Tests: `verify_his_flow.py`, `test_patient_fetch.py`, `backend/tests/`
- Ops (P2): `nginx.conf`, `sabari_project/backend/main.py` (58–64 CORS)

---
---

# ADDENDUM — Corrected MIMIC-centric architecture & data-flow (new findings)

> This addendum supersedes the assumption in **System map** (line 26) that demo patients are "deliberately non-MIMIC." After tracing the billing flow we found the **operative admission path uses a real MIMIC `hadm_id` end-to-end**. The non-MIMIC ids (91001–91006, 10100+) belong only to the *standalone* seed / `POST /api/patients` paths, which are NOT the integrated demo path. Everything above stays valid; the items below refine the identity/data-flow fixes.

## Corrected understanding (verified)
The **billing ("BILL guy") flow** admits a **real MIMIC `hadm_id`**, so MIMIC natively supplies all clinical + narrative depth (HPI, labs, imaging, cath notes). No synthetic/fabricated data is needed for the demo. The patient is one real MIMIC record from admission → discharge; the only "synthetic" element is the **de-identified display name** in `active_patients.patient_name`.

**Verified end-to-end chain (billing admit):**
1. `generate-estimate` → INSERT `active_patients` (identity + de-identified name) — `backend/app/main.py:1166`.
2. `POST /api/patient/{hadm_id}/prefetch-all` → BQ ETL writes `ap_*` tables (recent-N limits), status `'partial'` — `data_server.py:685–725`.
3. `POST /api/patients/{hadm_id}/sync-vitals` → `sync_patient_from_mimic` writes `ews_vitals_timeseries / ews_lab_events / ews_medications`, status `'fetched'` — `sabari_project/backend/main.py:1278–1295`, `mimic_sync.py`.
4. Ward reads `ews_*`; discharge reads `ap_*`.

## Answers to the user's data-flow questions
- **Are all tables written on admit?** Yes, but via the 3-step chain above — and orchestration is **browser-side fire-and-forget** (`billing.html:868–882`). A closed tab / failed leg strands a patient at `'partial'` (ap_* present, ews_* empty). → needs server-side orchestration (Fix A0).
- **Data volume/time?** Already bounded: recent-N per tab (chartevents 50, labs 25, meds/poe 20, notes 100 — `bq_mimic_loader.py:362–406`) + itemid-filtered vitals (`mimic_sync.py:13`). Not a volume problem; latency = ~9 BQ round-trips. Optional P2: parallelize/pre-warm.
- **Does discharge use EWS data today?** **No** — `build_clinical_context` (`main.py:2850`) reads only `ap_*`. The ward overlay (NEWS2, escalations, transfers, drug-lab actions, nurse vitals) is currently lost. → Fix A2.
- **Synthetic patients at discharge?** Have no `ap_*` data → fabricate via `_synth_tab`. → backfill + quarantine + hard guard (Fix A3).

## Decisions locked (this round) — refine the originals
- Admission standardized on **billing/MIMIC**; synthetic standalone paths guarded/quarantined.
- `active_patients.patient_name` = single source of truth (unchanged); MIMIC blank/real name never overrides it.
- Discharge **must merge the EWS overlay** (provenance-labeled) on top of the MIMIC base.

## Additional P0 fixes (extend the Action plan)

**Fix A0 — Server-orchestrated, idempotent, count-verified data load.**
Replace the browser-orchestrated chain with one backend path that runs prefetch-all → sync-vitals → verifies `ap_*` AND `ews_*` row counts → sets `'fetched'` only when both are populated, with retry. Browser just polls status. Guard `/display` so it never re-runs ETL for a `'fetched'` patient. (Touches `data_server.py:685–725`, `sabari_project/backend/main.py:1278–1295`, `frontend/billing.html:868–882`.)

**Fix A2 — Merge EWS overlay into discharge `clinical_context`.**
Add an EWS-overlay fetch (`ews_escalations`, `ews_drug_lab_actions`, `ews_ccu_transfers`, NEWS2 trajectory, nurse-charted `ews_vitals_timeseries`) and merge into `build_clinical_context` (`main.py:2850`), each block tagged `[WARD-GENERATED — EWS]` for NABH provenance. Same Cloud SQL DB → data server can read `ews_*` directly.

**Fix A3 — Block discharge without real data + backfill/quarantine.**
- Refuse "Generate Summary" when `data_fetch_status != 'fetched'` / no `ap_*` rows, with a clear "Admit via billing first" message (no fabricated summary ever reaches a doctor).
- One-time **backfill** seed: take data-rich real MIMIC hadm_ids (`get_top_dcm_patients`, `bq_mimic_loader.py:206`) and run the full server-side admit→prefetch→sync chain → pre-loaded ward patients with real data, discharge works without live billing.
- **Quarantine** old fabricated rows (91001–91006, 10100+) from `active_patients` (only DELETE EWS-owned rows per CLAUDE.md; never touch `ap_*`).

## Additional tests (extend the Test plan)
- **Load completeness/idempotency:** after server-orchestrated load, assert both `ap_*` and `ews_*` counts > 0 and status `'fetched'`; re-run is a no-op. Manual TC: close browser mid-load → patient still reaches `'fetched'`, not stranded `'partial'`.
- **EWS overlay reaches discharge:** create an escalation + drug-lab action on the ward → generate summary → assert `clinical_context` contains the provenance-tagged ward blocks.
- **Discharge guard:** patient with no `ap_*` data → Generate Summary refused.

## Additional critical files (this round)
- Load chain: `frontend/billing.html` (868–882), `backend/app/data_server.py` (685–725), `sabari_project/backend/main.py` (1278–1295), `sabari_project/backend/mimic_sync.py`
- EWS overlay: `backend/app/main.py` `build_clinical_context` (2850)
- Backfill: new seed script using `bq_mimic_loader.get_top_dcm_patients` (206)
