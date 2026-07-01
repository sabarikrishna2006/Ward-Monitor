import pandas as pd
import os

downloads_dir = r"c:\Users\ASUS\Downloads"

def analyze_csv(filename, column_name):
    file_path = os.path.join(downloads_dir, filename)
    if not os.path.exists(file_path):
        print(f"File not found: {filename}")
        return
    
    try:
        df = pd.read_csv(file_path)
        print(f"\n--- {filename} ---")
        if column_name in df.columns:
            counts = df[column_name].value_counts().head(10)
            print(f"Top 10 distinct '{column_name}':")
            print(counts.to_string())
        else:
            print(f"Column '{column_name}' not found. Available columns: {df.columns.tolist()}")
    except Exception as e:
        print(f"Error reading {filename}: {e}")

analyze_csv("procedures_icd.csv", "icd_code")
analyze_csv("prescriptions.csv", "drug")
analyze_csv("labevents.csv", "itemid")
