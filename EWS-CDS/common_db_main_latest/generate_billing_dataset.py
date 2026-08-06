import pandas as pd
import os

downloads_dir = r"c:\Users\ASUS\Downloads"
output_file = os.path.join(downloads_dir, "synthetic_billing.csv")

def safe_read(filename):
    path = os.path.join(downloads_dir, filename)
    if os.path.exists(path):
        return pd.read_csv(path)
    return pd.DataFrame()

print("Loading MIMIC CSVs...")
df_meds = safe_read("prescriptions.csv")
df_labs = safe_read("labevents.csv")
df_procs = safe_read("procedures_icd.csv")

# We will aggregate costs by hadm_id
billing_records = []

# Get all unique hadm_ids
all_hadm_ids = set()
if not df_meds.empty and 'hadm_id' in df_meds.columns:
    all_hadm_ids.update(df_meds['hadm_id'].dropna().unique())
if not df_labs.empty and 'hadm_id' in df_labs.columns:
    all_hadm_ids.update(df_labs['hadm_id'].dropna().unique())
if not df_procs.empty and 'hadm_id' in df_procs.columns:
    all_hadm_ids.update(df_procs['hadm_id'].dropna().unique())

print(f"Processing {len(all_hadm_ids)} distinct hospital admissions...")

for hadm_id in all_hadm_ids:
    total_cost = 40000.0  # Base PM-JAY Package Cost
    
    # 1. Process Medications
    if not df_meds.empty and 'hadm_id' in df_meds.columns:
        patient_meds = df_meds[df_meds['hadm_id'] == hadm_id]
        if not patient_meds.empty and 'drug' in patient_meds.columns:
            for drug in patient_meds['drug'].dropna():
                drug_str = str(drug).lower()
                # Explicit Premium Mapping
                if 'propofol' in drug_str or 'fentanyl' in drug_str or 'midazolam' in drug_str:
                    total_cost += 800.0  # Premium ICU drug cost
                else:
                    total_cost += 150.0  # Generic multiplier
                    
    # 2. Process Labs
    if not df_labs.empty and 'hadm_id' in df_labs.columns:
        patient_labs = df_labs[df_labs['hadm_id'] == hadm_id]
        if not patient_labs.empty:
            # Generic multiplier: Rs 300 per lab test
            total_cost += (len(patient_labs) * 300.0)
            
    # 3. Process Procedures
    if not df_procs.empty and 'hadm_id' in df_procs.columns:
        patient_procs = df_procs[df_procs['hadm_id'] == hadm_id]
        if not patient_procs.empty and 'icd_code' in patient_procs.columns:
            for code in patient_procs['icd_code'].dropna():
                if str(code).startswith('3897'):  # Cardiac Cath
                    total_cost += 25000.0
                else:
                    total_cost += 2000.0  # Generic procedure cost
                    
    # We add a flat length-of-stay ward charge (simplified to 3 days for demo)
    total_cost += (3 * 4500.0)
    
    billing_records.append({
        'hadm_id': hadm_id,
        'final_real_cost': total_cost
    })

# Save to CSV
df_billing = pd.DataFrame(billing_records)
df_billing.to_csv(output_file, index=False)
print(f"\nSUCCESS! Generated {len(df_billing)} billing records.")
print(f"File saved to: {output_file}")
print("\nSample Data:")
print(df_billing.head())
