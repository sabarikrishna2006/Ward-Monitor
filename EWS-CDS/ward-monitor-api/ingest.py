import pandas as pd
from database import engine, init_db
from models import Patient, VitalTimeSeries, LabEvent
from sqlalchemy.orm import Session
import random

# Realistic dummy demographics to attach to MIMIC IDs
NAMES = ["James Wilson", "Sarah Connor", "Michael Chang", "Emma Watson", "David Smith", "Linda Taylor", "Robert Johnson", "Emily Davis"]
COMPLAINTS = ["Sepsis, Pneumonia", "Heart Failure Exacerbation", "Post-op Appy", "COPD Exacerbation", "Chest Pain", "DKA", "Renal Failure"]

def ingest_data():
    print("Initializing DB...")
    init_db()
    
    print("Loading CSVs...")
    vitals_df = pd.read_csv("../ward-monitor-cds/data/mimic/hf_vitals.csv")
    labs_df = pd.read_csv("../ward-monitor-cds/data/mimic/hf_labs.csv")

    subject_ids = vitals_df['subject_id'].unique()
    
    with Session(engine) as session:
        # 1. Create Patients
        print("Inserting Patients...")
        bed_num = 1
        for sid in subject_ids:
            # Check if exists
            if not session.query(Patient).filter(Patient.subject_id == int(sid)).first():
                p = Patient(
                    subject_id=int(sid),
                    name=random.choice(NAMES),
                    age=random.randint(40, 85),
                    sex=random.choice(["M", "F"]),
                    room="4B",
                    bed="{:02d}".format(bed_num),
                    admitted="14 Oct 2023",
                    complaint=random.choice(COMPLAINTS)
                )
                session.add(p)
                bed_num += 1
        session.commit()

        # 2. Insert Vitals (Drop existing to avoid duplication)
        print("Inserting Vitals...")
        session.query(VitalTimeSeries).delete()
        
        vitals_records = []
        for _, row in vitals_df.iterrows():
            vitals_records.append(VitalTimeSeries(
                subject_id=int(row['subject_id']),
                chart_hour=str(row['chart_hour']),
                heart_rate=float(row['heart_rate']) if pd.notna(row['heart_rate']) else None,
                resp_rate=float(row['resp_rate']) if pd.notna(row['resp_rate']) else None,
                spo2=float(row['spo2']) if pd.notna(row['spo2']) else None,
                sbp=float(row['sbp']) if pd.notna(row['sbp']) else None,
                dbp=float(row['dbp']) if pd.notna(row['dbp']) else None,
                temperature=float(row['temperature']) if pd.notna(row['temperature']) else None,
            ))
        session.bulk_save_objects(vitals_records)
        session.commit()

        # 3. Insert Labs
        print("Inserting Labs...")
        session.query(LabEvent).delete()
        
        labs_records = []
        for _, row in labs_df.iterrows():
            if int(row['subject_id']) in subject_ids:
                labs_records.append(LabEvent(
                    subject_id=int(row['subject_id']),
                    chart_hour=str(row['chart_hour']),
                    potassium=float(row['potassium']) if pd.notna(row['potassium']) else None,
                    creatinine=float(row['creatinine']) if pd.notna(row['creatinine']) else None,
                    lactate=float(row['lactate']) if pd.notna(row['lactate']) else None,
                ))
        session.bulk_save_objects(labs_records)
        session.commit()

    print("Ingestion complete!")

if __name__ == "__main__":
    ingest_data()
