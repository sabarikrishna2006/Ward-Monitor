# Ward Monitor — Pre-Demo Click-Through QA Plan

Purpose: verify, by actually clicking through the browser (not API calls), that
the full escalation → de-escalation flow and all three personas work with no
visual/interaction bugs before tomorrow's demo. This document is self-
contained — no prior conversation context needed.

## 0. Setup (do this first)

```
cd common_db_main_latest/sabari_project/backend
set CLOUD_SQL_PASS=foqalAnalyticsHealthcareDB2026      (Windows cmd)
export CLOUD_SQL_PASS=foqalAnalyticsHealthcareDB2026   (bash)
py -3 -m uvicorn main:app --port 8006
```
Wait for `Application startup complete`. This ONE process serves both the API
and the full frontend (main.py mounts the frontend as static files at `/`).

Reset the two demo patients to a clean, tested baseline (safe to rerun any
time — it will not touch anything except hadm_id 91007/91008):
```
py -3 seed_demo_arc_patient.py
```

Optionally clear every OTHER patient's stale-vitals flag so the ward doesn't
look full of faded/overdue patients during QA (does not touch 91007/91008):
```
cd ..
py -3 refresh_cloud_vitals.py
```

Open the browser to: **http://127.0.0.1:8006**

## 1. How login works here (read this before clicking anything)

This app's login screen was removed — it now expects to receive an
authenticated user via `sessionStorage` (normally set by a separate login
app, which is NOT part of this local test). To open each persona locally,
run this in the **browser's DevTools console** (F12 → Console tab) BEFORE
navigating to `http://127.0.0.1:8006`, then load/reload the page:

**CCU Nurse:**
```js
sessionStorage.setItem('foqal_token', 'qa-test-token');
sessionStorage.setItem('foqal_user', JSON.stringify({
  role: 'nurse', name: 'Priya Nair', roleLabel: 'Staff Nurse',
  shift: 'Day', ward: 'Ward 4B/4C', empId: 'QA-001'
}));
location.reload();
```

**Head Nurse (Charge):**
```js
sessionStorage.setItem('foqal_token', 'qa-test-token');
sessionStorage.setItem('foqal_user', JSON.stringify({
  role: 'charge', name: 'Meera Shah', roleLabel: 'Head Nurse',
  shift: 'Day', ward: 'Ward 4B/4C', empId: 'QA-002'
}));
location.reload();
```

**GW Nurse:**
```js
sessionStorage.setItem('foqal_token', 'qa-test-token');
sessionStorage.setItem('foqal_user', JSON.stringify({
  role: 'gw_nurse', name: 'Anjali Rao', roleLabel: 'GW Nurse',
  shift: 'Day', ward: 'Ward 2A', empId: 'QA-003'
}));
location.reload();
```

To switch persona: run `sessionStorage.clear()` in the console, then set the
next persona's values as above and reload. (This is a legitimate local test
bypass of the normal cross-app SSO handoff — it does not change any app
behavior, it just supplies what the login app would normally supply.)

## 2. The two demo patients (know these before testing)

- **hadm_id 91007 — "Vikram Rao", Ward 4B (CCU).** Baseline: NEWS2=0/stable,
  escalation-risk LOW (~3%), one non-critical drug-lab WARNING badge visible
  (potassium trending on an ACE inhibitor). This is the "before" state.
- **hadm_id 91008 — "Vikram Rao", Ward 2A (General Ward).** NEWS2=0/stable,
  escalation-risk LOW, zero drug-lab alerts. This is the "after/recovered"
  state — a separate patient record representing him stepped down.

## 3. CCU Nurse walkthrough

Log in as **nurse** (section 1). You should land on the **NEWS2 Dashboard**.

- [ ] Dashboard loads within ~15s on first load (cold), then fast on repeat
      visits. Do not panic at a slow first load — that's the escalation model
      scoring the whole ward once; the next several requests are cached.
- [ ] Stat tiles at top (Critical/Medium/Low/Stale) show plausible non-zero
      counts; clicking a tile filters the table to just that group; clicking
      it again returns to "all".
- [ ] Table shows an **AI Risk** column with a colored tier badge
      (CRITICAL RISK=red, HIGH RISK=amber, LOW RISK=green) plus a % number
      and a small sparkline. Confirm the badge color matches the tier text —
      this was a real bug found and fixed tonight (a patient-detail element
      used to show a fixed purple color regardless of severity).
- [ ] Click the **"AI Risk ↕"** column header — table re-sorts by escalation
      risk descending. Click **"NEWS2 ↕"** — re-sorts by NEWS2 instead.
- [ ] Find Vikram Rao (91007) in the CCU list. Open his row → **Patient
      Detail**.
- [ ] On his detail page: NEWS2 badge, diagnosis banner, and an **"AI risk"**
      figure in the top banner — confirm its color also matches his current
      tier (not a fixed color).
- [ ] Click through all 5 tabs: Vital Signs, ML Insights, Drug-Lab Alerts,
      Lab Results, Medications. Confirm each renders without a blank
      screen or console error. On **ML Insights**: risk %, tier, deterioration
      window, and "top contributing signals" bars should all be populated.
      On **Drug-Lab Alerts**: one WARNING-severity hyperkalemia alert should
      be visible, readable, not garbled.
- [ ] Open **Nurse Vitals Entry** (from his detail page). Submit a bad
      reading: `SpO2 88, RR 27, HR 122, SBP 84, DBP 54, Temp 38.1, Air/Oxygen
      = Oxygen, AVPU = A`. Submit.
  - [ ] Confirmation shows NEWS2 jumped to ~13-14, CRITICAL.
  - [ ] Navigate back to the dashboard (or his detail page) — his AI Risk
        badge should now show **CRITICAL RISK**, colored red, with a
        materially higher % than before.
- [ ] From his detail page, click **"Escalate Now"** → fills out and submits
      the **Escalation Form** (n2). Confirm no error, and you're routed to
      the post-escalation confirmation screen (n3).
- [ ] Open **Nurse Vitals Entry** again and submit 2-3 improving readings
      (e.g. `SpO2 94→96, RR 20→18, HR 98→86, SBP 106→116, DBP 68→74, Temp
      37.4→37.0, Air`). Confirm each submission succeeds (no 500 — this was a
      real bug tonight: rapid successive submissions used to collide on a
      timestamp and crash). Tier is expected to **stay CRITICAL** through
      these — that's correct hysteresis behavior, not a bug; don't flag it.
- [ ] Open **Shift Handoff** (n6) — loads a nurse list and form without
      error; fill a note, complete it, confirm the "Handoff Complete" screen
      (n6b) shows something sensible.
- [ ] Open **Active DL Flags** (dl3) — loads without error, shows drug-lab
      flags across the ward.
- [ ] Find any patient shown as faded/"Stale" (or click the "Stale Vitals"
      tile to filter to them). Open their **Nurse Vitals Entry**, confirm it
      shows "⚠ Last vitals recorded X min ago — entry required", submit a
      fresh reading, confirm the patient un-fades and NEWS2 recomputes.
- [ ] Click **"CCU → GW Transfer"** on the dashboard header (or a patient's
      "CCU→GW Transfer" button). If eligible, submit a transfer request.
      Confirm no error.

## 4. Head Nurse (Charge) walkthrough

`sessionStorage.clear()`, log in as **charge** (section 1). You should land
on the **Escalation Queue** (n5).

- [ ] Escalation Queue lists active escalations, including the one you just
      created for Vikram Rao in section 3 (if you did that step first).
      Shows patient name, ward, bed, NEWS2, SLA timer.
- [ ] If you submitted a CCU→GW transfer request in section 3, it should
      appear here pending approval. Click **Approve**. Confirm success toast,
      no error.
- [ ] Open **Threshold Config** (n5b) — loads without error (may be a static
      config form; just confirm it renders).
- [ ] Open **DL Flag Overview** (dl1) — loads ward-wide drug-lab data without
      error.
- [ ] Open **Tier 1 Co-Sign** (dlcosign) — try co-signing a WARNING-tier flag
      (e.g. Vikram Rao's hyperkalemia early-warning). Confirm success, no
      error, and that the underlying alert is still visible afterward on his
      patient page (co-signing an action must not silently hide a still-true
      lab-based alert).
- [ ] Resolve or acknowledge the escalation you created for Vikram Rao so it
      doesn't linger before tomorrow (avoid leaving test state behind).

## 5. GW Nurse walkthrough

`sessionStorage.clear()`, log in as **gw_nurse** (section 1). You should land
on the **GW Dashboard**.

- [ ] Dashboard shows only General Ward patients (location filter working).
- [ ] **Right after approving a transfer in section 4**, this screen should
      show the newly-transferred patient within a few seconds without you
      doing anything — the dashboard auto-polls every 5 seconds now (used to
      be 30s; this was changed tonight specifically for this scenario). If
      it takes noticeably longer than ~10s, that's worth flagging.
- [ ] Find Vikram Rao (91008) — confirm NEWS2=0/stable, LOW escalation risk,
      **zero** drug-lab alerts on his detail page (this is meant to be the
      fully-recovered "after" state — no lingering flags).
- [ ] Repeat the stale-patient check from section 3 (find/simulate a stale
      GW patient, refresh via Nurse Vitals Entry, confirm it un-fades) — this
      exercises the exact same shared code path as CCU, but confirm it
      visually too.
- [ ] Open Escalation Form, Status Log, Shift Handoff, Active DL Flags for
      this role — confirm all load without error (same underlying screens as
      CCU nurse, just role-filtered).

## 6. Cross-cutting checks (any persona)

- [ ] Click the **AI Model Clinical Performance** info panel/modal wherever
      it's surfaced. Numbers shown (recall, PPV, lead time, AUROC) should be
      populated, not "—" or an obviously stale/hardcoded-looking number
      (recall ~89%, PPV ~23.6%, lead time ~11.0h, AUROC ~0.71 as of tonight).
- [ ] Resize the browser to a narrow/mobile width. Confirm the dashboard
      table switches to card mode and the "Escalation Risk"/"AI Risk" field
      still has a label and isn't cut off or unlabeled.
- [ ] Open browser DevTools console (F12) and watch for any red errors while
      clicking through — report anything that appears, even if the UI
      visually looked fine (a caught/swallowed error can still indicate a
      real bug).
- [ ] Confirm no screen ever shows a completely blank white page or an
      unhandled "undefined"/"[object Object]" rendered as literal text.

## 7. After QA — reset before the real demo

Whatever you did to Vikram Rao's two records during this QA pass (injecting
vitals, escalating, etc.), reset him to a clean baseline afterward so the
real demo starts fresh:
```
cd common_db_main_latest/sabari_project/backend
py -3 seed_demo_arc_patient.py
```

Report back: a plain list of anything that didn't match its checkbox above,
with a screenshot or console error text if available. Anything not listed
here that looks broken, inconsistent, or visually off is also worth flagging
even if it's not an explicit checklist item — the goal is nothing surprising
happens live tomorrow.
