import sqlite3

db_path = 'E:/IP_EarlyWarning/ward-monitor-cds/data/ward.db'
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [t[0] for t in cur.fetchall()]
print('Tables:', tables)

for table in tables:
    cur.execute(f"SELECT COUNT(*) FROM [{table}]")
    count = cur.fetchone()[0]
    cur.execute(f"PRAGMA table_info([{table}])")
    cols = [c[1] for c in cur.fetchall()]
    print(f"\n{table}: {count} rows")
    print(f"  Columns: {cols}")
    cur.execute(f"SELECT * FROM [{table}] LIMIT 3")
    for row in cur.fetchall():
        print(f"  ROW: {row}")

conn.close()
