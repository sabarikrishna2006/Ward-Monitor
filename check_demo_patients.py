import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "sabari_project", "backend"))

# Use the environment variables pointing to Cloud SQL
_env_path = os.path.join(os.path.dirname(__file__), "sabari_project", "backend", ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

os.environ.setdefault(
    "GOOGLE_APPLICATION_CREDENTIALS",
    os.path.join(os.path.dirname(__file__), "foqal-healthcare-project-google.json")
)

from database import SessionLocal
from mimic_sync import list_dcm_patients
from sqlalchemy import text

def check():
    db = SessionLocal()
    try:
        # Check total active patients
        print("Total active patients:")
        rows = db.execute(text("SELECT COUNT(*) FROM active_patients")).scalar()
        print("  %s" % rows)

        print("Total ews_vitals_timeseries:")
        rows = db.execute(text("SELECT COUNT(*) FROM ews_vitals_timeseries")).scalar()
        print("  %s" % rows)

        # Check demo rows specifically
        demo_rows = db.execute(text("""
            SELECT DISTINCT ap.hadm_id, ap.patient_name
            FROM active_patients ap
            WHERE EXISTS (
                SELECT 1 FROM ews_vitals_timeseries v WHERE v.hadm_id = ap.hadm_id
            )
        """)).fetchall()
        print("\nDemo rows matching criteria:")
        for r in demo_rows:
            print("  %s: %s" % (r[0], r[1]))

        print("\nRunning list_dcm_patients:")
        dcm = list_dcm_patients(db)
        print("Returned %d patients" % len(dcm))
        for p in dcm:
            name = p.get('patient_name') or p.get('subject_id')
            print("  %s: %s" % (p['hadm_id'], name))

    except Exception as e:
        print("ERROR:", e)
    finally:
        db.close()

if __name__ == "__main__":
    check()
