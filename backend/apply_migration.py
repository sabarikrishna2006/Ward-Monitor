"""
Apply a numbered SQL migration to Cloud SQL.

Usage:
    python backend/apply_migration.py 001
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pathlib import Path


def main():
    num = sys.argv[1] if len(sys.argv) > 1 else None
    if not num:
        print("Usage: python backend/apply_migration.py <number>  e.g. 001")
        sys.exit(1)

    migrations_dir = Path(__file__).parent / "app" / "migrations"
    matches = sorted(migrations_dir.glob(f"{num}_*.sql"))
    if not matches:
        print(f"No migration file found matching {num}_*.sql in {migrations_dir}")
        sys.exit(1)

    sql_file = matches[0]
    print(f"Applying migration: {sql_file.name}")

    from backend.app.cloud_sql_db import get_engine, ping
    if not ping():
        print("ERROR: Cannot reach Cloud SQL")
        sys.exit(1)

    sql = sql_file.read_text(encoding="utf-8")
    engine = get_engine()
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(sql)
        raw.commit()
        cur.close()
        print(f"Migration {sql_file.name} applied successfully.")
    except Exception as e:
        raw.rollback()
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        raw.close()


if __name__ == "__main__":
    main()
