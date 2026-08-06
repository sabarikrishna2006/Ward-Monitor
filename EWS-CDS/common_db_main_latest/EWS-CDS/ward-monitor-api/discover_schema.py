# -*- coding: utf-8 -*-
"""
Discover Cloud SQL schema - lists all tables and their columns.
Run once to understand what the DCM patient data looks like.
"""
import os
from google.cloud.sql.connector import Connector, IPTypes
import sqlalchemy
from sqlalchemy import text

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "../healthcare-project-db-creds (1).json"

INSTANCE_CONNECTION_NAME = "healthcare-project-496207:asia-south1:healthcare-project-496207-instance"
DB_USER = "postgres"
DB_PASS = "foqalAnalyticsHealthcareDB2026"
DB_NAME = "postgres"

connector = Connector()

def get_conn():
    return connector.connect(
        INSTANCE_CONNECTION_NAME, "pg8000",
        user=DB_USER, password=DB_PASS, db=DB_NAME,
        ip_type=IPTypes.PUBLIC,
    )

engine = sqlalchemy.create_engine("postgresql+pg8000://", creator=get_conn)

try:
    with engine.connect() as conn:
        tables = conn.execute(text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)).fetchall()

        print(f"\n=== Tables in Cloud SQL ({len(tables)} found) ===")
        for t in tables:
            tname = t[0]
            print(f"\n--- TABLE: {tname} ---")
            cols = conn.execute(text(f"""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = :tname
                ORDER BY ordinal_position;
            """), {"tname": tname}).fetchall()
            for c in cols:
                print(f"  {c[0]:40s} {c[1]:20s} nullable={c[2]}")

            count = conn.execute(text(f'SELECT COUNT(*) FROM "{tname}";')).scalar()
            print(f"  Row count: {count}")

            try:
                sample = conn.execute(text(f'SELECT * FROM "{tname}" LIMIT 1;')).fetchone()
                if sample:
                    print(f"  Sample keys: {list(sample._mapping.keys())}")
            except Exception as se:
                print(f"  Sample error: {se}")

except Exception as e:
    print(f"Error: {e}")
    import traceback; traceback.print_exc()
finally:
    connector.close()
