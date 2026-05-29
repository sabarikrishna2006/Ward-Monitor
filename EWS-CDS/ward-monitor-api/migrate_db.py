import sqlite3

def migrate():
    conn = sqlite3.connect('ward_fastapi.db')
    cur = conn.cursor()
    
    try:
        cur.execute("ALTER TABLE patients ADD COLUMN ward VARCHAR DEFAULT 'Ward 4B - Acute Care'")
        print("Added ward column")
    except sqlite3.OperationalError as e:
        print("Column ward might already exist:", e)

    try:
        cur.execute("CREATE TABLE medications (id INTEGER PRIMARY KEY AUTOINCREMENT, subject_id INTEGER, med_name VARCHAR, dose VARCHAR, frequency VARCHAR)")
        print("Created medications table")
    except sqlite3.OperationalError as e:
        print("Table medications might already exist:", e)

    conn.commit()
    conn.close()

if __name__ == '__main__':
    migrate()
