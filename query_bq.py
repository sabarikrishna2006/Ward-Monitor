from google.cloud import bigquery
import pandas as pd
import os
# Remove the global Vertex AI key from environment so BigQuery falls back to your personal login!
os.environ.pop('GOOGLE_APPLICATION_CREDENTIALS', None)

try:
    client = bigquery.Client(project="healthcare-project-496207")
    print("Successfully connected to BigQuery using your personal account!")
    
    hadm_id = 22202271
    
    print(f"\n--- Fetching Full Patient Profile for hadm_id: {hadm_id} ---")
    
    # 1. Procedures
    df_procs = client.query(f"SELECT icd_code FROM `physionet-data.mimiciv_3_1_hosp.procedures_icd` WHERE hadm_id = {hadm_id} LIMIT 5").to_dataframe()
    print("\n[1. Procedures (Itemized)]\n", df_procs)

    # 2. Medications
    df_meds = client.query(f"SELECT drug FROM `physionet-data.mimiciv_3_1_hosp.prescriptions` WHERE hadm_id = {hadm_id} LIMIT 5").to_dataframe()
    print("\n[2. Medications (Itemized)]\n", df_meds)
    
    # 3. Labs
    df_labs = client.query(f"SELECT COUNT(*) as total_labs FROM `physionet-data.mimiciv_3_1_hosp.labevents` WHERE hadm_id = {hadm_id}").to_dataframe()
    print("\n[3. Lab Events (Counted for Multiplier)]\n", df_labs)

    # 4. Microbiology
    df_micro = client.query(f"SELECT COUNT(*) as total_cultures FROM `physionet-data.mimiciv_3_1_hosp.microbiologyevents` WHERE hadm_id = {hadm_id}").to_dataframe()
    print("\n[4. Microbiology (Counted for Multiplier)]\n", df_micro)

    # 5. ICU Stays (The Bundled Bed Rate)
    df_icu = client.query(f"SELECT los as icu_days FROM `physionet-data.mimiciv_3_1_icu.icustays` WHERE hadm_id = {hadm_id}").to_dataframe()
    print("\n[5. ICU Stays (For Bundled 15k Rate)]\n", df_icu)

    # 6. Diagnosis (The PM-JAY Base Rate)
    df_diag = client.query(f"SELECT icd_code FROM `physionet-data.mimiciv_3_1_hosp.diagnoses_icd` WHERE hadm_id = {hadm_id} LIMIT 3").to_dataframe()
    print("\n[6. Diagnoses (For Base Package Cost)]\n", df_diag)

except Exception as e:
    print(f"\nError: You need to log in first! \nDetails: {e}")
