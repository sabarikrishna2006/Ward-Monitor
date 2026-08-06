import pandas as pd
import os

downloads_dir = r"c:\Users\ASUS\Downloads"
local_meds_file = os.path.join(downloads_dir, "prescriptions.csv")
indian_meds_file = os.path.join(downloads_dir, "indian_medicine_data.csv")

try:
    df_local = pd.read_csv(local_meds_file)
    df_indian = pd.read_csv(indian_meds_file)
    
    # Rename columns to avoid encoding crashes
    df_indian.columns = [c.encode('ascii', 'ignore').decode('ascii') for c in df_indian.columns]
    df_indian = df_indian.rename(columns={'price()': 'price'})
    
    local_drugs = df_local['drug'].dropna().unique()
    print(f"Total distinct drugs in local prescriptions.csv: {len(local_drugs)}")
    
    matched_count = 0
    print("\nAttempting dynamic string matching against the 200,000+ Indian medicine dataset...")
    
    for drug in local_drugs:
        drug_clean = str(drug).lower().split(' ')[0] # Match by first word (e.g. "Metoprolol" from "Metoprolol Tartrate")
        if len(drug_clean) < 4: continue # skip short names to avoid false matches
        
        # Search in short_composition1 or name
        matches = df_indian[
            df_indian['short_composition1'].str.lower().str.contains(drug_clean, na=False) |
            df_indian['name'].str.lower().str.contains(drug_clean, na=False)
        ]
        
        if not matches.empty:
            matched_count += 1
            best_match = matches.iloc[0]
            print(f"Match found for '{drug}':")
            print(f"  -> Indian Brand: {best_match['name']} | Price: Rs. {best_match['price']} | Composition: {best_match['short_composition1']}")
            
    print(f"\nSuccessfully matched {matched_count} out of {len(local_drugs)} local drugs dynamically!")

except Exception as e:
    print(f"Error: {e}")
