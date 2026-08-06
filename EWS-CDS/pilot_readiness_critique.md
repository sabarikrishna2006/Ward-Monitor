# Pilot Readiness Deep Critique — `common_db_main_latest`
**Reviewer:** Lead Healthcare Systems Engineer (10+ yrs Indian hospital deployments)  
**Scope:** Every file in `sabari_project/` (EWS) + `frontend/screens/doctor-queue.js` (Discharge AI)  
**Standard:** NABH-grade, zero-tolerance, pilot-deploy ready  
**Date:** 2026-06-26

---

## 🔴 CRITICAL BUGS (Demo-breaking / Clinically unsafe)

---

### BUG-01 — Patient Identity Breaks at the GW Nurse → Resident Handoff

**Severity:** CRITICAL — this is the bug you described. **Patient name changes at the discharge bridge.**

**Location:** [`app.js` L1608–1648](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/sabari_project/app.js#L1608-L1648) and [`backend/main.py` L1291–1327](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/sabari_project/backend/main.py#L1291-L1327)

**Root Cause (confirmed by code):**

1. The GW nurse presses "Initiate Discharge" on `n1b` (patient detail). At this point `APP._dischargePatient` holds the patient object as loaded by Sabari's backend — using `patient_name` from the `active_patients` table (e.g. `"Priya Sharma"`).

2. The `n_discharge` screen (L1645) opens the Doctor Portal using:
   ```js
   window.open(`${residentBase}/upload.html?hadm_id=${dp.id}`, '_blank')
   ```
   It passes **only `hadm_id`** — no `patient_name`, no `uhid`.

3. Ashmit's `doctor-queue.js` fetches encounters via `fetchEncounters()` and displays them using `fmtPid(enc.hadm_id, enc.display_id)` — i.e., **the encounter's display_id**, not the patient name at all. The patient name on the review card comes from `enc.patient` field (line 53 sets it to `null`).

4. **Result:** The doctor's queue shows patient ID correctly, but `enc.patient` is `null`. Anything that tries to render the patient's full name (e.g. in the amber re-generation toast: `patName: null` at L368, L429) shows blank or `null`.

**The exact data flow gap:**
```
Sabari DB:  patient_name = "Priya Sharma"   (active_patients / ap_admissions)
                              ↓
initiate-discharge API:  Creates/updates app_encounters — but DOES NOT write patient name into app_encounters
                              ↓
fetchEncounters():  Returns enc with enc.patient = null (never populated)
                              ↓
Doctor review screen:  Patient name is blank / null
```

**Fix required:**

In `backend/main.py` → `initiate_discharge()`, when creating/updating the `app_encounters` row, also write `patient_name` from the `hospital_core.patients` table (via the `admissions` bridge):

```python
# After fetching patient, also resolve UHID → full_name from hospital_core
name_row = db.execute(sql_text("""
    SELECT hcp.full_name FROM hospital_core.admissions hca
    JOIN hospital_core.patients hcp ON hca.uhid = hcp.uhid
    WHERE hca.hadm_id = :h LIMIT 1
"""), {"h": subject_id}).fetchone()
patient_full_name = name_row[0] if name_row else (patient.patient_name or "Unknown")

# Then include it in the INSERT / UPDATE of app_encounters
```

Also: `fetchEncounters` in Ashmit's backend must return `patient_name` in the encounter payload, and `doctor-queue.js` must set `enc.patient = { full_name: enc.patient_name }`.

---

### BUG-02 — Scrollability Breaks When Browser Window Is Minimised / Small

**Severity:** CRITICAL — nurses use 1366×768 ward monitors; this makes the dashboard completely unusable.

**Location:** [`styles.css` L15](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/sabari_project/styles.css#L15)

**Root Cause:**
```css
html, body { height: 100%; overflow: hidden; }
```

The `overflow: hidden` on `body` globally **removes the browser scrollbar**. The content area scrolls via `#main { overflow-y: auto }` — but only as long as the fixed layout computes the right heights. When the window is too small (e.g. during a Teams call), the layout breaks because the fixed positioned elements overlap.

**Secondary issue:** The `#layout` is `position: fixed` (L41–43). Combined with `overflow: hidden` on body, when the patient table grows beyond the available height and `#main`'s computed height is wrong (which happens on some browsers when the window is resized while a fixed layout is in use), the table rows become invisible/unreachable.

**Fix:**
```css
/* Replace L15 */
html { height: 100%; }
body { min-height: 100%; overflow-y: auto; }
/* And ensure #layout fills but does not overflow-hide */
#layout { position: fixed; overflow: hidden; } /* keep as-is but remove from body */
```

For full robustness, the `#main` content pane should have `min-height: 0` on its container and `flex: 1 1 0%` — not `flex: 1` which resolves to `flex: 1 1 auto` and can cause overflow.

---

### BUG-03 — `n4` (Escalation Status Log) and `n6` (Shift Handoff) Use **Hardcoded Demo Data**

**Severity:** CRITICAL — a stakeholder who clicks through the escalation flow will see dummy patient names `"PT-24-0092"`, hardcoded timestamps `"02 Jun 2026"`, hardcoded nurse names `"Rekha Devi"` regardless of who is logged in or which patient is selected.

**Location:** [`app.js` L988–1022](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/sabari_project/app.js#L988-L1022), [`app.js` L1187–1254](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/sabari_project/app.js#L1187-L1254)

**Evidence:**
```js
// N4 — Line 991: hardcoded patient ID
<h1 class="sh-title">Escalation Status — PT-24-0092</h1>

// N4 timeline — Lines 998-1005: hardcoded timestamps and names
['14:28','Vitals Recorded', 'NEWS2: 9. SpO₂ 91%, ...Nurse Rekha Devi', ''],
// ...
['02 Jun 2026'] // hardcoded date

// N6 handoff — Line 1197:
<input class="fi" value="Nurse Rekha Devi" readonly>
// N6b — Line 1247:
<td class="bold">Nurse Rekha Devi</td>
```

**Impact:** During a demo, a stakeholder will escalate patient "Arjun Singh" and then see the escalation status screen show "PT-24-0092 Priya Sharma" — a completely different patient. This will immediately destroy credibility.

**Fix:** Both screens must read from `APP.data.lastEscalation` (already populated by the real API after N2 submit) and `APP.user` for the nurse name. The N4 screen must also load escalation history from `/api/escalations/{id}` dynamically. N6 nurse names must come from `APP.user.name`.

---

### BUG-04 — `doctor-queue.js` Patient Cards Show No Patient Name

**Severity:** CRITICAL  
**Location:** [`doctor-queue.js` L51–53](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/frontend/screens/doctor-queue.js#L51-L53)

**Evidence:**
```js
const withSummaries = await Promise.all(encs.map(async e => {
  const sum = await fetchSummary(e.id).catch(() => null);
  return { ...e, admission: null, patient: null, summary: sum || null }; // ← patient always null
}));
```

`enc.patient` is **explicitly set to `null`** and never populated. The card renders `fmtPid(enc.hadm_id, enc.display_id)` for the patient identity, which shows an ID code — but the full patient name is absent from the card. For NABH audit, doctor review must show full patient name alongside HADM ID.

**Fix:** After fetching the encounter list, also fetch patient name via `hospital_core.admissions → hospital_core.patients.full_name` and inject it into `enc.patient`. This can be a lightweight second query piggybacked on the encounter list API response.

---

## 🟠 HIGH SEVERITY (Will cause issues in first 30 minutes of demo)

---

### BUG-05 — `EscalationCreate` Pydantic Model Declared Twice

**Severity:** HIGH — Python runtime error risk (duplicate class name overrides the first one silently)

**Location:** [`backend/main.py` L37–43](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/sabari_project/backend/main.py#L37-L43) and [`backend/main.py` L284–290](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/sabari_project/backend/main.py#L284-L290)

**Evidence:**
```python
# Line 37 — First definition (missing escalatedBy default)
class EscalationCreate(BaseModel):
    patientId: int
    level: str
    attending: str
    observations: str
    interventions: str
    escalatedBy: str          # No default — required

# Line 284 — Second definition (has default, silently overrides first)
class EscalationCreate(BaseModel):
    ...
    escalatedBy: str = "Nurse Rekha Devi"   # Hardcoded default name!
```

The **second class silently replaces the first** in Python. The API now uses "Nurse Rekha Devi" as default escalator name for ALL escalations if `escalatedBy` is not sent — meaning the NABH audit trail would record the wrong nurse name.

**Fix:** Delete the first `EscalationCreate` definition (lines 37–43). Fix the remaining default:
```python
escalatedBy: str = ""  # Empty default — frontend must always send real name
```

---

### BUG-06 — Attending Physician Dropdown Is Completely Hardcoded

**Severity:** HIGH — Clinicians and stakeholders will immediately notice "Dr. Anand Sharma" showing for every patient in every hospital

**Location:** [`app.js` L927–931](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/sabari_project/app.js#L927-L931)

```html
<select class="fi" id="esc-attending">
  <option value="Dr. Anand Sharma">Dr. Anand Sharma (On-call, Cardiology)</option>
  <option value="Dr. Priya Mehta">Dr. Priya Mehta</option>
  <option value="Dr. Deepak Rao">Dr. Deepak Rao</option>
</select>
```

These are fake names. The app has a real `app_users` table (AUTH). The escalation form must pull doctors from the database.

**Fix:** Add an `/api/on-call-doctors` endpoint (or reuse app_users filtered by role `doctor`/`consultant`). Populate the dropdown on N2 screen load via async fetch.

---

### BUG-07 — `ward_cache` TTL Is 20 Seconds But Dashboard Has No Polling

**Severity:** HIGH (data staleness)

**Location:** [`backend/main.py` L434](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/sabari_project/backend/main.py#L434)

The ward cache TTL is 20 seconds. The frontend has no polling loop for the N1 dashboard. A nurse will load the dashboard, walk to a patient bed, enter vitals on the N_vitals screen, submit them, then press "Back to Dashboard" (nav to n1). The ward data will be served **from cache** and still show the old NEWS2 score — because the cache is not cleared on vitals POST.

**Evidence:** `submitVitals()` in `app.js` L1504–1531 — after a successful vitals POST, it calls `nav('n1b', APP.currentPatientId)` (back to patient detail, not dashboard). But `_ward_cache` is only cleared in `sync_vitals_now()` (L1286) and `initiate_discharge()` (L1322), NOT in `/api/patients/{id}/vitals` POST.

**Fix:** In `add_vitals()` backend endpoint (L954–989), add `_ward_cache.clear()` after commit.

---

### BUG-08 — Escalation Form's Clinical Observations Field Has Hardcoded Text

**Severity:** HIGH — looks unprofessional in demo

**Location:** [`app.js` L934](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/sabari_project/app.js#L934)

```html
<textarea class="fi" id="esc-obs" rows="3">Patient increasingly short of breath, oxygen requirement escalating. Responsive to voice but lethargic.</textarea>
```

The observation textarea is pre-filled with generic demo text. A nurse during a live demo will see this text already populated — it will look like the system auto-fabricated clinical notes. **In a clinical system, pre-filled observations are a patient safety risk.**

**Fix:** Clear the default text. Use a `placeholder` attribute instead so the field appears blank but guided.

---

### BUG-09 — `n4` (Status Log) "Doctor Acknowledges" Button Navigates to `n4b` Without API Call

**Severity:** HIGH — no data is persisted when doctor acknowledges; NABH audit trail is broken

**Location:** [`app.js` L993](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/sabari_project/app.js#L993)

```html
<button class="btn btn-pri btn-sm" onclick="nav('n4b')">Doctor Acknowledges →</button>
```

This button navigates directly to the "resolution" screen. The escalation acknowledgement is never written to the `escalations` table (no PATCH to `/api/escalations/{id}/resolve` or `/acknowledge`). The NABH audit trail will show the escalation as perpetually "active".

**Fix:** Add an intermediate async call:
```js
async function doctorAcknowledge(escId) {
  await fetch(`/api/escalations/${escId}/resolve`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ resolvedBy: APP.user?.name || 'Doctor', notes: '' })
  });
  nav('n4b');
}
```

---

## 🟡 MEDIUM SEVERITY (Should fix before pilot; manageable in demo with workaround)

---

### BUG-10 — `isNaN` Check in `is_valid()` Blocks Zero Vital Values

**Severity:** MEDIUM — physiologically legitimate zero values are silently dropped

**Location:** [`backend/main.py` L45–50](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/sabari_project/backend/main.py#L45-L50)

```python
def is_valid(val):
    if val is None: return False
    if isinstance(val, (float, int)) and (math.isnan(val) or val == 0):
        return False
    return True
```

`val == 0` blocks `temperature = 0` (theoretically impossible) but also blocks SpO2 = 0 (a patient in arrest). More importantly, **in MIMIC data, some legitimate readings are 0 in some columns due to nullification**. This silently drops readings and can make a deteriorating patient's card appear to have no vitals. Correct check should be `val == 0 and val is not temperature` or better — validate contextually.

**Fix:** Remove the `val == 0` check from the generic `is_valid()`. Instead, apply per-column range validation at the NEWS2 score calculation level.

---

### BUG-11 — Doctor Queue Cards Show HADM ID, Not Patient Name

**Severity:** MEDIUM  
**Location:** [`doctor-queue.js` L197](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/frontend/screens/doctor-queue.js#L197)

```js
<div style="font-weight:800;font-size:18px">
  ${fmtPid(enc.hadm_id, enc.display_id)}
</div>
```

The patient card in the doctor queue shows only the encounter ID (e.g. `PT-26-0042`). There is no patient name visible. Doctors in Indian hospitals look for patient names + age + ward, not MIMIC IDs. This will confuse clinicians during the demo.

**Fix:** After resolving BUG-01 (patient name propagation), add below the ID:
```js
<div style="font-size:13px;color:#6B7280;margin-top:4px">
  ${enc.patient?.full_name || ''} · ${enc.patient?.age ? enc.patient.age + 'y' : ''}
</div>
```

---

### BUG-12 — NEWS2 Dashboard Card Filter for Empty Vitals Is Incomplete

**Severity:** MEDIUM  
**Location:** [`backend/main.py` L596–614](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/sabari_project/backend/main.py#L596-L614)

The `is_overdue` logic defaults to `status = 'stale'` for patients with no vitals and shows them on the ward board. However, the frontend `SCREENS.n1` renders these as stale rows — a nurse cannot tell the difference between "patient was just admitted and has no vitals yet" vs "patient vitals are overdue by 8 hours." 

**Fix:** Add a `no_vitals_yet` flag in the API response when `vitals_history` is empty. Display a distinct "Awaiting first vitals" badge instead of "Overdue" for newly admitted patients.

---

### BUG-13 — `_dischargePatient` State Is Never Reset After Navigation

**Severity:** MEDIUM — stale state if nurse goes back and initiates discharge for a different patient

**Location:** [`app.js` L1607–1649](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/sabari_project/app.js#L1607-L1649)

`APP._dischargePatient` is set when the nurse presses "Initiate Discharge" somewhere in the `n1b` flow, but it is **never cleared**. If a nurse initiates discharge for patient A, then navigates to patient B and presses Back, `n_discharge` would show patient A's name for patient B's discharge.

**Fix:** Clear `APP._dischargePatient = null` whenever `nav('n1')` or `nav('n1b', pid)` is called.

---

### BUG-14 — Ward Cache Is Shared Across ALL Users (No Per-Ward Segmentation)

**Severity:** MEDIUM  
**Location:** [`backend/main.py` L433–434](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/sabari_project/backend/main.py#L433-L434)

```python
_ward_cache: dict = {}   # key: (ward, location) → {ts, data}
```

The cache is a **global Python dict**, which means it is shared across all concurrent users and **across all hospitals** if the system is ever multi-tenanted. In a demo with two concurrent browser tabs (nurse + head nurse), one user's cache flush propagates to the other. This is currently safe for a single hospital demo but is an architectural smell.

---

### BUG-15 — Threshold Config Screen (N5b) Has No Save API Call

**Severity:** MEDIUM  
**Location:** [`app.js` L1183](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/sabari_project/app.js#L1183)

```html
<button class="btn btn-pri">Save & Sign Off</button>
```

The "Save & Sign Off" button has no `onclick` handler. Pressing it does nothing. The threshold configuration screen is purely visual. For a demo with a medical director, this will immediately be probed.

**Fix:** Either wire it to an API endpoint or add a visible "(Demo Mode — read-only)" indicator to set expectations correctly.

---

## 🟢 LOW / UX SEVERITY (Clean up before pilot)

---

### BUG-16 — Vitals Range Validations on SpO2 Allow Physiologically Impossible Values

**Location:** [`app.js` L1494](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/sabari_project/app.js#L1494)

```js
if (spo2 < 70 || spo2 > 100) { alert('SpO2 must be 70-100%'); return; }
```

SpO2 below 70% means the patient is in extremis/PEA arrest. In NABH-grade systems, SpO2 < 80% should trigger a warning before submission (not block it) because the nurse may legitimately need to record it. Blocking at 70 is too low — consider a "Are you sure? This is a critically low value" confirmation modal for values < 85%.

---

### BUG-17 — App.js `n4` and `n6` Static Nurse Names Should Pull from `APP.user`

**Location:** [`app.js` L1196–1199](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/sabari_project/app.js#L1196-L1199)

Every reference to `"Nurse Rekha Devi"` should be replaced with `APP.user ? APP.user.name : 'Nurse'`. This ensures the logged-in nurse's name appears in the handoff form and confirmation. Currently there are **4 hardcoded occurrences** in N6/N6b.

---

### BUG-18 — `n_discharge` Opens Doctor Portal URL Using `location.hostname`

**Location:** [`app.js` L1610](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/sabari_project/app.js#L1610)

```js
const residentBase = `http://${location.hostname}:5180`;
```

This assumes the Doctor Portal (Ashmit's system) is always on port 5180 on the same host. If the demo uses a deployed server (not localhost), or if the ports are different, the "Open Doctor Portal →" button will silently open a broken URL. This should be an environment variable / config constant, not `location.hostname`.

---

### BUG-19 — `is_stale` Threshold Is Hardcoded to 45 Minutes in Vitals API

**Location:** [`backend/main.py` L1002](file:///e:/IP_EarlyWarning/EWS-CDS/common_db_main_latest/sabari_project/backend/main.py#L1002)

```python
is_stale = stale_mins > 45
```

The ward monitoring cadence (computed by `monitoring_plan()`) can be as low as 30 minutes for NEWS2 ≥ 7 patients. But `is_stale` in the single-patient vitals detail endpoint is hardcoded to 45 minutes, regardless of the patient's NEWS2 score. A critical patient's last vitals recorded 40 minutes ago will show as "fresh" — when by NEWS2 protocol they should have been re-measured 10 minutes ago.

---

## Summary Table

| ID | Severity | Description | File | Line |
|---|---|---|---|---|
| BUG-01 | 🔴 CRITICAL | Patient name drops to null at GW→Doctor handoff | `app.js`, `backend/main.py` | 1608, 1291 |
| BUG-02 | 🔴 CRITICAL | Body overflow:hidden breaks scroll on small screens | `styles.css` | 15 |
| BUG-03 | 🔴 CRITICAL | N4 status log and N6 handoff are fully hardcoded | `app.js` | 988, 1187 |
| BUG-04 | 🔴 CRITICAL | Doctor queue cards always have `enc.patient = null` | `doctor-queue.js` | 53 |
| BUG-05 | 🟠 HIGH | Duplicate `EscalationCreate` class, wrong default name | `backend/main.py` | 37, 284 |
| BUG-06 | 🟠 HIGH | Attending dropdown is hardcoded fake names | `app.js` | 927 |
| BUG-07 | 🟠 HIGH | Vitals POST does not clear ward cache → stale NEWS2 shown | `backend/main.py` | 954 |
| BUG-08 | 🟠 HIGH | Escalation obs textarea has fake pre-filled text | `app.js` | 934 |
| BUG-09 | 🟠 HIGH | "Doctor Acknowledges" button makes no API call | `app.js` | 993 |
| BUG-10 | 🟡 MEDIUM | `is_valid(0)` returns False — blocks zero vital readings | `backend/main.py` | 48 |
| BUG-11 | 🟡 MEDIUM | Doctor queue shows HADM ID only, no patient name | `doctor-queue.js` | 197 |
| BUG-12 | 🟡 MEDIUM | No distinction between "just admitted" and "vitals overdue" | `backend/main.py` | 579 |
| BUG-13 | 🟡 MEDIUM | `_dischargePatient` state not cleared on nav | `app.js` | 1609 |
| BUG-14 | 🟡 MEDIUM | Global ward cache not per-user (multi-tenant risk) | `backend/main.py` | 433 |
| BUG-15 | 🟡 MEDIUM | Threshold config Save button has no handler | `app.js` | 1183 |
| BUG-16 | 🟢 LOW | SpO2 validation blocks at 70% — too permissive | `app.js` | 1494 |
| BUG-17 | 🟢 LOW | N6 handoff nurse names hardcoded — should use APP.user | `app.js` | 1196 |
| BUG-18 | 🟢 LOW | Doctor portal URL uses `location.hostname:5180` | `app.js` | 1610 |
| BUG-19 | 🟢 LOW | Vitals `is_stale` threshold hardcoded 45 min | `backend/main.py` | 1002 |

---

## Recommended Fix Order (Before Pilot)

**Sprint 1 — Before any stakeholder demo (1 day effort):**
1. BUG-03 — Remove hardcoded data from N4 and N6 (replace with real `APP.data` and `APP.user`)
2. BUG-05 — Delete duplicate `EscalationCreate`, fix hardcoded default name
3. BUG-08 — Remove pre-filled observation text from escalation form
4. BUG-07 — Clear `_ward_cache` in `add_vitals()` endpoint

**Sprint 2 — Before GW Nurse → Doctor workflow demo (2 day effort):**
5. BUG-01 — Fix patient identity propagation through discharge handoff (most complex)
6. BUG-04 — Fix `enc.patient = null` in doctor-queue
7. BUG-09 — Wire "Doctor Acknowledges" to API
8. BUG-02 — Fix scrollability on small screens

**Sprint 3 — Before pilot go-live (3 day effort):**
9. BUG-06 — Fetch attending doctors from real auth table
10. BUG-13 — Clear stale `_dischargePatient` on nav
11. BUG-15 — Wire or visually disable threshold config save
12. BUG-10, BUG-12, BUG-19 — Minor backend fixes
