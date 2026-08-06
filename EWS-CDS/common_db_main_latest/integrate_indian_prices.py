from google.cloud import bigquery
import pandas as pd
import os

os.environ.pop('GOOGLE_APPLICATION_CREDENTIALS', None)

import glob

downloads_dir = r"c:\Users\ASUS\Downloads"

# Dynamically find the latest version of the mapping file (e.g. mapping.csv, mapping_v2.csv, mapping_v3.csv)
mapping_files = glob.glob(os.path.join(downloads_dir, "us_to_indian_medicine_mapping*.csv"))
if not mapping_files:
    print("Error: No mapping file found.")
    exit()
# Sort to get the latest one (longest name or highest v number)
mapping_file = max(mapping_files, key=os.path.getmtime)
print(f"Using latest medication mapping file: {mapping_file}")

billing_output_path = os.path.join(downloads_dir, "dcm_patient_billing_dataset.csv")

try:
    client = bigquery.Client(project="healthcare-project-496207")
    print("Successfully connected to BigQuery!")
    
    # 1. Load the US-to-Indian medicine price mapping we just generated
    print("Loading medication price mapping...")
    df_map = pd.read_csv(mapping_file)
    # Create a quick dictionary lookup: { 'us_medicine_name': price }
    price_dict = dict(zip(df_map['us_medicine_name'].str.lower(), df_map['price_in_rupees']))
    
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
    
    # 3. Pull ALL prescriptions administered to these DCM patients
    print("Fetching all prescriptions for DCM cohort from BigQuery...")
    prescriptions_query = f"""
    SELECT hadm_id, drug
    FROM `physionet-data.mimiciv_3_1_hosp.prescriptions`
    WHERE hadm_id IN ({id_list_str})
    """
    df_prescriptions = client.query(prescriptions_query).to_dataframe()
    print(f"Loaded {len(df_prescriptions)} drug administrations.")
    
    # 4. Map each drug administration to its specific Indian price
    print("Programmatically applying Indian pricing to each prescription...")
    def get_price(drug):
        drug_cleaned = str(drug).strip().lower()
        return price_dict.get(drug_cleaned, 270.53) # Default to calculated mean if unmatched
        
    df_prescriptions['mapped_price'] = df_prescriptions['drug'].apply(get_price)
    
    # 5. Group by hadm_id and sum to get the exact pharmacy charge per patient
    print("Calculating total pharmacy charge per patient admission...")
    df_patient_pharmacy = df_prescriptions.groupby('hadm_id')['mapped_price'].sum().reset_index()
    df_patient_pharmacy = df_patient_pharmacy.rename(columns={'mapped_price': 'pharmacy_charge'})
    
    # 6. Pull other resource counts (Procedures, Labs, ICU days) to rebuild the billing sheet
    print("Fetching procedures, labs, and ICU stays...")
    
    proc_query = f"""
    SELECT hadm_id, 
           COUNT(icd_code) as total_procedures,
           SUM(CASE WHEN icd_code LIKE '3722%' OR icd_code LIKE '3897%' THEN 1 ELSE 0 END) as cardiac_cath_count
    FROM `physionet-data.mimiciv_3_1_hosp.procedures_icd`
    WHERE hadm_id IN ({id_list_str})
    GROUP BY hadm_id
    """
    df_procs = client.query(proc_query).to_dataframe()
    
    lab_query = f"""
    SELECT hadm_id, COUNT(itemid) as total_labs
    FROM `physionet-data.mimiciv_3_1_hosp.labevents`
    WHERE hadm_id IN ({id_list_str})
    GROUP BY hadm_id
    """
    df_labs = client.query(lab_query).to_dataframe()
    
    icu_query = f"""
    SELECT hadm_id, SUM(los) as icu_days
    FROM `physionet-data.mimiciv_3_1_icu.icustays`
    WHERE hadm_id IN ({id_list_str})
    GROUP BY hadm_id
    """
    df_icu = client.query(icu_query).to_dataframe()

    # 7. Merge all columns
    print("Fusing clinical resources and Indian pharmacy charges...")
    df_billing = df_cohort.copy()
    df_billing = df_billing.merge(df_procs, on='hadm_id', how='left')
    df_billing = df_billing.merge(df_patient_pharmacy, on='hadm_id', how='left')
    df_billing = df_billing.merge(df_labs, on='hadm_id', how='left')
    df_billing = df_billing.merge(df_icu, on='hadm_id', how='left')
    df_billing.fillna(0, inplace=True)
    
    # 8. Recalculate the bill using the Indian pharmacy charges
    df_billing['base_diagnosis_package_charge'] = 40000.0
    df_billing['standard_ward_charge'] = 3 * 4500.0
    df_billing['icu_stay_charge'] = df_billing['icu_days'] * 15000.0
    df_billing['laboratory_charge'] = df_billing['total_labs'] * 300.0
    df_billing['cardiac_catheterization_charge'] = df_billing['cardiac_cath_count'] * 25000.0
    df_billing['other_procedures_charge'] = (df_billing['total_procedures'] - df_billing['cardiac_cath_count']) * 2000.0
    
    df_billing['total_hospital_bill'] = \
        df_billing['base_diagnosis_package_charge'] + \
        df_billing['standard_ward_charge'] + \
        df_billing['icu_stay_charge'] + \
        df_billing['laboratory_charge'] + \
        df_billing['pharmacy_charge'] + \
        df_billing['cardiac_catheterization_charge'] + \
        df_billing['other_procedures_charge']
        
    # Save the final dataset
    df_billing.to_csv(billing_output_path, index=False)
    print(f"\nSUCCESS! Rebuilt dcm_patient_billing_dataset.csv with Indian pharmacy pricing.")
    print(f"File saved to: {billing_output_path}")
    print("\nSample Itemized Row:")
    print(df_billing[['hadm_id', 'pharmacy_charge', 'laboratory_charge', 'total_hospital_bill']].head())

    # 9. Retrain ML Model with these new prices
    from sklearn.model_selection import train_test_split
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.metrics import mean_absolute_error, r2_score
    
    # Create flat model training dataset
    X = df_billing[['total_procedures', 'cardiac_cath_count', 'pharmacy_charge', 'total_labs', 'icu_days']]
    y = df_billing['total_hospital_bill']
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    model = RandomForestRegressor(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)
    
    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)
    
    print("\n==================================================")
    print("      UPDATED ML MODEL (WITH INDIAN DRUG PRICES)  ")
    print("==================================================")
    print(f"Mean Absolute Error (MAE): Rs. {mae:,.2f}")
    print(f"R-squared (R2) Score: {r2:.4f}")
    
    # Save training copy
    df_billing.to_csv(os.path.join(downloads_dir, "dcm_billing_ml_data.csv"), index=False)

except Exception as e:
    print(f"Error rebuilding dataset: {e}")
