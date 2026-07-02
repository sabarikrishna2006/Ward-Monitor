"""
One-shot script: applies cloud_sql_schema.sql to Cloud SQL.
Idempotent — uses CREATE TABLE IF NOT EXISTS throughout.

Usage:
    python backend/setup_cloud_sql.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pathlib import Path

SCHEMA_FILE = Path(__file__).parent / "cloud_sql_schema.sql"


def main():
    from backend.app.cloud_sql_db import get_engine, ping

    print("== Foqal Cloud SQL setup ==")
    print(f"Schema : {SCHEMA_FILE}")

    if not ping():
        print("\nERROR: Cannot reach Cloud SQL.")
        print("  → Go to GCP Console → SQL → foqal-healthcare-cloud-sql-db")
        print("    → Users → postgres → Edit → set password: Foqal@Healthcare2024")
        sys.exit(1)
    print("Connection : OK\n")

    sql = SCHEMA_FILE.read_text(encoding="utf-8")

    engine = get_engine()

    # Use raw pg8000 connection to execute the full schema script at once
    raw_conn = engine.raw_connection()
    try:
        cursor = raw_conn.cursor()
        cursor.execute(sql)
        raw_conn.commit()
        cursor.close()
    except Exception as e:
        raw_conn.rollback()
        print(f"ERROR applying schema: {e}")
        sys.exit(1)
    finally:
        raw_conn.close()

    print("Schema applied successfully.\n")

    # List all tables
    from sqlalchemy import text
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' ORDER BY tablename"
        )).fetchall()

    print(f"Tables in public schema ({len(rows)}):")
    for r in rows:
        print(f"  {r[0]}")
    print()


if __name__ == "__main__":
    main()
