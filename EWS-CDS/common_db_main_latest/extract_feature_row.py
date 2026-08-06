import pandas as pd
import os

downloads_dir = r"c:\Users\ASUS\Downloads"
target_hadm_id = 22202271.0 # The user's requested ID

def safe_read(filename):
    path = os.path.join(downloads_dir, filename)
    if os.path.exists(path):
        return pd.read_csv(path)
    return pd.DataFrame()

print("Loading local MIMIC data...")
df_meds = safe_read("prescriptions.csv")
df_labs = safe_read("labevents.csv")
df_procs = safe_read("procedures_icd.csv")

# If the target ID doesn't exist in our small local subset, pick the first one available
available_ids = set()
if not df_labs.empty: available_ids.update(df_labs['hadm_id'].dropna().unique())
if not df_meds.empty: available_ids.update(df_meds['hadm_id'].dropna().unique())

if target_hadm_id not in available_ids and available_ids:
    target_hadm_id = list(available_ids)[0]
    print(f"\nNote: Requested ID not in local subset. Using available ID: {target_hadm_id}")

print(f"\n--- Extracting ML Feature Row for hadm_id: {target_hadm_id} ---")

# Initialize features
features = {
    'hadm_id': target_hadm_id,
    'Total_Labs_Count': 0,
    'Total_Meds_Count': 0,
    'Had_Premium_Med_Propofol': 0,
    'Had_Premium_Med_Fentanyl': 0,
    'Had_Premium_Med_Midazolam': 0,
    'Had_Procedure_Cardiac_Cath': 0,
}

# Extract Labs
if not df_labs.empty and 'hadm_id' in df_labs.columns:
    patient_labs = df_labs[df_labs['hadm_id'] == target_hadm_id]
    features['Total_Labs_Count'] = len(patient_labs)

# Extract Meds
if not df_meds.empty and 'hadm_id' in df_meds.columns:
    patient_meds = df_meds[df_meds['hadm_id'] == target_hadm_id]
    features['Total_Meds_Count'] = len(patient_meds)
    if not patient_meds.empty and 'drug' in patient_meds.columns:
        drugs = patient_meds['drug'].dropna().astype(str).str.lower().tolist()
        if any('propofol' in d for d in drugs): features['Had_Premium_Med_Propofol'] = 1
        if any('fentanyl' in d for d in drugs): features['Had_Premium_Med_Fentanyl'] = 1
        if any('midazolam' in d for d in drugs): features['Had_Premium_Med_Midazolam'] = 1

# Extract Procedures
if not df_procs.empty and 'hadm_id' in df_procs.columns:
    patient_procs = df_procs[df_procs['hadm_id'] == target_hadm_id]
    if not patient_procs.empty and 'icd_code' in patient_procs.columns:
        codes = patient_procs['icd_code'].dropna().astype(str).tolist()
        if any(c.startswith('3897') for c in codes): features['Had_Procedure_Cardiac_Cath'] = 1

# Calculate Target Cost (For demonstration)
final_cost = 40000.0 + (3 * 4500.0) # Base + Ward
final_cost += features['Total_Labs_Count'] * 300.0
final_cost += features['Total_Meds_Count'] * 150.0
if features['Had_Premium_Med_Propofol']: final_cost += 800.0
if features['Had_Premium_Med_Fentanyl']: final_cost += 800.0
if features['Had_Premium_Med_Midazolam']: final_cost += 800.0
if features['Had_Procedure_Cardiac_Cath']: final_cost += 25000.0

# Print the final ML Row
print("\n[ML Feature Columns 'X']")
for k, v in features.items():
    print(f"  {k}: {v}")

print(f"\n[Target Column 'Y']")
print(f"  Final_Real_Cost: ₹{final_cost:,.2f}")
