"""
Fix demo data for a coherent CCU + GW + discharge demo, and verify ward-data perf.
- Reset 91003 (Govind Rao): undo erroneous discharge -> back to CCU, active.
- Place stable patients in GENERAL_WARD so the GW Nurse has a discharge worklist.
- Time /api/ward-data in-process (uses the edited code on disk) to confirm the
  per-request MIMIC auto-sync removal fixed the slowness.

Run from common_db/:  py fix_demo_data.py
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "sabari_project", "backend"))
from database import engine
from sqlalchemy import text

print("=" * 64)
print("1. FIX DEMO DATA")
print("=" * 64)
with engine.begin() as c:
    # 91003 Govind Rao: a CCU warning patient — undo the earlier direct discharge
    c.execute(text("UPDATE active_patients SET ward_location='CCU', status='active' WHERE hadm_id=91003"))
    c.execute(text("UPDATE app_encounters SET status='Pending Ingestion', updated_at=NOW() "
                   "WHERE hadm_id=91003 AND status='Ready for Review'"))
    print("  91003 Govind Rao -> CCU / active (discharge undone)")

    # GW worklist: Joseph (91005, stepped down) + Anjali (91006) are the stable GW patients
    c.execute(text("UPDATE active_patients SET ward_location='GENERAL_WARD', status='active' WHERE hadm_id IN (91005, 91006)"))
    # Joseph's pending CCU->GW transfer is now complete (he is in GW)
    c.execute(text("UPDATE ews_ccu_transfers SET status='approved', decided_at=NOW(), decided_by='Sister Leena Kurup' "
                   "WHERE hadm_id=91005 AND status='pending'"))
    print("  91005 Joseph Thomas -> GENERAL_WARD (step-down approved)")
    print("  91006 Anjali Nair   -> GENERAL_WARD")

    # Show resulting ward distribution
    rows = c.execute(text("SELECT hadm_id, patient_name, ward_location, status FROM active_patients "
                          "WHERE hadm_id BETWEEN 91001 AND 91006 ORDER BY hadm_id")).fetchall()
    print("\n  Demo ward distribution:")
    for r in rows:
        print(f"    {r[0]} {r[1]:16s} {r[2]:13s} {r[3]}")

print("\n" + "=" * 64)
print("2. VERIFY WARD-DATA PERFORMANCE (in-process, edited code)")
print("=" * 64)
from fastapi.testclient import TestClient
import main
client = TestClient(main.app)

for label, params in [("CCU view", {"location": "CCU"}),
                      ("GW view",  {"location": "GENERAL_WARD"}),
                      ("All",      {"ward": "All"})]:
    t0 = time.time()
    r = client.get("/api/ward-data", params=params)
    dt = time.time() - t0
    n = len(r.json().get("patients", [])) if r.status_code == 200 else 0
    print(f"  {label:9s} -> {dt*1000:7.0f} ms  HTTP {r.status_code}  ({n} patients)")
