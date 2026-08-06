"""
End-to-end HIS flow verification (in-process, against real Cloud SQL).
Walks: ADMISSION -> WARD BOARD -> DISCHARGE HANDOFF, and checks the
hospital_core.admissions bridge is created atomically on admission.

Run from common_db/:  py verify_his_flow.py
Cleans up its own test patient at the end.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "sabari_project", "backend"))

from fastapi.testclient import TestClient
from sqlalchemy import text
import main
from database import engine

client = TestClient(main.app)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
def check(label, cond):
    print(f"  [{PASS if cond else FAIL}] {label}")
    return bool(cond)

print("=" * 70)
print("HIS END-TO-END FLOW VERIFICATION")
print("=" * 70)

all_ok = True
test_hadm = None

# ── 1. ADMISSION (billing/registration clerk enters a new admission) ──────────
print("\n1. ADMISSION  — POST /api/patients (a 'warning' DCM patient)")
admit = client.post("/api/patients", json={
    "name": "ZZ Test Patient", "age": 64, "sex": "M",
    "ward": "Ward 4B", "room": "4B", "bed": "99",
    "complaint": "DCM HFrEF — verification test",
    "hr": 116, "rr": 22, "spo2": 92, "sbp": 100, "dbp": 62, "temp": 37.1,
    "air_or_oxygen": "Air", "consciousness": "A", "hypercapnic_failure": 0,
})
all_ok &= check(f"admission returns 200 (got {admit.status_code})", admit.status_code == 200)
body = admit.json() if admit.status_code == 200 else {}
test_hadm = body.get("subject_id")
all_ok &= check(f"active_patients hadm_id created ({test_hadm})", bool(test_hadm))
all_ok &= check("app_encounters encounter_id returned", bool(body.get("encounter_id")))
all_ok &= check("hospital_core.admissions bridge created on admission",
                bool(body.get("admission_id")))

# verify rows landed in DB
with engine.connect() as c:
    ap = c.execute(text("SELECT status FROM active_patients WHERE hadm_id=:h"), {"h": test_hadm}).fetchone()
    vt = c.execute(text("SELECT COUNT(*) FROM ews_vitals_timeseries WHERE hadm_id=:h"), {"h": test_hadm}).scalar()
    hc = c.execute(text("SELECT status FROM hospital_core.admissions WHERE hadm_id=:h"), {"h": test_hadm}).fetchone()
all_ok &= check(f"active_patients.status = 'active' (got {ap[0] if ap else None})", ap and ap[0] == "active")
all_ok &= check(f"initial vitals row written ({vt} row)", vt and vt >= 1)
all_ok &= check(f"hospital_core.admissions.status = 'admitted' (got {hc[0] if hc else None})",
                hc and hc[0] == "admitted")

# ── 2. WARD NURSE BOARD — patient appears with a live NEWS2 score ─────────────
print("\n2. WARD NURSE — GET /api/ward-data (patient should appear w/ NEWS2)")
ward = client.get("/api/ward-data", params={"ward": "All"})
all_ok &= check(f"ward-data returns 200 (got {ward.status_code})", ward.status_code == 200)
patients = ward.json().get("patients", []) if ward.status_code == 200 else []
mine = next((p for p in patients if p.get("id") == str(test_hadm)), None)
all_ok &= check("test patient appears on ward board", mine is not None)
if mine:
    score = mine.get("news2")
    all_ok &= check(f"NEWS2 score computed (={score})", score is not None)
    all_ok &= check(f"status classified (={mine.get('status')})", mine.get("status") in
                    ("warning", "critical", "stable", "stale"))

# ── 3. NURSE CHARTS MORE VITALS — live NEWS2 recompute ────────────────────────
print("\n3. WARD NURSE — POST /api/patients/{id}/vitals (chart a reading)")
chart = client.post(f"/api/patients/{test_hadm}/vitals", json={
    "heart_rate": 120, "resp_rate": 24, "spo2": 90, "sbp": 95, "dbp": 58,
    "temperature": 37.4, "consciousness": "A", "air_or_oxygen": "Oxygen",
})
all_ok &= check(f"vitals charting returns 200 (got {chart.status_code})", chart.status_code == 200)
if chart.status_code == 200:
    all_ok &= check(f"live NEWS2 returned (={chart.json().get('news2_score')})",
                    chart.json().get("news2_score") is not None)

# ── 4. DISCHARGE HANDOFF — nurse marks ready, hands off to Ashmit ─────────────
print("\n4. HANDOFF — POST /api/patients/{id}/initiate-discharge")
disc = client.post(f"/api/patients/{test_hadm}/initiate-discharge")
all_ok &= check(f"initiate-discharge returns 200 (got {disc.status_code})", disc.status_code == 200)
with engine.connect() as c:
    ap2 = c.execute(text("SELECT status FROM active_patients WHERE hadm_id=:h"), {"h": test_hadm}).fetchone()
    enc = c.execute(text("SELECT status FROM app_encounters WHERE hadm_id=:h"), {"h": test_hadm}).fetchone()
all_ok &= check(f"active_patients.status -> 'data_ready' (got {ap2[0] if ap2 else None})",
                ap2 and ap2[0] == "data_ready")
all_ok &= check(f"app_encounters.status -> 'Ready for Review' (got {enc[0] if enc else None})",
                enc and enc[0] == "Ready for Review")

# ── CLEANUP ───────────────────────────────────────────────────────────────────
print("\n5. CLEANUP — removing test patient")
with engine.begin() as c:
    c.execute(text("DELETE FROM ews_vitals_timeseries WHERE hadm_id=:h"), {"h": test_hadm})
    c.execute(text("DELETE FROM hospital_core.admissions WHERE hadm_id=:h"), {"h": test_hadm})
    c.execute(text("DELETE FROM hospital_core.patients WHERE uhid=:u"),
              {"u": f"FOQAL-{__import__('datetime').datetime.now().year}-{test_hadm:07d}"})
    c.execute(text("DELETE FROM app_encounters WHERE hadm_id=:h"), {"h": test_hadm})
    c.execute(text("DELETE FROM active_patients WHERE hadm_id=:h"), {"h": test_hadm})
print(f"  test patient {test_hadm} removed.")

print("\n" + "=" * 70)
print(f"RESULT: {'ALL CHECKS PASSED' if all_ok else 'SOME CHECKS FAILED — see above'}")
print("=" * 70)
sys.exit(0 if all_ok else 1)
