import sqlite3, sys
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

conn = sqlite3.connect("data/ward_careos.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT subject_id, ward_location FROM patients ORDER BY subject_id")
rows = cur.fetchall()
print("SQLite patients (%d rows):" % len(rows))
for r in rows:
    print("  sid=%s wl=%s" % (r["subject_id"], r["ward_location"]))

# Check table row counts
for tbl in ["patients","vitals_timeseries","lab_events","medications","escalations","ccu_transfers","drug_lab_actions"]:
    cur.execute("SELECT COUNT(*) FROM " + tbl)
    print("  %s: %d rows" % (tbl, cur.fetchone()[0]))
conn.close()
