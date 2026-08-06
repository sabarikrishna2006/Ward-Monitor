import pandas as pd
import os

downloads_dir = r"c:\Users\ASUS\Downloads"
file_path = os.path.join(downloads_dir, "indian_medicine_data.csv")

try:
    df = pd.read_csv(file_path, nrows=5)
    safe_columns = [col.encode('ascii', 'ignore').decode('ascii') for col in df.columns]
    print("Columns in dataset:", safe_columns)
    for col in df.columns:
        safe_col = col.encode('ascii', 'ignore').decode('ascii')
        print(f"\nSample values for {safe_col}:")
        for val in df[col].dropna().head(3):
            print("  -", str(val).encode('ascii', 'ignore').decode('ascii'))
except Exception as e:
    print(f"Error reading file: {e}")
