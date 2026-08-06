import pandas as pd
import os

downloads_dir = r"c:\Users\ASUS\Downloads"
treatments_file = os.path.join(downloads_dir, "treatments.csv")

try:
    df = pd.read_csv(treatments_file)
    print("Headers of treatments.csv:", df.columns.tolist())
    print("\nFirst 10 rows:")
    print(df.to_string())
    print("\nMean cost in treatments.csv:", df['Cost'].mean())
except Exception as e:
    print(f"Error: {e}")
