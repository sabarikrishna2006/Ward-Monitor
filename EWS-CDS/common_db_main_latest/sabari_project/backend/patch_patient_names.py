"""
patch_patient_names.py - Add patient_name column and migrate names from SQLite.
Also checks for duplicate EWS rows and cleans them up if needed.
Run: py -3 patch_patient_names.py
"""
import os, sqlite3
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "healthcare-project-db-creds.json"
)
from google.cloud.sql.connector import Connector, IPTypes
import sqlalchemy
from sqlalchemy import text

INSTANCE = "healthcare-project-496207:asia-south1:healthcare-project-496207-instance"
connector = Connector()
def get_conn():
    return connector.connect(INSTANCE, "pg8000", user="postgres",
                             password=os.environ["CLOUD_SQL_PASS"], db="postgres",
                             ip_type=IPTypes.PUBLIC)
engine = sqlalchemy.create_engine("postgresql+pg8000://", creator=get_conn)

# 1. Add patient_name column to active_patients
with engine.connect() as pg:
    pg.execute(text("ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS patient_name VARCHAR(200)"))
    pg.commit()
    print("[OK] patient_name column added to active_patients")

# 2. Read names from SQLite
sqlite_conn = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ward_careos.db"))
sqlite_conn.row_factory = sqlite3.Row
cur = sqlite_conn.cursor()
cur.execute("SELECT subject_id, name FROM patients")
patients = cur.fetchall()
sqlite_conn.close()

# 3. Update Cloud SQL rows with names
with engine.connect() as pg:
    for p in patients:
        name = p["name"] or ("Patient %d" % p["subject_id"])
        pg.execute(text("UPDATE active_patients SET patient_name = :n WHERE hadm_id = :h"),
                   {"n": name, "h": p["subject_id"]})
    pg.commit()
    print("[OK] Patient names migrated (%d rows)" % len(patients))

# 4. Check for duplicate EWS rows
with engine.connect() as pg:
    print("\nCurrent EWS row counts:")
    for tbl in ["ews_vitals_timeseries", "ews_lab_events", "ews_medications",
                "ews_escalations", "ews_ccu_transfers", "ews_drug_lab_actions"]:
        count = pg.execute(text("SELECT COUNT(*) FROM " + tbl)).scalar()
        print("  %s: %d rows" % (tbl, count))

    # Check for duplicates in vitals (same hadm_id + chart_time)
    dup_count = pg.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT hadm_id, chart_time, COUNT(*) as cnt
            FROM ews_vitals_timeseries
            GROUP BY hadm_id, chart_time
            HAVING COUNT(*) > 1
        ) dups
    """)).scalar()
    print("\nDuplicate vitals (same hadm_id + chart_time): %d" % dup_count)

    if dup_count > 0:
        print("Cleaning up duplicates...")
        # Keep the row with lowest id for each (hadm_id, chart_time)
        pg.execute(text("""
            DELETE FROM ews_vitals_timeseries
            WHERE id NOT IN (
                SELECT MIN(id) FROM ews_vitals_timeseries
                GROUP BY hadm_id, chart_time
            )
        """))
        pg.execute(text("""
            DELETE FROM ews_lab_events
            WHERE id NOT IN (
                SELECT MIN(id) FROM ews_lab_events
                GROUP BY hadm_id, chart_time
            )
        """))
        pg.execute(text("""
            DELETE FROM ews_medications
            WHERE id NOT IN (
                SELECT MIN(id) FROM ews_medications
                GROUP BY hadm_id, med_name, dose, frequency
            )
        """))
        pg.execute(text("""
            DELETE FROM ews_ccu_transfers
            WHERE id NOT IN (
                SELECT MIN(id) FROM ews_ccu_transfers
                GROUP BY hadm_id
            )
        """))
        pg.commit()
        print("[OK] Duplicates cleaned")

        # Recount
        print("\nFinal EWS row counts after cleanup:")
        for tbl in ["ews_vitals_timeseries", "ews_lab_events", "ews_medications",
                    "ews_escalations", "ews_ccu_transfers", "ews_drug_lab_actions"]:
            count = pg.execute(text("SELECT COUNT(*) FROM " + tbl)).scalar()
            print("  %s: %d rows" % (tbl, count))

    ap_count = pg.execute(text("SELECT COUNT(*) FROM active_patients")).scalar()
    print("\nactive_patients total: %d" % ap_count)

connector.close()
print("\n[DONE]")
