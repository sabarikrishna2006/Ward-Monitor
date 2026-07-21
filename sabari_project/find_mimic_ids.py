import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))
from database import engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

Session = sessionmaker(bind=engine)
db = Session()

try:
    print("Connecting to Cloud SQL to find GUARANTEED demo hadm_ids...")
    # This query specifically EXCLUDES patients who have real ICU vitals.
    # This guarantees the backend will use the predictable (id % 3) logic.
    rows = db.execute(text("""
        SELECT DISTINCT aa.hadm_id
        FROM ap_admissions aa
        JOIN ap_diagnoses ad ON aa.hadm_id = ad.hadm_id
        LEFT JOIN mimic_icu.chartevents_pivoted icu ON icu.hadm_id = aa.hadm_id
        WHERE (ad.icd_code LIKE 'I42%' OR ad.icd_code LIKE '425%')
        AND icu.hadm_id IS NULL
        LIMIT 200
    """)).fetchall()
    
    critical_ids = []
    warning_ids = []
    stable_ids = []
    
    for row in rows:
        hadm_id = row[0]
        modulo = hadm_id % 3
        if modulo == 2 and len(critical_ids) < 3:
            critical_ids.append(hadm_id)
        elif modulo == 1 and len(warning_ids) < 3:
            warning_ids.append(hadm_id)
        elif modulo == 0 and len(stable_ids) < 3:
            stable_ids.append(hadm_id)
            
    print("\n" + "="*60)
    print(" USE THESE REAL MIMIC IDs FOR YOUR DEMO (100% GUARANTEED):")
    print("="*60)
    
    print(f"\n1. ESCALATION / CRITICAL FLOW (NEWS2 ~11)")
    print("These will admit instantly as CRITICAL:")
    for cid in critical_ids: print(f"  -> {cid}")

    print(f"\n2. MODERATE / WARNING FLOW (NEWS2 ~6)")
    print("These will admit as WARNING:")
    for wid in warning_ids: print(f"  -> {wid}")
        
    print(f"\n3. STABLE ADMISSION FLOW (NEWS2 0)")
    print("These will admit entirely STABLE:")
    for sid in stable_ids: print(f"  -> {sid}")

except Exception as e:
    print(f"Error: {e}")
