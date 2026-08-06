import sys
sys.path.insert(0, 'backend')
from app.cloud_sql_db import get_engine
from sqlalchemy import text

engine = get_engine()
with engine.connect() as conn:
    cols = conn.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'active_patients' ORDER BY ordinal_position"
    )).fetchall()
    print('active_patients columns:', [r[0] for r in cols])

    tbls = conn.execute(text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name"
    )).fetchall()
    print('tables:', [r[0] for r in tbls])
