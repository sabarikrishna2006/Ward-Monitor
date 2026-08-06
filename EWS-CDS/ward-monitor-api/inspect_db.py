

import sqlite3
import os

for db_file in ['ward_fastapi.db', 'ward_data.db']:
    if not os.path.exists(db_file):
        print(f"\n{db_file} - NOT FOUND")
        continue
    print(f"\n{'='*60}")
    print(f"DATABASE: {db_file}")
    print(f"{'='*60}")
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in cur.fetchall()]
    print(f"Tables: {tables}")

    for table in tables:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        count = cur.fetchone()[0]
        print(f"\n  {table}: {count} rows")
        cur.execute(f"PRAGMA table_info({table})")
        cols = [c[1] for c in cur.fetchall()]
        print(f"  Columns: {cols}")
        cur.execute(f"SELECT * FROM {table} LIMIT 2")
        sample = cur.fetchall()
        for row in sample:
            print(f"  SAMPLE: {row}")

    conn.close()
