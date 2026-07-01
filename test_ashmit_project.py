from google.cloud import bigquery

try:
    # We are using YOUR personal project now, NOT Gautam Sir's!
    client = bigquery.Client(project="mimic-bq-ashmit-498605")
    
    print("Successfully connected using YOUR project (mimic-bq-ashmit-498605)!")
    
    # Let's try both the old and new table names just to be 100% sure
    queries = {
        "v3.1 explicit": "SELECT COUNT(*) FROM `physionet-data.mimiciv_v3_1_hosp.diagnoses_icd`",
        "Standard": "SELECT COUNT(*) FROM `physionet-data.mimiciv_hosp.diagnoses_icd`"
    }
    
    for name, q in queries.items():
        try:
            print(f"\nTrying {name} format...")
            df = client.query(q).to_dataframe()
            print(f"SUCCESS! The '{name}' table format is the correct one!")
            break
        except Exception as e:
            print(f"Failed: {e}")

except Exception as e:
    print(f"Critical Error: {e}")
