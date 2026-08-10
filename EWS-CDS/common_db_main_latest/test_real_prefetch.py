import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # common_db_main_latest, so `backend` and `sabari_project` packages resolve
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "sabari_project", "backend"))  # mimic_sync's own imports

_env_path = os.path.join(os.path.dirname(__file__), ".env.secrets")
with open(_env_path) as _f:
    for _line in _f:
        _line = _line.strip()
        if _line.startswith("export "):
            _line = _line[len("export "):]
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"'))
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.join(os.path.dirname(__file__), "foqal-healthcare-project-google.json")

from backend.app.cloud_sql_db import get_engine
from sqlalchemy import text

TEST_HADM = 23882377  # real, DCM-flagged, not currently in active_patients

engine = get_engine()
with engine.begin() as conn:
    existing = conn.execute(text("SELECT COUNT(*) FROM active_patients WHERE hadm_id=:h"), {"h": TEST_HADM}).scalar()
    print("already in active_patients:", existing)
    if not existing:
        conn.execute(text("""
            INSERT INTO active_patients (hadm_id, subject_id, status, ward_location, ward, data_fetch_status, patient_name, admit_time)
            VALUES (:h, :h, 'active', 'CCU', 'Ward 4B', 'pending', 'Test RealFetch Patient', NOW())
        """), {"h": TEST_HADM})
        print("provisioned pending active_patients row")

print("\n=== calling the REAL fetch_and_store_patient (same function prefetch-all calls) ===")
from backend.app.bigquery_mimic_loader import fetch_and_store_patient
try:
    result = fetch_and_store_patient(TEST_HADM, engine, display_only=False)
    print("RESULT:", result)
except Exception as e:
    import traceback
    print("CRASHED:")
    traceback.print_exc()

print("\n=== post-call state ===")
with engine.begin() as conn:
    ce = conn.execute(text("SELECT COUNT(*) FROM ap_chartevents WHERE hadm_id=:h"), {"h": TEST_HADM}).scalar()
    ews = conn.execute(text("SELECT COUNT(*) FROM ews_vitals_timeseries WHERE hadm_id=:h"), {"h": TEST_HADM}).scalar()
    status = conn.execute(text("SELECT data_fetch_status FROM active_patients WHERE hadm_id=:h"), {"h": TEST_HADM}).scalar()
    print(f"ap_chartevents rows for {TEST_HADM}: {ce}")
    print(f"ews_vitals_timeseries rows for {TEST_HADM}: {ews}")
    print(f"data_fetch_status: {status}")
