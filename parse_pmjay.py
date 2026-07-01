import pandas as pd

try:
    df = pd.read_html(r'C:\Users\ASUS\.gemini\antigravity\brain\5896c730-5fa9-4289-8c14-6ad8dc112519\.system_generated\steps\862\content.md')[0]
    print(df.head())
    print("Columns:", df.columns.tolist())
    df.to_csv(r'c:\Users\ASUS\Downloads\pmjay_assam_procedures.csv', index=False)
    print("Saved to CSV successfully.")
except Exception as e:
    print("Error:", e)
