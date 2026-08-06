# Comprehensive Manual Test Plan
## EWS-CDS + Discharge AI — Pilot Readiness
**System:** `common_db_main_latest`  
**Standard:** NABH-grade, zero-tolerance pilot deploy  
**Date:** 2026-06-26  
**Tester instruction:** Run every test case in sequence. Record PASS / FAIL / BLOCKED. If a case fails, note the exact screen state, error message, and timestamp.

---

## Setup Checklist (Before Testing)
- [ ] Sabari backend running on `localhost:8000` (FastAPI)
- [ ] Ashmit backend running on `localhost:5180` (Doctor Portal)
- [ ] Cloud SQL connected (check `GET /api/ward-data` returns patients)
- [ ] At least 2 active patients in the database — one CCU, one General Ward
- [ ] At least one patient with vitals recorded in the last 2 hours
- [ ] At least one patient with NO vitals (to test empty state)
- [ ] Auth users exist: ward nurse, charge nurse, resident doctor

---

## MODULE 1 — Authentication

### TC-01: Ward Nurse Login
**Precondition:** Sabari frontend loaded at `localhost:8000`  
**Steps:**
1. Open browser → `http://localhost:8000`
2. Select role: "Bedside Nurse" or "Ward Nurse"
3. Enter valid credentials
4. Click Login

**Expected Result:**
- Redirects to NEWS2 Dashboard (N1 screen)
- Top bar shows logged-in nurse name (not "Nurse Rekha Devi")
- Role chip shows correct role

**Fail Indicators:** Page stays on login / "Nurse Rekha Devi" appears in topbar / blank screen

---

### TC-02: Charge Nurse Login
**Steps:** Same as TC-01 but select "Charge Nurse" role

**Expected Result:**
- Redirects to Escalation Queue (N5 screen)
- Sidebar shows Charge Nurse–specific menu items

---

### TC-03: Resident Doctor Login (Ashmit Portal)
**Steps:**
1. Open `http://localhost:5180`
2. Login with doctor credentials

**Expected Result:**
- Redirects to Doctor Queue screen
- Patient cards visible (if any are in "Awaiting Review" status)

---

## MODULE 2 — Ward Nurse EWS Dashboard (N1 Screen)

### TC-04: Dashboard Loads — Shell First, Data Second
**Steps:**
1. Login as Ward Nurse
2. Immediately watch the screen on first load

**Expected Result:**
- Within 300ms: HTML shell (topbar, sidebar, table header) is visible
- Skeleton loading rows animate in the table body
- Within 3s: Real patient data populates the table
- No full-page blank white screen at any point

**Fail Indicators:** Page is blank for >1s / Data appears without skeleton / Page hangs

---

### TC-05: Dashboard Shows Correct Patient Count and NEWS2 Scores
**Steps:**
1. Load the NEWS2 Dashboard (N1)
2. Count the patient rows

**Expected Result:**
- Exactly the number of active patients in the database appear
- Each row shows: Patient code, Name, Ward, NEWS2 score, EWS Reason, Status, Due label
- No blank/empty rows

**Fail Indicators:** Extra blank rows / patient count mismatch / "undefined" text visible

---

### TC-06: Empty Vitals Patient — Graceful Handling
**Precondition:** At least one patient exists with zero vitals records  
**Steps:**
1. Load the NEWS2 Dashboard

**Expected Result:**
- Patient with no vitals appears with status "Syncing data…" or is hidden entirely
- NOT a blank row with dashes for all vitals
- NO JavaScript errors in browser console

**Fail Indicators:** Blank row with all "--" values / console errors / `NaN` visible

---

### TC-07: Scrollability on Small Screen
**Steps:**
1. Load the NEWS2 Dashboard with 8+ patients
2. Resize browser window to 1024×600 (simulate small ward monitor)
3. Try to scroll down in the patient table

**Expected Result:**
- Scrollbar appears in the `#main` content area
- All patients are reachable by scrolling
- Topbar and sidebar remain fixed
- No content is clipped/hidden below the fold

**Fail Indicators:** Scrollbar missing / patients below fold are unreachable / layout breaks

---

### TC-08: Scrollability When Window Is Minimized Then Restored
**Steps:**
1. Load the NEWS2 Dashboard
2. Minimize the browser window
3. Restore the window
4. Attempt to scroll the patient list

**Expected Result:** Scroll works normally after restore — layout re-renders correctly

---

### TC-09: NEWS2 Status Color Coding
**Steps:**
1. Find a patient with NEWS2 ≥ 7 on the dashboard

**Expected Result:**
- Row background is red-tinted (`row-crit` class)
- NEWS2 score badge is red
- EWS Reason shows "Escalate now"

---

### TC-10: Dashboard Auto-Refresh After Vitals Entry
**Precondition:** Patient has NEWS2 = 3 currently  
**Steps:**
1. Open Patient Detail (N1b) for that patient
2. Click "Enter Vitals"
3. Enter values that will produce NEWS2 = 8 (e.g., SpO2 = 85%, RR = 30)
4. Submit vitals
5. Press "Back to Dashboard" (N1)
6. Observe the patient's NEWS2 score on the dashboard

**Expected Result:**
- NEWS2 score updates from 3 → 8 within one refresh cycle (≤ 20 seconds)
- Row background changes to red
- Status changes to "Escalate now"

**Fail Indicators:** Score still shows 3 / requires manual page refresh to update

---

## MODULE 3 — Patient Detail & Vitals Entry (N1b, N_vitals)

### TC-11: Patient Detail Screen Loads Correctly
**Steps:**
1. Click on any patient row in the dashboard
2. Observe the N1b screen

**Expected Result:**
- Patient name, patient code, ward, bed, diagnosis visible
- Latest vitals displayed with correct values
- NEWS2 score shown prominently
- "Enter Vitals", "Initiate Discharge", "Escalate" buttons present

---

### TC-12: Vitals Entry — All Fields Validation
**Steps:**
1. Navigate to Enter Vitals (N_vitals) for any patient
2. Try submitting with blank fields → should block
3. Enter SpO2 = 150 → should block with error
4. Enter RR = 2 → should block with error
5. Enter valid values: SpO2=96, RR=18, HR=80, SBP=120, DBP=78, Temp=37.0
6. Submit

**Expected Result:**
- Steps 2-4: Specific validation error messages shown, form not submitted
- Step 6: "Vitals saved — NEWS2 score: X" confirmation shown
- After 2 seconds: Auto-navigates back to Patient Detail (N1b)
- N1b shows the new vitals

---

### TC-13: Vitals Entry — Stale Warning Shown
**Precondition:** Patient's last vitals were entered >45 minutes ago  
**Steps:**
1. Open Enter Vitals for that patient

**Expected Result:**
- Yellow warning banner: "Last vitals recorded XX min ago — entry required."
- Banner shows correct number of minutes

---

### TC-14: Vitals Entry — Submit Button Disables During Save
**Steps:**
1. Fill in valid vitals
2. Click "Submit Vitals" quickly twice

**Expected Result:**
- Button text changes to "Saving…" after first click
- Button is disabled to prevent double-submission
- Only ONE vitals record is created in the database

---

## MODULE 4 — Escalation Flow (N2, N3, N4)

### TC-15: Escalation Form — Nurse Name Comes from Login
**Steps:**
1. Login as "Nurse Priya Mehta" (or any non-"Rekha Devi" user)
2. Navigate to Escalation form (N2) for a high-NEWS2 patient

**Expected Result:**
- The "Escalated By" field shows the actual logged-in nurse's name
- NOT "Nurse Rekha Devi"

---

### TC-16: Escalation Form — Observation Field Is Blank
**Steps:**
1. Open the Escalation form (N2)

**Expected Result:**
- "Clinical Observations" textarea is EMPTY (shows placeholder text only)
- NOT pre-filled with "Patient increasingly short of breath…"

---

### TC-17: Submit Escalation → N3 Shows Real Data
**Steps:**
1. Fill in escalation form (N2) with real observations
2. Select escalation level: "Nurse-to-Doctor"
3. Click "Submit Escalation →"

**Expected Result:**
- Success navigates to N3 (Post-Escalation screen)
- N3 shows: correct patient name, correct NEWS2 score, actual escalation timestamp, actual attending name
- Reference ID is "ESC-XXXX" format

**Fail Indicators:** N3 shows hardcoded "14:28", wrong patient name, "null" anywhere

---

### TC-18: Escalation Recorded in Charge Nurse Queue (N5)
**Steps:**
1. Complete TC-17 (submit an escalation)
2. Login as Charge Nurse or navigate to N5

**Expected Result:**
- The escalation appears in the queue with correct patient name, NEWS2, level, nurse name
- SLA timer is ticking (shows "X m to SLA")

---

### TC-19: SLA Breach Detection
**Precondition:** An escalation exists that was submitted >15 minutes ago without acknowledgement  
**Steps:**
1. Open Charge Nurse Queue (N5)

**Expected Result:**
- That escalation row has red background (`row-crit`)
- Shows "⏱ SLA BREACHED" badge
- Shows "X m unattended" in the SLA column

---

### TC-20: Re-escalation Workflow
**Steps:**
1. On N5, find an active escalation
2. Click "Re-escalate ↑"

**Expected Result:**
- Confirmation alert: "Re-escalated to [next level]"
- Escalation level changes (e.g., "Nurse-to-Doctor" → "Attending" → "Consultant")
- Re-escalation timestamp recorded

---

## MODULE 5 — CCU → General Ward Step-Down Transfer

### TC-21: Transfer Eligibility Check
**Precondition:** A CCU patient with NEWS2 ≤ 2 sustained for 6+ readings  
**Steps:**
1. Open Patient Detail (N1b) for a CCU patient
2. Click "CCU → GW Transfer"

**Expected Result:**
- Step-down eligibility screen loads
- Green "✓ Met" badges for: NEWS2 ≤ 2 sustained, No active escalation, Haemodynamically stable
- "Submit to Head Nurse →" button is enabled (not greyed out)

---

### TC-22: Transfer Eligibility — Ineligible Patient
**Precondition:** A CCU patient with NEWS2 = 8  
**Steps:**
1. Open the CCU → GW Transfer screen for that patient

**Expected Result:**
- "Submit to Head Nurse →" button is DISABLED
- Warning banner: "⚠️ Not all step-down criteria are met"
- Criteria rows show red "✗ Not met" for NEWS2

---

### TC-23: Submit Transfer Recommendation
**Precondition:** Eligible CCU patient from TC-21  
**Steps:**
1. Fill in target ward and clinical rationale
2. Click "Submit to Head Nurse →"

**Expected Result:**
- Screen shows "✅ Step-down recommendation submitted — Head Nurse review pending"
- Recommendation appears in Charge Nurse Queue (N5) under "CCU → GW Transfer Approvals"

---

### TC-24: Charge Nurse Approves Transfer
**Steps:**
1. Login as Charge Nurse → Navigate to N5
2. Find the pending transfer in the approval section
3. Click "Approve →"

**Expected Result:**
- Alert: "Transfer approved — patient moved to General Ward"
- Patient's `ward_location` changes from "CCU" to "GENERAL_WARD"
- Patient appears in the General Ward view instead of CCU view
- Dashboard row shows "GW" location tag instead of "CCU"

---

### TC-25: Patient Cannot Be Transferred Twice
**Steps:**
1. Complete TC-23 (submit recommendation)
2. Navigate back to the same patient's Transfer screen

**Expected Result:**
- "Submitted ✓" state shown — recommendation already submitted
- Form is NOT shown again
- "Withdraw Recommendation" button is present

---

## MODULE 6 — Discharge Initiation (GW Nurse → Resident Doctor)

### TC-26: Initiate Discharge — Patient Name Preserved
**This is the PRIMARY bug test. Run this carefully.**

**Precondition:** Patient "Arjun Singh" (or any real patient) in General Ward  
**Steps:**
1. Login as GW Nurse
2. Open Patient Detail for "Arjun Singh"
3. Click "Initiate Discharge"
4. On the n_discharge confirmation screen, note the patient name shown
5. Click "Open Doctor Portal →"
6. In the Doctor Portal (localhost:5180), observe the queue

**Expected Result — Step 4:** Confirmation shows "Arjun Singh" (not "Patient" or blank)  
**Expected Result — Step 6:** Doctor queue shows a card with "Arjun Singh" or his display_id  
**Expected Result:** Patient name is IDENTICAL in both systems

**Fail Indicators:**
- n_discharge shows "Patient" instead of real name
- Doctor queue card shows blank name or different name
- `enc.patient` is null in browser DevTools network response

---

### TC-27: Discharge Confirmation Screen Shows All 4 Steps
**Steps:**
1. Complete discharge initiation (TC-26 steps 1-4)

**Expected Result:**
- 4-step workflow table visible: Ward Nurse (✓), Resident Doctor, Attending Physician, Billing
- Step 1 marked as "Discharge initiated ✓"

---

### TC-28: Initiated Discharge Appears in Resident's Queue
**Steps:**
1. Complete TC-26
2. Login to Doctor Portal (localhost:5180)
3. Check the doctor queue

**Expected Result:**
- A new encounter card appears for the patient
- Status: "Ready for Review" or "Awaiting Generation"
- Timestamp is recent (within 1 minute of discharge initiation)

---

## MODULE 7 — Doctor Queue & Discharge Summary Review

### TC-29: Doctor Queue Loads with Skeleton
**Steps:**
1. Login to Doctor Portal
2. Watch the queue screen load

**Expected Result:**
- Within 300ms: Skeleton loading cards visible
- Within 5s: Real encounter cards populate
- No blank white screen

---

### TC-30: Doctor Queue Shows Patient Display ID
**Steps:**
1. View the doctor queue with at least one encounter

**Expected Result:**
- Each card shows a patient ID (e.g., "PT-26-0042")
- Status pill is correct color: purple for "Ready for Review", green for "Signed Off"
- "Review Summary" button is active when summary is ready

---

### TC-31: Live Poll — New Patient Appears Without Refresh
**Steps:**
1. Keep doctor queue open in one tab
2. In another tab/window, initiate a discharge for a new patient
3. Wait up to 10 seconds on the doctor queue tab

**Expected Result:**
- New encounter card appears automatically (live poll runs every 8s)
- No manual page refresh needed

---

### TC-32: Doctor Reviews Summary
**Precondition:** An encounter with status "Awaiting Review" and a generated summary exists  
**Steps:**
1. Click "Review Summary" on a card
2. Navigate through the review screen

**Expected Result:**
- Summary content renders correctly
- Patient ID in review header matches the card
- Sign Off and Revision options present

---

## MODULE 8 — Cross-Cutting & Edge Cases

### TC-33: Browser Back Button Behavior
**Steps:**
1. Navigate: N1 → N1b (patient detail) → N2 (escalation) → Press browser Back button

**Expected Result:**
- App returns to N1b (not N1 or a blank screen)
- Patient data is still loaded
- No JavaScript errors in console

---

### TC-34: Concurrent Users — Cache Invalidation
**Precondition:** Two browser tabs open — one as Ward Nurse, one as Charge Nurse  
**Steps:**
1. Tab 1 (Ward Nurse): Submit vitals for Patient A (high NEWS2)
2. Tab 2 (Charge Nurse): Navigate to N5 Escalation Queue within 30 seconds

**Expected Result:**
- Tab 2 shows updated patient status reflecting new vitals
- Cache is not serving stale data from before the vitals POST

---

### TC-35: API Down — Graceful Error Handling
**Steps:**
1. Stop the Sabari backend (`Ctrl+C`)
2. Reload the NEWS2 Dashboard in the browser

**Expected Result:**
- Error message is shown (not a blank page or `undefined` crash)
- Error explains the backend is unreachable
- Retry button or instructions are present

---

## Test Results Matrix

| TC | Test Case | Status | Notes | Tester | Date |
|---|---|---|---|---|---|
| TC-01 | Ward Nurse Login | | | | |
| TC-02 | Charge Nurse Login | | | | |
| TC-03 | Doctor Login | | | | |
| TC-04 | Shell-first async load | | | | |
| TC-05 | Correct patient count | | | | |
| TC-06 | Empty vitals graceful | | | | |
| TC-07 | Scroll on small screen | | | | |
| TC-08 | Scroll after minimize | | | | |
| TC-09 | NEWS2 color coding | | | | |
| TC-10 | Auto-refresh after vitals | | | | |
| TC-11 | Patient detail loads | | | | |
| TC-12 | Vitals validation | | | | |
| TC-13 | Stale vitals warning | | | | |
| TC-14 | Double-submit blocked | | | | |
| TC-15 | Nurse name from login | | | | |
| TC-16 | Obs field blank | | | | |
| TC-17 | Submit escalation → N3 real data | | | | |
| TC-18 | Escalation in charge queue | | | | |
| TC-19 | SLA breach detection | | | | |
| TC-20 | Re-escalation | | | | |
| TC-21 | Transfer eligibility — eligible | | | | |
| TC-22 | Transfer eligibility — ineligible | | | | |
| TC-23 | Submit transfer recommendation | | | | |
| TC-24 | Charge nurse approves transfer | | | | |
| TC-25 | No duplicate transfer | | | | |
| TC-26 | **Discharge — patient name preserved** | | | | |
| TC-27 | Discharge 4-step workflow shown | | | | |
| TC-28 | Initiated discharge in doctor queue | | | | |
| TC-29 | Doctor queue skeleton load | | | | |
| TC-30 | Doctor queue shows display_id | | | | |
| TC-31 | Live poll auto-updates | | | | |
| TC-32 | Doctor reviews summary | | | | |
| TC-33 | Browser back button | | | | |
| TC-34 | Cache invalidation concurrent | | | | |
| TC-35 | API down graceful error | | | | |

---

## Priority Order for Manual Testing

Run **TC-26 first** — it validates the most critical reported bug (patient identity).  
Then **TC-07 + TC-08** — the scroll bug visible immediately.  
Then **TC-04** — async load behavior.  
Then **TC-15 + TC-16 + TC-17** — escalation flow with real data.  
Then all remaining TCs in order.

---

## Bug-to-TestCase Cross Reference

| Bug ID | Bug Description | Validated by TC |
|---|---|---|
| BUG-01 | Patient name lost at discharge handoff | TC-26, TC-27, TC-28 |
| BUG-02 | Scroll breaks on small screen | TC-07, TC-08 |
| BUG-03 | N4/N6 hardcoded data | TC-17, TC-18 |
| BUG-04 | Doctor queue enc.patient = null | TC-26, TC-30 |
| BUG-05 | Duplicate EscalationCreate / wrong name | TC-15 |
| BUG-06 | Hardcoded attending doctors | TC-17 |
| BUG-07 | Ward cache not cleared after vitals | TC-10 |
| BUG-08 | Pre-filled observation text | TC-16 |
| BUG-09 | Doctor Acknowledges no API call | TC-17 (check escalation status after) |
| BUG-10 | is_valid() blocks zero vitals | TC-06 |
| BUG-11 | No patient name in doctor queue | TC-30 |
| BUG-12 | No "just admitted" vs "overdue" distinction | TC-06 |
| BUG-13 | _dischargePatient not cleared | TC-26 (run twice for different patients) |
| BUG-15 | Threshold Config save no handler | Open N5b, click Save |
