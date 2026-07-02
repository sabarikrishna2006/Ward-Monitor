"""
apply_ews_migration.py — Applies ews_migration.sql to Cloud SQL.
Run ONCE from sabari_project/backend/:  py -3 apply_ews_migration.py
"""
import os
from google.cloud.sql.connector import Connector, IPTypes
import sqlalchemy
from sqlalchemy import text

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "healthcare-project-db-creds.json"
)

INSTANCE = "healthcare-project-496207:asia-south1:healthcare-project-496207-instance"
connector = Connector()

def get_conn():
    return connector.connect(INSTANCE, "pg8000", user="postgres",
                             password="Vo(QNIe]S2rCg`.(", db="postgres",
                             ip_type=IPTypes.PUBLIC)

engine = sqlalchemy.create_engine("postgresql+pg8000://", creator=get_conn)

sql_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ews_migration.sql")
with open(sql_path, encoding="utf-8") as f:
    raw = f.read()

# Split on semicolons, skip comments and blank lines
statements = []
for stmt in raw.split(";"):
    lines = [l for l in stmt.splitlines() if l.strip() and not l.strip().startswith("--")]
    cleaned = "\n".join(lines).strip()
    if cleaned:
        statements.append(cleaned)

print("Applying %d SQL statements to Cloud SQL..." % len(statements))

with engine.connect() as conn:
    for i, stmt in enumerate(statements, 1):
        first_line = stmt.splitlines()[0][:80]
        print("  [%d/%d] %s..." % (i, len(statements), first_line))
        conn.execute(text(stmt))
    conn.commit()

print("[OK] EWS migration applied successfully")
connector.close()
