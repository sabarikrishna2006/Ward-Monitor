import pandas as pd
import os

downloads_dir = r"c:\Users\ASUS\Downloads"
meds_file = os.path.join(downloads_dir, "indian_medicine_data.csv")

try:
    print("Loading Indian Medicine Database...")
    df = pd.read_csv(meds_file)
    
    # We will search both the brand 'name' and the 'short_composition1' (generic)
    # columns for matches of our top DCM drugs
    target_keywords = ["lasix", "metolar", "betaloc", "uniwarfin", "calpol", "crocin", "paracetamol", "potcl"]
    
    print("\nSearching for Indian brand/generic matches in the dataset:")
    for kw in target_keywords:
        print(f"\n--- Results for '{kw}' ---")
        # Search in 'name'
        matches_name = df[df['name'].str.lower().str.contains(kw, na=False)]
        # Search in 'short_composition1'
        matches_comp = df[df['short_composition1'].str.lower().str.contains(kw, na=False)]
        
        all_matches = pd.concat([matches_name, matches_comp]).drop_duplicates(subset=['name'])
        
        if not all_matches.empty:
            # Rename columns to avoid print encoding crashes
            all_matches = all_matches.rename(columns={c: c.encode('ascii', 'ignore').decode('ascii') for c in all_matches.columns})
            print(all_matches[['name', 'price()', 'short_composition1']].head(3).to_string(index=False))
        else:
            print("No matches found.")
except Exception as e:
    print(f"Error: {e}")
