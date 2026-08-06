from google.cloud import bigquery
import os

os.environ.pop('GOOGLE_APPLICATION_CREDENTIALS', None)

try:
    client = bigquery.Client(project="healthcare-project-496207")
    
    query = """
    SELECT icd_code, icd_version, long_title 
    FROM `physionet-data.mimiciv_3_1_hosp.d_icd_diagnoses` 
    WHERE icd_code IN ('4254', 'I420')
    """
    
    df = client.query(query).to_dataframe()
    print("Official Medical Diagnosis Codes for Dilated Cardiomyopathy:")
    print(df.to_string(index=False))

except Exception as e:
    print(f"Error: {e}")
