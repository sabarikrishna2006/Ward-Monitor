import os
import sys

# Requires CLOUD_SQL_PASS already exported in the shell (see .env.secrets) —
# never hardcode the DB password in a file that gets committed to git.
if "CLOUD_SQL_PASS" not in os.environ:
    raise SystemExit("CLOUD_SQL_PASS not set — source common_db_main_latest/.env.secrets first")

# Add path to import database module
sys.path.append(os.path.join(os.path.dirname(__file__), "backend"))
from backend.database import SessionLocal
from sqlalchemy import text

def clean_patient(hadm_id):
    db = SessionLocal()
    try:
        print(f"Cleaning up {hadm_id}...")
        # billing_records has no FK/cascade to active_patients — must delete explicitly
        # or it's left orphaned (app_encounters does cascade, so no need to touch that).
        db.execute(text("DELETE FROM billing_records WHERE hadm_id = :h"), {"h": hadm_id})
        db.execute(text("DELETE FROM active_patients WHERE hadm_id = :h"), {"h": hadm_id})
        db.execute(text("DELETE FROM ews_vitals_timeseries WHERE hadm_id = :h"), {"h": hadm_id})
        db.execute(text("DELETE FROM ews_lab_events WHERE hadm_id = :h"), {"h": hadm_id})
        db.execute(text("DELETE FROM ews_medications WHERE hadm_id = :h"), {"h": hadm_id})
        db.execute(text("DELETE FROM ews_escalations WHERE hadm_id = :h"), {"h": hadm_id})
        db.commit()
        print(f"Successfully cleaned up {hadm_id}.")
    except Exception as e:
        db.rollback()
        print(f"Error cleaning {hadm_id}: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    clean_patient(25201843)  # Rekha Gupta
    clean_patient(20297415)  # Deepak Varma
