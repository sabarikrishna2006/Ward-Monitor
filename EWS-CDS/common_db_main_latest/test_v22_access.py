from google.cloud import bigquery
import os

os.environ.pop('GOOGLE_APPLICATION_CREDENTIALS', None)

try:
    client = bigquery.Client(project="healthcare-project-496207")
    
    print("Testing access to MIMIC-IV v2.2 vs v3.1 BigQuery tables...")
    
    queries = {
        "v2.2 (Old)": "SELECT subject_id FROM `physionet-data.mimiciv_v2_2_hosp.patients` LIMIT 1",
        "v2.2 (Alias)": "SELECT subject_id FROM `physionet-data.mimiciv_hosp.patients` LIMIT 1",
        "v3.1 (New)": "SELECT subject_id FROM `physionet-data.mimiciv_v3_1_hosp.patients` LIMIT 1"
    }
    
    for name, q in queries.items():
        try:
            print(f"\nTrying {name} table...")
            df = client.query(q).to_dataframe()
            print(f"SUCCESS! You have access to {name}!")
        except Exception as inner_e:
            print(f"Failed: {inner_e}")

except Exception as e:
    print(f"Critical Error: {e}")
