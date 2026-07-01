from google.cloud import bigquery
import pandas as pd
import numpy as np
import os
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score

# Reset environment credentials to use user login
os.environ.pop('GOOGLE_APPLICATION_CREDENTIALS', None)

try:
    client = bigquery.Client(project="healthcare-project-496207")
    print("Successfully connected to BigQuery!")
    
    # 1. Fetch the Dilated Cardiomyopathy (DCM) Cohort
    # ICD-9 Congestive/Dilated Cardiomyopathy is '4254'
    # ICD-10 Dilated Cardiomyopathy is 'I420'
    cohort_query = """
    SELECT DISTINCT hadm_id 
    FROM `physionet-data.mimiciv_3_1_hosp.diagnoses_icd` 
    WHERE icd_code IN ('4254', 'I420')
    """
    print("\nFetching DCM Cohort hadm_ids...")
    df_cohort = client.query(cohort_query).to_dataframe()
    dcm_hadm_ids = df_cohort['hadm_id'].dropna().astype(int).tolist()
    print(f"Found {len(dcm_hadm_ids)} distinct DCM hospital admissions.")
    
    if not dcm_hadm_ids:
        print("Error: No DCM patients found in this dataset.")
        exit()
        
    # Format list of IDs for SQL query
    id_list_str = ",".join(map(str, dcm_hadm_ids))
    
    # 2. Extract Features from BigQuery for this Cohort
    print("\nExtracting features from BigQuery...")
    
    # Query for Procedures
    proc_query = f"""
    SELECT hadm_id, COUNT(icd_code) as proc_count,
           MAX(CASE WHEN icd_code LIKE '3722%' OR icd_code LIKE '3897%' THEN 1 ELSE 0 END) as has_cardiac_cath
    FROM `physionet-data.mimiciv_3_1_hosp.procedures_icd`
    WHERE hadm_id IN ({id_list_str})
    GROUP BY hadm_id
    """
    df_procs = client.query(proc_query).to_dataframe()
    
    # Query for Medications
    med_query = f"""
    SELECT hadm_id, COUNT(drug) as med_count,
           MAX(CASE WHEN LOWER(drug) LIKE '%propofol%' OR LOWER(drug) LIKE '%fentanyl%' OR LOWER(drug) LIKE '%midazolam%' THEN 1 ELSE 0 END) as has_premium_med
    FROM `physionet-data.mimiciv_3_1_hosp.prescriptions`
    WHERE hadm_id IN ({id_list_str})
    GROUP BY hadm_id
    """
    df_meds = client.query(med_query).to_dataframe()
    
    # Query for Labs
    lab_query = f"""
    SELECT hadm_id, COUNT(itemid) as lab_count
    FROM `physionet-data.mimiciv_3_1_hosp.labevents`
    WHERE hadm_id IN ({id_list_str})
    GROUP BY hadm_id
    """
    df_labs = client.query(lab_query).to_dataframe()
    
    # Query for ICU days
    icu_query = f"""
    SELECT hadm_id, SUM(los) as icu_days
    FROM `physionet-data.mimiciv_3_1_icu.icustays`
    WHERE hadm_id IN ({id_list_str})
    GROUP BY hadm_id
    """
    df_icu = client.query(icu_query).to_dataframe()

    # 3. Merge Features into flat training table
    print("\nMerging features...")
    df_features = pd.DataFrame({'hadm_id': dcm_hadm_ids})
    df_features = df_features.merge(df_procs, on='hadm_id', how='left')
    df_features = df_features.merge(df_meds, on='hadm_id', how='left')
    df_features = df_features.merge(df_labs, on='hadm_id', how='left')
    df_features = df_features.merge(df_icu, on='hadm_id', how='left')
    
    # Fill missing values with 0
    df_features.fillna(0, inplace=True)
    
    # 4. Generate Target Billing Y values
    print("Calculating synthetic cost (Target Y)...")
    # Base package cost = Rs 40,000 + Standard Ward (3 days * Rs 4500)
    base_cost = 40000.0 + (3 * 4500.0)
    
    df_features['final_real_cost'] = base_cost \
        + (df_features['icu_days'] * 15000.0) \
        + (df_features['lab_count'] * 300.0) \
        + (df_features['med_count'] * 150.0) \
        + (df_features['has_premium_med'] * 800.0) \
        + (df_features['has_cardiac_cath'] * 25000.0)
        
    print("\nSample Training Data (X + Y):")
    print(df_features.head())
    
    # 5. Train ML Model
    X = df_features[['proc_count', 'has_cardiac_cath', 'med_count', 'has_premium_med', 'lab_count', 'icu_days']]
    y = df_features['final_real_cost']
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    print(f"\nTraining Random Forest Regressor on {len(X_train)} samples...")
    model = RandomForestRegressor(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)
    
    # 6. Evaluate Model
    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)
    
    print("\n--- MODEL PERFORMANCE ---")
    print(f"Mean Absolute Error (MAE): Rs. {mae:,.2f}")
    print(f"R-squared (R2) Score: {r2:.4f}")
    
    # Save the dataset to Downloads
    output_path = os.path.join(r"c:\Users\ASUS\Downloads", "dcm_billing_ml_data.csv")
    df_features.to_csv(output_path, index=False)
    print(f"\nDataset saved successfully to: {output_path}")

except Exception as e:
    print(f"Error training model: {e}")
