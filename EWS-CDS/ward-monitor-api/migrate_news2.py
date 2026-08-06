import sqlite3

def migrate():
    conn = sqlite3.connect('ward_fastapi.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute("ALTER TABLE patients ADD COLUMN hypercapnic_failure INTEGER DEFAULT 0")
        print("Added hypercapnic_failure to patients")
    except sqlite3.OperationalError:
        print("Column hypercapnic_failure may already exist")
        
    try:
        cursor.execute("ALTER TABLE vitals_timeseries ADD COLUMN consciousness VARCHAR DEFAULT 'A'")
        print("Added consciousness to vitals_timeseries")
    except sqlite3.OperationalError:
        print("Column consciousness may already exist")
        
    try:
        cursor.execute("ALTER TABLE vitals_timeseries ADD COLUMN air_or_oxygen VARCHAR DEFAULT 'Air'")
        print("Added air_or_oxygen to vitals_timeseries")
    except sqlite3.OperationalError:
        print("Column air_or_oxygen may already exist")
        
    # Update some mock data to show functionality
    cursor.execute("UPDATE patients SET hypercapnic_failure = 1 WHERE subject_id IN (1, 3)")
    cursor.execute("UPDATE vitals_timeseries SET air_or_oxygen = 'Oxygen' WHERE subject_id IN (2, 4)")
    cursor.execute("UPDATE vitals_timeseries SET consciousness = 'V' WHERE subject_id = 5")
    
    conn.commit()
    conn.close()
    print("Migration complete!")

if __name__ == "__main__":
    migrate()
