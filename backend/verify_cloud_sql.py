"""
verify_cloud_sql.py — Confirm Cloud SQL connectivity and list existing tables.
Run from sabari_project/backend/:  python verify_cloud_sql.py
"""
import os
from google.cloud.sql.connector import Connector, IPTypes
import sqlalchemy
from sqlalchemy import text

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "healthcare-project-db-creds.json"
)

INSTANCE = "healthcare-project-496207:us-central1:foqal-healthcare-cloud-sql-db"
DB_USER = "postgres"
DB_PASS = "foqalAnalyticsHealthcareDB2026"
DB_NAME = "postgres"

connector = Connector()

def get_conn():
    return connector.connect(INSTANCE, "pg8000", user=DB_USER, password=DB_PASS,
                             db=DB_NAME, ip_type=IPTypes.PUBLIC)

engine = sqlalchemy.create_engine("postgresql+pg8000://", creator=get_conn)

try:
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename;
        """))
        tables = [r[0] for r in result]
        print(f"\n[OK] Connected to Cloud SQL. Found {len(tables)} tables:\n")
        for t in tables:
            print(f"  - {t}")

        # Check active_patients columns
        result = conn.execute(text("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'active_patients'
            ORDER BY ordinal_position;
        """))
        cols = result.fetchall()
        print(f"\nactive_patients columns ({len(cols)}):")
        for col in cols:
            print(f"  {col[0]}: {col[1]}")

        # Check EWS tables
        ews_tables = ['ews_vitals_timeseries', 'ews_lab_events', 'ews_medications',
                      'ews_escalations', 'ews_ccu_transfers', 'ews_drug_lab_actions']
        print("\nEWS table status:")
        for t in ews_tables:
            exists = t in tables
            print(f"  {'[Y]' if exists else '[N]'} {t}")

        # Row counts for existing tables (if any EWS tables present)
        existing_ews = [t for t in ews_tables if t in tables]
        if existing_ews:
            print("\nEWS table row counts:")
            for t in existing_ews:
                count = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                print(f"  {t}: {count} rows")

        # active_patients count
        ap_count = conn.execute(text("SELECT COUNT(*) FROM active_patients")).scalar()
        print(f"\nactive_patients: {ap_count} rows")

except Exception as e:
    print(f"\n[FAIL] Connection failed: {e}")
    raise
finally:
    connector.close()
