import os
import sys

# Set environment variable so we connect to the right DB
os.environ["CLOUD_SQL_PASS"] = "foqalAnalyticsHealthcareDB2026"

# Add path to import database module
sys.path.append(os.path.join(os.path.dirname(__file__), "backend"))
from backend.database import SessionLocal
from sqlalchemy import text

def clean_patient(hadm_id):
    db = SessionLocal()
    try:
        print(f"Cleaning up {hadm_id}...")
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
    clean_patient(20000147)
    clean_patient(20000094) # clean up 20000094 as well just in case to start fresh
