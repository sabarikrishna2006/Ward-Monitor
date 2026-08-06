import sqlite3
from datetime import datetime

def run():
    print("Connecting to database...")
    conn = sqlite3.connect('backend/data/ward_careos.db')
    cursor = conn.cursor()

    cursor.execute('SELECT MAX(chart_time) FROM ews_vitals_timeseries')
    row = cursor.fetchone()
    if not row or not row[0]:
        print("No vitals found.")
        return

    max_time_str = row[0]
    if '.' in max_time_str:
        max_time = datetime.strptime(max_time_str, '%Y-%m-%d %H:%M:%S.%f')
    else:
        max_time = datetime.strptime(max_time_str, '%Y-%m-%d %H:%M:%S')
        
    now = datetime.now()
    diff = now - max_time
    shift = int(diff.total_seconds())
    
    if shift > 0:
        print(f"Shifting all records forward by {shift} seconds...")
        cursor.execute(f"UPDATE ews_vitals_timeseries SET chart_time = datetime(chart_time, '+{shift} seconds')")
        cursor.execute(f"UPDATE ews_lab_events SET chart_time = datetime(chart_time, '+{shift} seconds')")
        cursor.execute(f"UPDATE active_patients SET admit_time = datetime(admit_time, '+{shift} seconds') WHERE admit_time IS NOT NULL")
        conn.commit()
        print("Done! Patients will now show as fresh.")
    else:
        print("Data is already up to date.")

if __name__ == '__main__':
    run()
