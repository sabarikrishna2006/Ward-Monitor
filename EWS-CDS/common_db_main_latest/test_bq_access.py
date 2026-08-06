from google.cloud import bigquery

try:
    client = bigquery.Client(project="healthcare-project-496207")
    
    print("Testing access to MIMIC-IV v3.1 BigQuery tables...")
    
    queries = [
        "SELECT subject_id FROM `physionet-data.mimiciv_hosp.patients` LIMIT 1",
        "SELECT subject_id FROM `physionet-data.mimic_core.patients` LIMIT 1"
    ]
    
    success = False
    for q in queries:
        try:
            print(f"\nTrying query: {q}")
            df = client.query(q).to_dataframe()
            print("SUCCESS! Data found:")
            print(df)
            success = True
            break
        except Exception as inner_e:
            print(f"Failed: {inner_e}")
            
    if not success:
        print("\nAll attempts failed. PhysioNet is definitely blocking the query or the table names changed.")

except Exception as e:
    print(f"Critical Error: {e}")
