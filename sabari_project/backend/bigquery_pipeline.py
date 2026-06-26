import os
import sys
from datetime import datetime
from google.cloud import bigquery
import sqlite3

# Set credentials path - UPDATE this if different
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "healthcare-project-db-creds (1).json"
)

# Output DB path
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "real_mimic_data.db")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS patients (
        subject_id INTEGER PRIMARY KEY,
        hadm_id INTEGER,
        gender TEXT,
        anchor_age INTEGER,
        admittime TEXT,
        dischtime TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS chartevents (
        subject_id INTEGER,
        hadm_id INTEGER,
        charttime TEXT,
        itemid INTEGER,
        valuenum REAL
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS labevents (
        subject_id INTEGER,
        hadm_id INTEGER,
        charttime TEXT,
        itemid INTEGER,
        valuenum REAL
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS prescriptions (
        subject_id INTEGER,
        hadm_id INTEGER,
        drug TEXT,
        dose_val_rx TEXT,
        dose_unit_rx TEXT
    )''')
    
    conn.commit()
    return conn

def extract_mimic_data():
    print("Initializing BigQuery client...")
    try:
        client = bigquery.Client()
    except Exception as e:
        print(f"Failed to initialize BigQuery client: {e}")
        print("Please ensure GOOGLE_APPLICATION_CREDENTIALS is set correctly.")
        return

    conn = init_db()
    c = conn.cursor()
    
    # Clean previous extractions
    c.execute("DELETE FROM patients")
    c.execute("DELETE FROM chartevents")
    c.execute("DELETE FROM labevents")
    c.execute("DELETE FROM prescriptions")
    
    print("1. Fetching DCM Patients (ICD-10 I42.0 or 425)...")
    q_patients = """
        SELECT DISTINCT p.subject_id, a.hadm_id, p.gender, p.anchor_age, a.admittime, a.dischtime
        FROM `physionet-data.mimiciv_hosp.patients` p
        JOIN `physionet-data.mimiciv_hosp.admissions` a ON p.subject_id = a.subject_id
        JOIN `physionet-data.mimiciv_hosp.diagnoses_icd` d ON a.hadm_id = d.hadm_id
        WHERE d.icd_code LIKE 'I42%' OR d.icd_code LIKE '425%'
        LIMIT 50
    """
    patients_df = client.query(q_patients).to_dataframe()
    patients_df.to_sql("patients", conn, if_exists="append", index=False)
    
    subject_ids = patients_df["subject_id"].tolist()
    print(f"   Found {len(subject_ids)} patients. Fetching vitals...")
    
    # 2. Vitals
    q_vitals = f"""
        SELECT subject_id, hadm_id, charttime, itemid, valuenum 
        FROM `physionet-data.mimiciv_icu.chartevents`
        WHERE subject_id IN UNNEST(@subject_ids)
        AND itemid IN (220045, 220210, 220277, 220179, 220180, 223762, 223761)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("subject_ids", "INT64", subject_ids)]
    )
    vitals_df = client.query(q_vitals, job_config=job_config).to_dataframe()
    vitals_df.to_sql("chartevents", conn, if_exists="append", index=False)
    print(f"   Fetched {len(vitals_df)} vital records.")
    
    # 3. Labs
    print("3. Fetching Labs (DCM specific: BNP, Troponin, Potassium, INR, etc.)...")
    q_labs = f"""
        SELECT subject_id, hadm_id, charttime, itemid, valuenum
        FROM `physionet-data.mimiciv_hosp.labevents`
        WHERE subject_id IN UNNEST(@subject_ids)
        AND itemid IN (
            50971, -- Potassium
            50912, -- Creatinine
            50813, -- Lactate
            51237, -- INR
            50963, -- BNP
            51003, -- Troponin T
            50983, -- Sodium
            51222  -- Hemoglobin
        )
    """
    labs_df = client.query(q_labs, job_config=job_config).to_dataframe()
    labs_df.to_sql("labevents", conn, if_exists="append", index=False)
    print(f"   Fetched {len(labs_df)} lab records.")
    
    # 4. Medications
    print("4. Fetching Prescriptions...")
    q_meds = f"""
        SELECT subject_id, hadm_id, drug, dose_val_rx, dose_unit_rx
        FROM `physionet-data.mimiciv_hosp.prescriptions`
        WHERE subject_id IN UNNEST(@subject_ids)
    """
    meds_df = client.query(q_meds, job_config=job_config).to_dataframe()
    meds_df.to_sql("prescriptions", conn, if_exists="append", index=False)
    print(f"   Fetched {len(meds_df)} prescription records.")
    
    conn.close()
    print(f"\nExtraction complete! Real MIMIC data saved to: {DB_PATH}")

if __name__ == "__main__":
    extract_mimic_data()
