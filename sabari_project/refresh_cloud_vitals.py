import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))
from database import engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text
from datetime import datetime, timezone

Session = sessionmaker(bind=engine)
db = Session()

try:
    print("Connecting to Cloud SQL...")
    max_time = db.execute(text('SELECT MAX(chart_time) FROM ews_vitals_timeseries')).scalar()
    if not max_time:
        print('No vitals found in Cloud SQL.')
        sys.exit(0)
    
    if isinstance(max_time, str):
        if '.' in max_time:
            max_time = datetime.strptime(max_time, '%Y-%m-%d %H:%M:%S.%f')
        else:
            max_time = datetime.strptime(max_time, '%Y-%m-%d %H:%M:%S')
            
    # max_time comes back tz-aware (timestamptz column); datetime.now() is naive.
    # Match awareness before subtracting, or this raises on every run.
    now = datetime.now(timezone.utc) if max_time.tzinfo else datetime.now()
    diff = now - max_time
    shift = int(diff.total_seconds())
    
    if shift > 0:
        print(f"Shifting all records forward by {shift} seconds...")
        db.execute(text(f"UPDATE ews_vitals_timeseries SET chart_time = chart_time + interval '{shift} seconds'"))
        db.execute(text(f"UPDATE ews_lab_events SET chart_time = chart_time + interval '{shift} seconds'"))
        db.execute(text(f"UPDATE active_patients SET admit_time = admit_time + interval '{shift} seconds' WHERE admit_time IS NOT NULL"))
        try:
            db.execute(text(f"UPDATE hospital_core.admissions SET admitted_at = admitted_at + interval '{shift} seconds' WHERE admitted_at IS NOT NULL"))
        except:
            pass # ignore if table doesn't exist
        db.commit()
        print('Successfully refreshed all vitals, labs, and admission times in Cloud SQL!')
    else:
        print('Data is already up to date.')
except Exception as e:
    print(f'Error: {e}')
