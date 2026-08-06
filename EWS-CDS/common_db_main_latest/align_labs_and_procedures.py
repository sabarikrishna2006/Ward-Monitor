import pandas as pd
import os
import re

downloads_dir = r"c:\Users\ASUS\Downloads"
labs_file = os.path.join(downloads_dir, "dcm_distinct_labs.csv")
procs_file = os.path.join(downloads_dir, "dcm_distinct_procedures.csv")
treatments_file = os.path.join(downloads_dir, "treatments.csv")
pmjay_file = os.path.join(downloads_dir, "pmjay_assam_procedures.csv")

labs_output = os.path.join(downloads_dir, "us_to_indian_lab_mapping.csv")
procs_output = os.path.join(downloads_dir, "us_to_indian_procedure_mapping.csv")

try:
    print("Loading treatments database (Kaggle) for labs...")
    df_treat = pd.read_csv(treatments_file)
    treat_mean = float(df_treat['cost'].mean())
    print(f"Calculated treatments mean price: Rs. {treat_mean:.2f}")
    
    # Extract standard prices from Kaggle treatments
    ecg_price = float(df_treat[df_treat['treatment_type'] == 'ECG']['cost'].mean())
    mri_price = float(df_treat[df_treat['treatment_type'] == 'MRI']['cost'].mean())
    xray_price = float(df_treat[df_treat['treatment_type'] == 'X-Ray']['cost'].mean())
    physio_price = float(df_treat[df_treat['treatment_type'] == 'Physiotherapy']['cost'].mean())
    chemo_price = float(df_treat[df_treat['treatment_type'] == 'Chemotherapy']['cost'].mean())
    
    # Load PMJAY Assam for procedures
    print("Loading PMJAY Assam database for procedures...")
    df_pmjay = pd.read_csv(pmjay_file)
    df_pmjay['clean_price'] = df_pmjay['Package Price'].astype(str).str.replace(',', '', regex=False).str.extract(r'(\d+)').astype(float)
    df_pmjay = df_pmjay.dropna(subset=['AB PM - JAY Procedure Name', 'clean_price'])
    pmjay_mean = float(df_pmjay['clean_price'].mean())
    print(f"Calculated PMJAY Assam mean price: Rs. {pmjay_mean:.2f}")

    # ----------------------------------------------------
    # 1. ALIGN LABS
    # ----------------------------------------------------
    print("\nAligning Labs using Kaggle...")
    df_labs = pd.read_csv(labs_file)
    labs_mapping = []
    
    for _, row in df_labs.iterrows():
        itemid = row['itemid']
        label = str(row['label']).strip()
        label_lower = label.lower()
        fluid = str(row['fluid'])
        
        price = treat_mean
        source = "Kaggle Dataset Mean Fallback"
        
        if 'ecg' in label_lower or 'electrocardiogram' in label_lower:
            price = ecg_price
            source = "Kaggle Dataset Match"
        elif 'x-ray' in label_lower or 'radiography' in label_lower:
            price = xray_price
            source = "Kaggle Dataset Match"
        elif 'mri' in label_lower:
            price = mri_price
            source = "Kaggle Dataset Match"
            
        indian_name = f"{label} Test ({fluid})"
        if 'potassium' in label_lower:
            indian_name = f"Serum Potassium Level ({fluid})"
        elif 'sodium' in label_lower:
            indian_name = f"Serum Sodium Level ({fluid})"
        elif 'creatinine' in label_lower:
            indian_name = f"Serum Creatinine Test ({fluid})"
        elif 'troponin' in label_lower:
            indian_name = f"Troponin I / T Cardiac Marker ({fluid})"
        elif 'bnp' in label_lower:
            indian_name = f"B-Type Natriuretic Peptide Test ({fluid})"
            
        labs_mapping.append({
            'us_lab_itemid': itemid,
            'us_lab_label': label,
            'indian_lab_equivalent': indian_name,
            'price_in_rupees': price,
            'pricing_source': source
        })
        
    df_labs_map = pd.DataFrame(labs_mapping)
    
    success = False
    idx = 1
    out_labs = labs_output
    while not success:
        try:
            df_labs_map.to_csv(out_labs, index=False)
            print(f"SUCCESS! Aligned {len(df_labs_map)} labs to: {out_labs}")
            success = True
        except PermissionError:
            idx += 1
            out_labs = os.path.join(downloads_dir, f"us_to_indian_lab_mapping_v{idx}.csv")
            
    # ----------------------------------------------------
    # 2. ALIGN PROCEDURES
    # ----------------------------------------------------
    print("\nAligning Procedures using PMJAY Assam...")
    df_procs = pd.read_csv(procs_file)
    procs_mapping = []
    
    for _, row in df_procs.iterrows():
        code = row['icd_code']
        title = str(row['long_title']).strip()
        title_lower = title.lower()
        
        price = pmjay_mean
        source = "PMJAY Assam Mean Fallback"
        
        indian_name = title
        
        # Try to find a match in PMJAY
        # We will split the title into words (min 4 chars) and see if any word matches
        words = [w for w in re.split(r'\W+', title_lower) if len(w) >= 4]
        match_found = False
        if words:
            # Create a regex to match any of the significant words
            pattern = '|'.join(words)
            mask = df_pmjay['AB PM - JAY Procedure Name'].str.contains(pattern, case=False, na=False)
            matches = df_pmjay[mask]
            
            if not matches.empty:
                # Take the first match for simplicity
                first_match = matches.iloc[0]
                price = first_match['clean_price']
                indian_name = first_match['AB PM - JAY Procedure Name']
                source = "PMJAY Assam Dataset Match"
                match_found = True
        
        if not match_found:
            if 'catheterization' in title_lower:
                indian_name = "Cardiac Catheterization (Cath Lab Procedure)"
            elif 'bypass' in title_lower:
                indian_name = "Coronary Artery Bypass Graft (CABG Surgery)"
            elif 'ventilation' in title_lower:
                indian_name = "ICU Mechanical Ventilation Support"
            elif 'pacemaker' in title_lower:
                indian_name = "Cardiac Pacemaker Implantation"
            
        procs_mapping.append({
            'us_procedure_code': code,
            'us_procedure_title': title,
            'indian_procedure_equivalent': indian_name,
            'price_in_rupees': price,
            'pricing_source': source
        })
        
    df_procs_map = pd.DataFrame(procs_mapping)
    
    success = False
    idx = 1
    out_procs = procs_output
    while not success:
        try:
            df_procs_map.to_csv(out_procs, index=False)
            print(f"SUCCESS! Aligned {len(df_procs_map)} procedures to: {out_procs}")
            success = True
        except PermissionError:
            idx += 1
            out_procs = os.path.join(downloads_dir, f"us_to_indian_procedure_mapping_v{idx}.csv")

    print("\nSample Lab Mappings:")
    print(df_labs_map.head(3).to_string(index=False))
    print("\nSample Procedure Mappings:")
    print(df_procs_map.head(3).to_string(index=False))

except Exception as e:
    print(f"Error: {e}")
