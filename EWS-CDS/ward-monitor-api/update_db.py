import random
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from database import engine
from models import Patient, VitalTimeSeries, LabEvent, Medication

def update_db():
    with Session(engine) as session:
        patients = session.query(Patient).all()
        
        # 1. Distribute Wards
        wards = ["Ward 4B - Acute Care", "Ward 7A - Step Down"]
        for i, p in enumerate(patients):
            p.ward = wards[i % len(wards)]
        
        # 2. Add Medications
        session.query(Medication).delete()
        meds_data = [
            ("Lisinopril", "10mg", "Daily"),
            ("Spironolactone", "25mg", "Daily"),
            ("Metformin", "500mg", "BID"),
            ("Ibuprofen", "400mg", "PRN"),
            ("Warfarin", "5mg", "Daily"),
            ("Apixaban", "5mg", "BID")
        ]
        
        for p in patients:
            # Give each patient 1-3 random meds
            num_meds = random.randint(1, 3)
            chosen = random.sample(meds_data, num_meds)
            for m in chosen:
                session.add(Medication(
                    subject_id=p.subject_id,
                    med_name=m[0],
                    dose=m[1],
                    frequency=m[2]
                ))
        
        # 3. Shift Timestamps (Mock Replay fix)
        # We find the max timestamp currently in the DB and shift it so the max is "now"
        vitals = session.query(VitalTimeSeries).all()
        if vitals:
            # Assuming chart_hour is string 'YYYY-MM-DD HH:MM:SS'
            # Let's see format first, just print it.
            print("Sample vital time:", vitals[-1].chart_hour)
            
        session.commit()

if __name__ == "__main__":
    update_db()
