"""
Clears ALL patients from every dashboard table.
Run from repo root: python clear_all_patients.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from app.cloud_sql_db import get_engine
from sqlalchemy import text

engine = get_engine()

TABLES = [
    # EWS child tables first (FK → active_patients.hadm_id)
    "ews_ccu_transfers",
    "ews_escalations",
    "ews_medications",
    "ews_lab_events",
    "ews_vitals_timeseries",
    # Ashmit app tables
    "amendment_log",
    "app_summaries",
    "rejection_log",
    "billing_records",
    "app_encounters",
    # MIMIC clinical tables
    "ap_prescriptions",
    "ap_labevents",
    "ap_chartevents",
    "ap_diagnoses",
    "ap_procedures",
    "ap_microbiologyevents",
    "ap_inputevents",
    "ap_outputevents",
    "ap_procedureevents",
    "ap_poe",
    "ap_pharmacy",
    "ap_icustays",
    "ap_transfers",
    # Main patient table last
    "active_patients",
]

for tbl in TABLES:
    try:
        with engine.begin() as conn:
            result = conn.execute(text(f"DELETE FROM {tbl}"))
            print(f"  [ok]   {tbl}: {result.rowcount} rows deleted")
    except Exception as e:
        msg = str(e).split('\n')[0][:120]
        print(f"  [skip] {tbl}: {msg}")

# hospital_core has a deep FK chain. Truncate both patients + admissions
# in a single statement so CASCADE resolves all dependencies atomically.
print("\n  Clearing hospital_core patient data (TRUNCATE CASCADE)...")
try:
    with engine.begin() as conn:
        conn.execute(text(
            "TRUNCATE TABLE hospital_core.admissions, hospital_core.patients CASCADE"
        ))
    print("  [ok]   hospital_core.admissions + hospital_core.patients: truncated (cascade)")
except Exception as e:
    msg = str(e).split('\n')[0][:120]
    print(f"  [skip] hospital_core: {msg}")
    # Fallback: try patients-only CASCADE (admissions should cascade from it)
    try:
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE hospital_core.patients CASCADE"))
        print("  [ok]   hospital_core.patients: truncated (cascade fallback)")
    except Exception as e2:
        msg2 = str(e2).split('\n')[0][:120]
        print(f"  [skip] hospital_core.patients fallback: {msg2}")

print("\nDone.")
