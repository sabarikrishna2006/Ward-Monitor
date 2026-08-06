from google.cloud import bigquery
import pandas as pd
import os

# Reset environment credentials to use user login
os.environ.pop('GOOGLE_APPLICATION_CREDENTIALS', None)

try:
    client = bigquery.Client(project="healthcare-project-496207")
    print("Successfully connected to BigQuery!")
    
    # 1. Get the DCM cohort hadm_ids
    cohort_query = """
    SELECT DISTINCT hadm_id 
    FROM `physionet-data.mimiciv_3_1_hosp.diagnoses_icd` 
    WHERE icd_code IN ('4254', 'I420')
    """
    print("\nFetching DCM Cohort hadm_ids...")
    df_cohort = client.query(cohort_query).to_dataframe()
    dcm_hadm_ids = df_cohort['hadm_id'].dropna().astype(int).tolist()
    print(f"Found {len(dcm_hadm_ids)} distinct DCM hospital admissions.")
    
    id_list_str = ",".join(map(str, dcm_hadm_ids))
    
    # 2. Get distinct Procedures (with descriptions if possible, otherwise we join d_icd_procedures)
    print("\nFetching distinct procedures for DCM cohort...")
    proc_query = f"""
    SELECT p.icd_code, d.long_title, COUNT(*) as occurrence_count
    FROM `physionet-data.mimiciv_3_1_hosp.procedures_icd` p
    LEFT JOIN `physionet-data.mimiciv_3_1_hosp.d_icd_procedures` d ON p.icd_code = d.icd_code
    WHERE p.hadm_id IN ({id_list_str})
    GROUP BY p.icd_code, d.long_title
    ORDER BY occurrence_count DESC
    """
    df_procs = client.query(proc_query).to_dataframe()
    print(f"Found {len(df_procs)} distinct procedures.")
    
    # 3. Get distinct Medications (from prescriptions)
    print("\nFetching distinct medications for DCM cohort...")
    med_query = f"""
    SELECT drug, COUNT(*) as occurrence_count
    FROM `physionet-data.mimiciv_3_1_hosp.prescriptions`
    WHERE hadm_id IN ({id_list_str})
    GROUP BY drug
    ORDER BY occurrence_count DESC
    """
    df_meds = client.query(med_query).to_dataframe()
    print(f"Found {len(df_meds)} distinct medications.")
    
    # 4. Get distinct Labs (with names from d_labitems)
    print("\nFetching distinct labs for DCM cohort...")
    lab_query = f"""
    SELECT l.itemid, d.label, d.fluid, COUNT(*) as occurrence_count
    FROM `physionet-data.mimiciv_3_1_hosp.labevents` l
    LEFT JOIN `physionet-data.mimiciv_3_1_hosp.d_labitems` d ON l.itemid = d.itemid
    WHERE l.hadm_id IN ({id_list_str})
    GROUP BY l.itemid, d.label, d.fluid
    ORDER BY occurrence_count DESC
    """
    df_labs = client.query(lab_query).to_dataframe()
    print(f"Found {len(df_labs)} distinct labs.")
    
    # Save the distinct items to separate CSVs for review
    downloads_dir = r"c:\Users\ASUS\Downloads"
    
    df_procs.to_csv(os.path.join(downloads_dir, "dcm_distinct_procedures.csv"), index=False)
    df_meds.to_csv(os.path.join(downloads_dir, "dcm_distinct_medications.csv"), index=False)
    df_labs.to_csv(os.path.join(downloads_dir, "dcm_distinct_labs.csv"), index=False)
    
    print("\n==================================================")
    print("TOP 10 MOST FREQUENT PROCEDURES FOR DCM COHORT:")
    print("==================================================")
    print(df_procs.head(10).to_string(index=False))
    
    print("\n==================================================")
    print("TOP 10 MOST FREQUENT MEDICATIONS FOR DCM COHORT:")
    print("==================================================")
    print(df_meds.head(10).to_string(index=False))
    
    print("\n==================================================")
    print("TOP 10 MOST FREQUENT LABS FOR DCM COHORT:")
    print("==================================================")
    print(df_labs.head(10).to_string(index=False))
    
    print(f"\nAll files saved successfully to your Downloads folder!")

except Exception as e:
    print(f"Error fetching distinct items: {e}")
