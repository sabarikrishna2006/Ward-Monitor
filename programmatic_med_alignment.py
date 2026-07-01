import pandas as pd
import os
import re

downloads_dir = r"c:\Users\ASUS\Downloads"
mimic_meds_file = os.path.join(downloads_dir, "dcm_distinct_medications.csv")
indian_meds_file = os.path.join(downloads_dir, "indian_medicine_data.csv")
mapping_output = os.path.join(downloads_dir, "us_to_indian_medicine_mapping.csv")

def clean_drug_name(name):
    name = str(name).lower()
    
    # 1. Strip standard packaging text in parentheses
    name = re.sub(r'\(.*\)', '', name)
    
    # 2. Strip specific percentage indicators (like 0.9%, 5%, 0.45%) cleanly without deleting the rest of the text
    name = re.sub(r'\b\d+(\.\d+)?\s*%', '', name)
    
    # 3. Strip dosage numbers and units (like 250mg, 10mcg, 5ml, 40iu) cleanly
    name = re.sub(r'\b\d+(\.\d+)?\s*(mg|ml|mcg|g|u-100|unit|units|eq|meq|pkt|syr|vial|ampoule|injection|tablet|capsule|ointment|cream|solution|suspension|spray|patch|flush|dilution|bag|mini bag)\b', '', name)
    
    # 4. Remove generic standalone numbers
    name = re.sub(r'\b\d+(\.\d+)?\b', '', name)
    
    # 5. Clean up any extra whitespaces
    name = re.sub(r'\s+', ' ', name)
    name = name.strip()
    
    return name

try:
    print("Loading MIMIC distinct medications...")
    df_mimic = pd.read_csv(mimic_meds_file)
    print("Loading Indian Medicine Database (32MB)...")
    df_indian = pd.read_csv(indian_meds_file)
    
    # Clean Indian column names
    df_indian.columns = [c.encode('ascii', 'ignore').decode('ascii') for c in df_indian.columns]
    df_indian = df_indian.rename(columns={'price()': 'price'})
    
    # Pre-clean the Indian database columns for fast matching
    print("Pre-processing Indian database for fast search...")
    df_indian['comp1_lower'] = df_indian['short_composition1'].str.lower().fillna('')
    df_indian['comp2_lower'] = df_indian['short_composition2'].str.lower().fillna('')
    df_indian['name_lower'] = df_indian['name'].str.lower().fillna('')
    
    mapping_data = []
    total_drugs = len(df_mimic)
    matched_count = 0
    
    print(f"\nProgrammatically aligning {total_drugs} drugs...")
    
    for idx, row in df_mimic.iterrows():
        us_name = str(row['drug'])
        cleaned_us = clean_drug_name(us_name)
        
        if len(cleaned_us) < 3: # skip short noise
            mapping_data.append({
                'us_medicine_name': us_name,
                'indian_brand_equivalent': "None (Short name noise)",
                'price_in_rupees': 270.53,
                'pricing_source': "Synthetic - Short name noise fallback"
            })
            continue
            
        # Search: 
        # 1. First in short_composition1
        # 2. Then in short_composition2 (New!)
        # 3. Finally in name (Brand name)
        matches = df_indian[
            df_indian['comp1_lower'].str.contains(cleaned_us, regex=False) |
            df_indian['comp2_lower'].str.contains(cleaned_us, regex=False)
        ]
        
        if matches.empty:
            matches = df_indian[df_indian['name_lower'].str.contains(cleaned_us, regex=False)]
            
        if not matches.empty:
            # Sort matches so we get active/available drugs (prefer non-discontinued if possible)
            matches_sorted = matches.sort_values(by='Is_discontinued', ascending=True)
            best_match = matches_sorted.iloc[0]
            
            mapping_data.append({
                'us_medicine_name': us_name,
                'indian_brand_equivalent': best_match['name'],
                'price_in_rupees': float(best_match['price']),
                'pricing_source': "Indian Medicine Dataset Match"
            })
            matched_count += 1
        else:
            # If not found in the dataset, assign the calculated mean price of the dataset
            mapping_data.append({
                'us_medicine_name': us_name,
                'indian_brand_equivalent': us_name + " (Generic Equivalent)",
                'price_in_rupees': 270.53,
                'pricing_source': "Dataset Mean Price Fallback"
            })
            
    # Save the mapping CSV with a robust increment check if Excel locks it
    df_map = pd.DataFrame(mapping_data)
    success = False
    idx = 1
    out_file = mapping_output
    
    while not success:
        try:
            df_map.to_csv(out_file, index=False)
            print(f"\nSUCCESS! Programmatically aligned {matched_count} out of {total_drugs} medications ({matched_count/total_drugs*100:.1f}%)")
            print(f"File saved to: {out_file}")
            success = True
        except PermissionError:
            idx += 1
            out_file = os.path.join(downloads_dir, f"us_to_indian_medicine_mapping_v{idx}.csv")
            if idx > 15: # Safety break
                print("Error: Too many locked files. Please close Excel.")
                break
                
    print("\nSample Programmatic Mappings:")
    print(df_map.head(15).to_string(index=False))

    # Generate the updated markdown ledger
    ledger_path = r"C:\Users\ASUS\.gemini\antigravity\brain\5896c730-5fa9-4289-8c14-6ad8dc112519\medication_mapping_ledger.md"
    with open(ledger_path, "w") as f:
        f.write("# Programmatic DCM Medication Price Alignment Ledger\n\n")
        f.write(f"Successfully aligned **{matched_count}** out of **{total_drugs}** clinical drug names (**{matched_count/total_drugs*100:.1f}%**) programmatically to the Indian Medicine Dataset.\n\n")
        f.write("## Sample Programmatic Mappings\n\n")
        f.write("| US Medicine Name (MIMIC) | Indian Brand Equivalent | Price (Rs.) | Pricing Source |\n")
        f.write("| :--- | :--- | :--- | :--- |\n")
        for _, m_row in df_map.head(30).iterrows():
            f.write(f"| {m_row['us_medicine_name']} | {m_row['indian_brand_equivalent']} | Rs. {m_row['price_in_rupees']:.2f} | {m_row['pricing_source']} |\n")
            
    print(f"Generated Markdown Ledger at: {ledger_path}")

except Exception as e:
    print(f"Error: {e}")
