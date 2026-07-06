"""
Standalone script: run migration 026 against Cloud SQL.
Creates hospital_core, ews, discharge_ai schemas + 23 tables.
Safe to re-run — all statements use IF NOT EXISTS.

Usage (from inside 'common_db/' folder):
    py apply_026.py
"""
import sys
import os
import pathlib
import re

# Add backend to path so we can import cloud_sql_db
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

print("Connecting to Cloud SQL...")
from app.cloud_sql_db import get_engine
from sqlalchemy import text

engine = get_engine()

# Quick connectivity test
try:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("Cloud SQL connection OK")
except Exception as e:
    print(f"ERROR: Cannot connect to Cloud SQL: {e}")
    sys.exit(1)

# Read migration 026 SQL
sql_path = pathlib.Path(__file__).parent / "backend" / "app" / "migrations" / "026_erd_schema_tables.sql"
if not sql_path.exists():
    print(f"ERROR: Migration file not found at {sql_path}")
    sys.exit(1)

raw = sql_path.read_text(encoding="utf-8")


def extract_sql(chunk: str) -> str:
    """Strip leading/trailing comment lines and blank lines from a statement chunk.
    Returns the actual SQL, or empty string if the chunk is comment-only."""
    lines = chunk.split("\n")
    sql_lines = []
    past_leading = False
    for line in lines:
        stripped = line.strip()
        # Skip leading blank lines and -- comment lines before SQL starts
        if not past_leading:
            if stripped == "" or stripped.startswith("--"):
                continue
            past_leading = True
        sql_lines.append(line)
    return "\n".join(sql_lines).strip()


# Split on semicolons, extract real SQL from each chunk
stmts = []
for chunk in raw.split(";"):
    sql = extract_sql(chunk)
    if sql:
        stmts.append(sql)

print(f"Found {len(stmts)} SQL statements to execute...\n")

ok, errors = 0, 0
for i, stmt in enumerate(stmts, 1):
    first_line = stmt.replace("\n", " ").strip()[:70]
    try:
        with engine.begin() as conn:
            conn.execute(text(stmt))
        ok += 1
        print(f"  [{i:02d}/{len(stmts)}] OK   — {first_line}")
    except Exception as e:
        err_str = str(e)
        # "already exists" is expected on re-runs — count as ok
        if "already exists" in err_str.lower():
            ok += 1
            print(f"  [{i:02d}/{len(stmts)}] SKIP (exists) — {first_line[:55]}")
        else:
            errors += 1
            # Extract the useful part of the pg8000 error
            m = re.search(r"'M': '([^']+)'", err_str)
            short_err = m.group(1) if m else err_str[:80]
            print(f"  [{i:02d}/{len(stmts)}] ERROR — {first_line[:45]} | {short_err}")

print(f"\nMigration 026: {ok} OK, {errors} real errors")

# Verify
print("\n--- Cloud SQL verification ---")
with engine.connect() as conn:
    schemas = conn.execute(text(
        "SELECT schema_name FROM information_schema.schemata "
        "WHERE schema_name IN ('hospital_core','ews','discharge_ai') "
        "ORDER BY schema_name"
    )).fetchall()

    tables = conn.execute(text(
        "SELECT table_schema, table_name FROM information_schema.tables "
        "WHERE table_schema IN ('hospital_core','ews','discharge_ai') "
        "ORDER BY table_schema, table_name"
    )).fetchall()

    hosp_row = conn.execute(text(
        "SELECT short_code, name FROM hospital_core.hospitals LIMIT 1"
    )).fetchone() if any(r[0] == "hospital_core" for r in schemas) else None

schema_names = [r[0] for r in schemas]
print(f"Schemas: {schema_names}")
print(f"Tables ({len(tables)} total):")
current_schema = None
for schema, tbl in tables:
    if schema != current_schema:
        print(f"  [{schema}]")
        current_schema = schema
    print(f"    {tbl}")

if hosp_row:
    print(f"\nSeed hospital: {hosp_row[1]} ({hosp_row[0]})")

print()
if len(tables) >= 23 and errors == 0:
    print("SUCCESS — All 23 ERD tables present. Next step:")
    print("  Start Sabari backend (port 7826), then call:")
    print("  POST http://localhost:7826/api/admissions/provision-all")
elif len(tables) >= 23 and errors > 0:
    print(f"PARTIAL — {len(tables)} tables present but {errors} statement(s) failed.")
    print("Tables that already existed are fine. Check the ERROR lines above.")
else:
    print(f"INCOMPLETE — Only {len(tables)}/23 tables found. {errors} real errors above.")
    print("Fix the errors and re-run. All statements are idempotent.")
