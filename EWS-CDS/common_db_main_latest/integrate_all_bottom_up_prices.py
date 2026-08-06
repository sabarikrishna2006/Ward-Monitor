from google.cloud import bigquery
import pandas as pd
import os
import glob

os.environ.pop('GOOGLE_APPLICATION_CREDENTIALS', None)

downloads_dir = r"c:\Users\ASUS\Downloads"
billing_output_path = os.path.join(downloads_dir, "dcm_patient_billing_dataset.csv")

# Helper to find the latest versioned mapping files
def get_latest_mapping(pattern, default_name):
    files = glob.glob(os.path.join(downloads_dir, pattern))
    if not files:
        return os.path.join(downloads_dir, default_name)
    return max(files, key=os.path.getmtime)

med_mapping_file = get_latest_mapping("us_to_indian_medicine_mapping*.csv", "us_to_indian_medicine_mapping.csv")
lab_mapping_file = get_latest_mapping("us_to_indian_lab_mapping*.csv", "us_to_indian_lab_mapping.csv")
proc_mapping_file = get_latest_mapping("us_to_indian_procedure_mapping*.csv", "us_to_indian_procedure_mapping.csv")

try:
    client = bigquery.Client(project="healthcare-project-496207")
    print("Successfully connected to BigQuery!")
    
    # 1. Load the US-to-Indian price mappings
    print(f"Loading Medicine mapping: {med_mapping_file}")
    df_med_map = pd.read_csv(med_mapping_file)
    med_price_dict = dict(zip(df_med_map['us_medicine_name'].str.lower(), df_med_map['price_in_rupees']))
    med_mean = df_med_map['price_in_rupees'].mean()
    
    print(f"Loading Lab mapping: {lab_mapping_file}")
    df_lab_map = pd.read_csv(lab_mapping_file)
    lab_price_dict = dict(zip(df_lab_map['us_lab_itemid'], df_lab_map['price_in_rupees']))
    lab_mean = df_lab_map['price_in_rupees'].mean()
    
    print(f"Loading Procedure mapping: {proc_mapping_file}")
    df_proc_map = pd.read_csv(proc_mapping_file)
    # Store procedure code as string since ICD codes can contain letters/leading zeros
    df_proc_map['us_procedure_code'] = df_proc_map['us_procedure_code'].astype(str).str.strip()
    proc_price_dict = dict(zip(df_proc_map['us_procedure_code'], df_proc_map['price_in_rupees']))
    proc_mean = df_proc_map['price_in_rupees'].mean()
    
    # 2. Fetch the DCM cohort hadm_ids
    cohort_query = """
    SELECT DISTINCT hadm_id, subject_id
    FROM `physionet-data.mimiciv_3_1_hosp.diagnoses_icd` 
    WHERE icd_code IN ('4254', 'I420')
    """
    print("\nFetching DCM Cohort hadm_ids...")
    df_cohort = client.query(cohort_query).to_dataframe()
    dcm_hadm_ids = df_cohort['hadm_id'].dropna().astype(int).tolist()
    id_list_str = ",".join(map(str, dcm_hadm_ids))
    
    # 3. Fetch prescriptions and calculate bottom-up Pharmacy Charge
    print("Fetching and pricing prescriptions...")
    prescriptions_query = f"""
    SELECT hadm_id, drug
    FROM `physionet-data.mimiciv_3_1_hosp.prescriptions`
    WHERE hadm_id IN ({id_list_str})
    """
    df_prescriptions = client.query(prescriptions_query).to_dataframe()
    df_prescriptions['mapped_price'] = df_prescriptions['drug'].str.strip().str.lower().map(med_price_dict).fillna(med_mean)
    df_patient_pharmacy = df_prescriptions.groupby('hadm_id')['mapped_price'].sum().reset_index()
    df_patient_pharmacy = df_patient_pharmacy.rename(columns={'mapped_price': 'pharmacy_charge'})
    
    # 4. Fetch lab count per lab item per patient and calculate bottom-up Lab Charge
    print("Fetching and pricing lab events...")
    labs_query = f"""
    SELECT hadm_id, itemid, COUNT(itemid) as lab_count
    FROM `physionet-data.mimiciv_3_1_hosp.labevents`
    WHERE hadm_id IN ({id_list_str})
    GROUP BY hadm_id, itemid
    """
    df_patient_labs = client.query(labs_query).to_dataframe()
    df_patient_labs['item_price'] = df_patient_labs['itemid'].map(lab_price_dict).fillna(lab_mean)
    df_patient_labs['total_item_charge'] = df_patient_labs['item_price'] * df_patient_labs['lab_count']
    df_patient_lab_charges = df_patient_labs.groupby('hadm_id')['total_item_charge'].sum().reset_index()
    df_patient_lab_charges = df_patient_lab_charges.rename(columns={'total_item_charge': 'laboratory_charge'})
    
    # Get total lab count count for clinical features
    df_patient_lab_counts = df_patient_labs.groupby('hadm_id')['lab_count'].sum().reset_index()
    df_patient_lab_counts = df_patient_lab_counts.rename(columns={'lab_count': 'total_labs'})
    
    # 5. Fetch procedure codes per patient and calculate bottom-up Procedure Charge
    print("Fetching and pricing procedures...")
    procs_query = f"""
    SELECT hadm_id, icd_code, COUNT(icd_code) as proc_count
    FROM `physionet-data.mimiciv_3_1_hosp.procedures_icd`
    WHERE hadm_id IN ({id_list_str})
    GROUP BY hadm_id, icd_code
    """
    df_patient_procs = client.query(procs_query).to_dataframe()
    df_patient_procs['icd_code'] = df_patient_procs['icd_code'].astype(str).str.strip()
    df_patient_procs['proc_price'] = df_patient_procs['icd_code'].map(proc_price_dict).fillna(proc_mean)
    df_patient_procs['total_proc_charge'] = df_patient_procs['proc_price'] * df_patient_procs['proc_count']
    df_patient_proc_charges = df_patient_procs.groupby('hadm_id')['total_proc_charge'].sum().reset_index()
    df_patient_proc_charges = df_patient_proc_charges.rename(columns={'total_proc_charge': 'procedures_charge'})
    
    # Get total procedure and cardiac cath counts for clinical features
    df_patient_proc_counts = df_patient_procs.groupby('hadm_id')['proc_count'].sum().reset_index()
    df_patient_proc_counts = df_patient_proc_counts.rename(columns={'proc_count': 'total_procedures'})
    
    df_patient_cath_counts = df_patient_procs[df_patient_procs['icd_code'].str.startswith(('3722', '3723', '3897'))].groupby('hadm_id')['proc_count'].sum().reset_index()
    df_patient_cath_counts = df_patient_cath_counts.rename(columns={'proc_count': 'cardiac_cath_count'})
    
    # 6. Fetch ICU stay durations
    print("Fetching ICU stays...")
    icu_query = f"""
    SELECT hadm_id, SUM(los) as icu_days
    FROM `physionet-data.mimiciv_3_1_icu.icustays`
    WHERE hadm_id IN ({id_list_str})
    GROUP BY hadm_id
    """
    df_icu = client.query(icu_query).to_dataframe()
    
    # 7. Merge everything into the final billing dataset
    print("Fusing clinical resources and bottom-up charges...")
    df_billing = df_cohort.copy()
    df_billing = df_billing.merge(df_patient_pharmacy, on='hadm_id', how='left')
    df_billing = df_billing.merge(df_patient_lab_charges, on='hadm_id', how='left')
    df_billing = df_billing.merge(df_patient_lab_counts, on='hadm_id', how='left')
    df_billing = df_billing.merge(df_patient_proc_charges, on='hadm_id', how='left')
    df_billing = df_billing.merge(df_patient_proc_counts, on='hadm_id', how='left')
    df_billing = df_billing.merge(df_patient_cath_counts, on='hadm_id', how='left')
    df_billing = df_billing.merge(df_icu, on='hadm_id', how='left')
    df_billing.fillna(0, inplace=True)
    
    # 8. Re-calculate the total hospital bill using the detailed, itemized charges
    df_billing['base_diagnosis_package_charge'] = 40000.0
    df_billing['standard_ward_charge'] = 3 * 4500.0
    df_billing['icu_stay_charge'] = df_billing['icu_days'] * 15000.0
    
    df_billing['total_hospital_bill'] = \
        df_billing['base_diagnosis_package_charge'] + \
        df_billing['standard_ward_charge'] + \
        df_billing['icu_stay_charge'] + \
        df_billing['laboratory_charge'] + \
        df_billing['pharmacy_charge'] + \
        df_billing['procedures_charge']
        
    # Save the final dataset
    df_billing.to_csv(billing_output_path, index=False)
    print(f"\nSUCCESS! Rebuilt dcm_patient_billing_dataset.csv with bottom-up Indian/Kaggle pricing.")
    print(f"File saved to: {billing_output_path}")
    print("\nSample Itemized Row:")
    print(df_billing[['hadm_id', 'pharmacy_charge', 'laboratory_charge', 'procedures_charge', 'total_hospital_bill']].head())

    # 9. Retrain ML Model with these new bottom-up prices
    from sklearn.model_selection import train_test_split
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.metrics import mean_absolute_error, r2_score
    
    # Create flat model training dataset
    X = df_billing[['total_procedures', 'cardiac_cath_count', 'pharmacy_charge', 'laboratory_charge', 'procedures_charge', 'total_labs', 'icu_days']]
    y = df_billing['total_hospital_bill']
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    model = RandomForestRegressor(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)
    
    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)
    
    print("\n==================================================")
    print("   UPDATED ML MODEL (BOTTOM-UP LABS & PROCEDURES) ")
    print("==================================================")
    print(f"Mean Absolute Error (MAE): Rs. {mae:,.2f}")
    print(f"R-squared (R2) Score: {r2:.4f}")
    
    # Save training copy
    df_billing.to_csv(os.path.join(downloads_dir, "dcm_billing_ml_data.csv"), index=False)

except Exception as e:
    print(f"Error rebuilding dataset: {e}")
