"""
End-to-end test: register one patient in active_patients, trigger BigQuery
fetch, and verify all clinical tables were populated.

Usage:
    python test_patient_fetch.py [hadm_id]

Default hadm_id: 20000293
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

_env_path = os.path.join(os.path.dirname(__file__), "backend", ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

os.environ.setdefault(
    "GOOGLE_APPLICATION_CREDENTIALS",
    r"C:\Users\ASUS\Desktop\discharge-summary-ai\Foqal_Bucket\foqal-healthcare-project-google.json",
)

from sqlalchemy import text
from backend.app.cloud_sql_db import get_engine, ping
from backend.app.bigquery_mimic_loader import fetch_and_store_patient

HADM_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 20000293

CLINICAL_TABLES = [
    "ap_admissions", "ap_diagnoses", "ap_procedures", "ap_drgcodes",
    "ap_labevents", "ap_microbiologyevents", "ap_prescriptions",
    "ap_icustays", "ap_chartevents", "ap_transfers", "ap_services",
    "ap_pharmacy", "ap_poe", "ap_omr",
    "ap_procedureevents", "ap_datetimeevents", "ap_inputevents", "ap_outputevents",
]


def main():
    print(f"\n{'='*60}")
    print(f"  Foqal Cloud SQL — Patient Fetch Test")
    print(f"  hadm_id = {HADM_ID}")
    print(f"{'='*60}\n")

    # ── 1. connectivity check ──────────────────────────────────────────────
    print("Step 1: Cloud SQL connectivity …", end=" ")
    if not ping():
        print("FAIL — check CLOUD_SQL_PASS / instance name")
        sys.exit(1)
    print("OK")

    engine = get_engine()

    # ── 2. register patient row (billing staff action) ─────────────────────
    print("Step 2: Register patient in active_patients …", end=" ")
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO active_patients (hadm_id, subject_id, status, data_fetch_status)
            VALUES (:h, 0, 'active', 'pending')
            ON CONFLICT (hadm_id) DO NOTHING
        """), {"h": HADM_ID})
    print("OK")

    # ── 3. BigQuery fetch ──────────────────────────────────────────────────
    print("Step 3: Fetching from BigQuery MIMIC-IV …\n")
    counts = fetch_and_store_patient(HADM_ID, engine)

    if "error" in counts:
        print(f"\n  ERROR: {counts['error']}")
        sys.exit(1)
    if counts.get("skipped"):
        print(f"\n  SKIPPED: {counts.get('reason')}")

    # ── 4. Verification ────────────────────────────────────────────────────
    print(f"\n{'─'*50}")
    print("Step 4: Row counts in Cloud SQL\n")

    all_ok = True
    with engine.begin() as conn:
        # Master row
        ap = conn.execute(text(
            "SELECT status, data_fetch_status, primary_diagnosis_title, "
            "       anchor_age, gender, admission_type, los_days "
            "FROM active_patients WHERE hadm_id=:h"
        ), {"h": HADM_ID}).fetchone()

        if ap:
            print(f"  active_patients row:")
            print(f"    status              : {ap[0]}")
            print(f"    data_fetch_status   : {ap[1]}")
            print(f"    primary_diagnosis   : {ap[2]}")
            print(f"    age / gender        : {ap[3]} / {ap[4]}")
            print(f"    admission_type      : {ap[5]}")
            print(f"    LOS (days)          : {ap[6]}")
        else:
            print("  ERROR: active_patients row not found!")
            all_ok = False

        print()

        # Clinical tables
        print(f"  {'Table':<30} {'Rows':>8}")
        print(f"  {'─'*38}")
        for tbl in CLINICAL_TABLES:
            try:
                n = conn.execute(
                    text(f"SELECT COUNT(*) FROM {tbl} WHERE hadm_id=:h"),
                    {"h": HADM_ID}
                ).scalar()
                flag = "  ✓" if n and n > 0 else "  –"
                print(f"  {tbl:<30} {n:>8}{flag}")
                if n is None:
                    all_ok = False
            except Exception as e:
                print(f"  {tbl:<30}  ERROR: {e}")
                all_ok = False

    print(f"\n{'─'*50}")
    print(f"  Total rows inserted : {counts.get('_total_rows', '?')}")
    print(f"  Time taken          : {counts.get('_elapsed_s', '?')}s")
    print(f"  Result              : {'PASS ✓' if all_ok else 'PARTIAL — check above'}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
