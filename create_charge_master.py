import pandas as pd
import os

downloads_dir = r"c:\Users\ASUS\Downloads"

def process_procedures():
    file_path = os.path.join(downloads_dir, "dcm_distinct_procedures.csv")
    if not os.path.exists(file_path):
        return
    df = pd.read_csv(file_path)
    
    # Pricing Rules for Procedures based on keywords and Kaggle treatments.csv
    def assign_proc_price(row):
        title = str(row['long_title']).lower()
        code = str(row['icd_code'])
        
        # 1. ECG mapping
        if 'electrocardiogram' in title or 'ecg' in title or 'ekg' in title or code.startswith('895'):
            return 2430.53 # Kaggle ECG Standard
        # 2. X-Ray mapping
        elif 'x-ray' in title or 'radiography' in title or 'arteriography' in title or code.startswith('87') or code.startswith('885'):
            return 2441.10 # Kaggle X-Ray Standard
        # 3. MRI mapping
        elif 'mri' in title or 'magnetic resonance' in title:
            return 3042.59 # Kaggle MRI Standard
        # 4. Physiotherapy mapping
        elif 'physiotherapy' in title or 'rehabilitation' in title or 'physical therapy' in title:
            return 3140.29 # Kaggle Physiotherapy Standard
        # 5. Major Cardiac Surgeries (Bypass, Cath, Pacemaker)
        elif any(k in title for k in ['bypass', 'catheterization', 'pacemaker', 'excision', 'destruction', 'valve', 'ventilation', 'dialysis']):
            return 25000.0 # Major surgical tier
        # 6. Standard ward procedures
        else:
            return 2000.0 # Default procedure cost
            
    df['assigned_price'] = df.apply(assign_proc_price, axis=1)
    df.to_csv(os.path.join(downloads_dir, "procedure_prices.csv"), index=False)
    print("Generated procedure_prices.csv")

def process_medications():
    file_path = os.path.join(downloads_dir, "dcm_distinct_medications.csv")
    if not os.path.exists(file_path):
        return
    df = pd.read_csv(file_path)
    
    # Pricing Rules for Medications based on clinical significance in heart failure
    def assign_med_price(row):
        drug = str(row['drug']).lower()
        
        # 1. Premium Anesthesia / ICU sedatives
        if any(k in drug for k in ['propofol', 'fentanyl', 'midazolam', 'norepinephrine', 'epinephrine', 'dobutamine']):
            return 800.0 # Premium ICU tier
        # 2. IV Fluids / Electrolyte Infusions
        elif any(k in drug for k in ['dextrose', 'sodium chloride', 'potassium chloride', 'magnesium sulfate']):
            return 450.0 # IV hydration tier
        # 3. Core heart failure meds (Beta blockers, ACE inhibitors, diuretics)
        elif any(k in drug for k in ['metoprolol', 'furosemide', 'carvedilol', 'lisinopril', 'spironolactone', 'warfarin']):
            return 150.0 # Cardiac maintenance tier
        # 4. Standard pills / OTC
        else:
            return 100.0 # Standard generic tier
            
    df['assigned_price'] = df.apply(assign_med_price, axis=1)
    df.to_csv(os.path.join(downloads_dir, "medication_prices.csv"), index=False)
    print("Generated medication_prices.csv")

def process_labs():
    file_path = os.path.join(downloads_dir, "dcm_distinct_labs.csv")
    if not os.path.exists(file_path):
        return
    df = pd.read_csv(file_path)
    
    # Pricing Rules for Laboratory Tests
    def assign_lab_price(row):
        label = str(row['label']).lower()
        
        # 1. Critical Cardiac Markers
        if 'troponin' in label or 'bnp' in label or 'ck-mb' in label:
            return 1500.0 # Cardiac panel
        # 2. Renal / Metabolic panels
        elif any(k in label for k in ['creatinine', 'urea nitrogen', 'magnesium', 'calcium', 'sodium', 'potassium', 'chloride', 'bicarbonate']):
            return 450.0 # Renal/Metabolic panel
        # 3. Blood cultures / Microbiology
        elif 'culture' in label or 'blood' in str(row['fluid']).lower():
            return 350.0 # Standard blood panel
        # 4. Basic labs
        else:
            return 250.0 # Standard lab tier
            
    df['assigned_price'] = df.apply(assign_lab_price, axis=1)
    df.to_csv(os.path.join(downloads_dir, "lab_prices.csv"), index=False)
    print("Generated lab_prices.csv")

process_procedures()
process_medications()
process_labs()
print("\nSuccess! Generated all Charge Master Price sheets in Downloads.")
