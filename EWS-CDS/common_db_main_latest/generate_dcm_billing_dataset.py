from google.cloud import bigquery
import pandas as pd
import os

# Reset environment credentials to use user login
os.environ.pop('GOOGLE_APPLICATION_CREDENTIALS', None)

try:
    client = bigquery.Client(project="healthcare-project-496207")
    print("Successfully connected to BigQuery!")
    
    # 1. Fetch the Dilated Cardiomyopathy (DCM) Cohort
    cohort_query = """
    SELECT DISTINCT hadm_id, subject_id
    FROM `physionet-data.mimiciv_3_1_hosp.diagnoses_icd` 
    WHERE icd_code IN ('4254', 'I420')
    """
    print("\nFetching DCM Cohort (hadm_id and subject_id)...")
    df_cohort = client.query(cohort_query).to_dataframe()
    dcm_hadm_ids = df_cohort['hadm_id'].dropna().astype(int).tolist()
    print(f"Found {len(dcm_hadm_ids)} distinct DCM hospital admissions.")
    
    if not dcm_hadm_ids:
        print("Error: No DCM patients found in this dataset.")
        exit()
        
    id_list_str = ",".join(map(str, dcm_hadm_ids))
    
    # 2. Extract resource counts from BigQuery
    print("\nExtracting clinical resource counts from BigQuery...")
    
    # Procedures Count & Specific Premium Procedures
    proc_query = f"""
    SELECT hadm_id, 
           COUNT(icd_code) as total_procedures,
           SUM(CASE WHEN icd_code LIKE '3722%' OR icd_code LIKE '3897%' THEN 1 ELSE 0 END) as cardiac_cath_count
    FROM `physionet-data.mimiciv_3_1_hosp.procedures_icd`
    WHERE hadm_id IN ({id_list_str})
    GROUP BY hadm_id
    """
    df_procs = client.query(proc_query).to_dataframe()
    
    # Medications Count & Premium Medications
    med_query = f"""
    SELECT hadm_id, 
           COUNT(drug) as total_medications,
           SUM(CASE WHEN LOWER(drug) LIKE '%propofol%' OR LOWER(drug) LIKE '%fentanyl%' OR LOWER(drug) LIKE '%midazolam%' THEN 1 ELSE 0 END) as premium_meds_count
    FROM `physionet-data.mimiciv_3_1_hosp.prescriptions`
    WHERE hadm_id IN ({id_list_str})
    GROUP BY hadm_id
    """
    df_meds = client.query(med_query).to_dataframe()
    
    # Labs Count
    lab_query = f"""
    SELECT hadm_id, COUNT(itemid) as total_labs
    FROM `physionet-data.mimiciv_3_1_hosp.labevents`
    WHERE hadm_id IN ({id_list_str})
    GROUP BY hadm_id
    """
    df_labs = client.query(lab_query).to_dataframe()
    
    # ICU Stay Length (LOS)
    icu_query = f"""
    SELECT hadm_id, SUM(los) as icu_days
    FROM `physionet-data.mimiciv_3_1_icu.icustays`
    WHERE hadm_id IN ({id_list_str})
    GROUP BY hadm_id
    """
    df_icu = client.query(icu_query).to_dataframe()

    # 3. Merge clinical counts with the cohort list
    print("\nMerging data...")
    df_billing = df_cohort.copy()
    df_billing = df_billing.merge(df_procs, on='hadm_id', how='left')
    df_billing = df_billing.merge(df_meds, on='hadm_id', how='left')
    df_billing = df_billing.merge(df_labs, on='hadm_id', how='left')
    df_billing = df_billing.merge(df_icu, on='hadm_id', how='left')
    
    # Fill missing values with 0
    df_billing.fillna(0, inplace=True)
    
    # 4. Apply Charge Master Prices (Itemized Billing Columns)
    print("Applying Charge Master pricing to create itemized bills...")
    
    # Base Package Cost (Rs. 40,000 for DCM diagnosis + standard 3-day ward rate of Rs. 4,500/day)
    df_billing['base_diagnosis_package_charge'] = 40000.0
    df_billing['standard_ward_charge'] = 3 * 4500.0
    
    # ICU Bed Rate (Rs. 15,000 / day)
    df_billing['icu_stay_charge'] = df_billing['icu_days'] * 15000.0
    
    # Labs Charge (Rs. 300 / test)
    df_billing['laboratory_charge'] = df_billing['total_labs'] * 300.0
    
    # Meds Charge (Rs. 150 / standard prescription)
    df_billing['pharmacy_charge'] = (df_billing['total_medications'] - df_billing['premium_meds_count']) * 150.0
    
    # Premium Meds Charge (Rs. 800 / premium prescription)
    df_billing['premium_meds_charge'] = df_billing['premium_meds_count'] * 800.0
    
    # Cardiac Catheterization Procedure (Rs. 25,000)
    df_billing['cardiac_catheterization_charge'] = df_billing['cardiac_cath_count'] * 25000.0
    
    # Other Procedures (Rs. 2,000 / procedure)
    df_billing['other_procedures_charge'] = (df_billing['total_procedures'] - df_billing['cardiac_cath_count']) * 2000.0
    
    # Sum it all up for the Total Cost
    df_billing['total_hospital_bill'] = \
        df_billing['base_diagnosis_package_charge'] + \
        df_billing['standard_ward_charge'] + \
        df_billing['icu_stay_charge'] + \
        df_billing['laboratory_charge'] + \
        df_billing['pharmacy_charge'] + \
        df_billing['premium_meds_charge'] + \
        df_billing['cardiac_catheterization_charge'] + \
        df_billing['other_procedures_charge']
        
    print("\nSUCCESS! Generated Itemized Billing Dataset.")
    print("Sample Data Rows:")
    print(df_billing[['hadm_id', 'icu_stay_charge', 'laboratory_charge', 'total_hospital_bill']].head())
    
    # Save the billing dataset to Downloads
    output_path = os.path.join(r"c:\Users\ASUS\Downloads", "dcm_patient_billing_dataset.csv")
    df_billing.to_csv(output_path, index=False)
    print(f"\nItemized billing dataset saved successfully to: {output_path}")

except Exception as e:
    print(f"Error generating billing dataset: {e}")
