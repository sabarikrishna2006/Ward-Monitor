from google.cloud import bigquery
import pandas as pd
import os

os.environ.pop('GOOGLE_APPLICATION_CREDENTIALS', None)

client = bigquery.Client(project="healthcare-project-496207")
print("Connected to BigQuery.")

# 1. Select 5 Cardiac Patients
q_cardiac = """
SELECT DISTINCT hadm_id 
FROM `physionet-data.mimiciv_3_1_hosp.services`
WHERE curr_service IN ('CMED', 'CSURG')
LIMIT 5
"""
cardiac_ids = client.query(q_cardiac).to_dataframe()['hadm_id'].tolist()

# 2. Select 3 Surgical Patients (excluding already picked)
q_surg = f"""
SELECT DISTINCT hadm_id 
FROM `physionet-data.mimiciv_3_1_hosp.services`
WHERE curr_service IN ('SURG', 'NSURG', 'TSURG', 'ORTHO', 'VSURG')
AND hadm_id NOT IN ({','.join(map(str, cardiac_ids))})
LIMIT 3
"""
surg_ids = client.query(q_surg).to_dataframe()['hadm_id'].tolist()

# 3. Select 2 Complex ICU Patients (highest length of stay)
picked = cardiac_ids + surg_ids
q_icu = f"""
SELECT hadm_id, MAX(los) as max_los
FROM `physionet-data.mimiciv_3_1_icu.icustays`
WHERE hadm_id NOT IN ({','.join(map(str, picked))})
GROUP BY hadm_id
ORDER BY max_los DESC
LIMIT 2
"""
icu_ids = client.query(q_icu).to_dataframe()['hadm_id'].tolist()

final_cohort = cardiac_ids + surg_ids + icu_ids
id_list_str = ",".join(map(str, final_cohort))

print(f"Selected Cohort of {len(final_cohort)} patients:")
print(f"Cardiac: {cardiac_ids}")
print(f"Surgical: {surg_ids}")
print(f"ICU/Complex: {icu_ids}")

print("\nExtracting distinct procedures...")
proc_query = f"""
SELECT DISTINCT p.icd_code, d.long_title
FROM `physionet-data.mimiciv_3_1_hosp.procedures_icd` p
LEFT JOIN `physionet-data.mimiciv_3_1_hosp.d_icd_procedures` d ON p.icd_code = d.icd_code
WHERE p.hadm_id IN ({id_list_str})
"""
df_procs = client.query(proc_query).to_dataframe()

print("Extracting distinct medications...")
med_query = f"""
SELECT DISTINCT drug
FROM `physionet-data.mimiciv_3_1_hosp.prescriptions`
WHERE hadm_id IN ({id_list_str})
"""
df_meds = client.query(med_query).to_dataframe()

print("Extracting distinct labs...")
lab_query = f"""
SELECT DISTINCT l.itemid, d.label, d.fluid
FROM `physionet-data.mimiciv_3_1_hosp.labevents` l
LEFT JOIN `physionet-data.mimiciv_3_1_hosp.d_labitems` d ON l.itemid = d.itemid
WHERE l.hadm_id IN ({id_list_str})
"""
df_labs = client.query(lab_query).to_dataframe()

dl = r"c:\Users\ASUS\Downloads"
df_procs.to_csv(os.path.join(dl, "ab_test_procedures.csv"), index=False)
df_meds.to_csv(os.path.join(dl, "ab_test_medications.csv"), index=False)
df_labs.to_csv(os.path.join(dl, "ab_test_labs.csv"), index=False)

print(f"\nExtracted for A/B Test:")
print(f"- {len(df_procs)} unique procedures")
print(f"- {len(df_meds)} unique medications")
print(f"- {len(df_labs)} unique labs")
