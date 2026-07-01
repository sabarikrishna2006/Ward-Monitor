import pandas as pd

# Load the Kaggle treatments dataset from your Downloads folder
file_path = r"c:\Users\ASUS\Downloads\treatments.csv"

try:
    df = pd.read_csv(file_path)
    
    print("Successfully loaded treatments.csv!")
    print(f"Total rows: {len(df)}\n")
    
    # Check if the columns exist
    if 'treatment_type' in df.columns and 'description' in df.columns and 'cost' in df.columns:
        
        # Group by BOTH treatment type and description to get the exact mean cost
        price_book_df = df.groupby(['treatment_type', 'description'])['cost'].mean().reset_index()
        
        print("--- GENERATED PRICE BOOK ---")
        # Format it nicely as a Python dictionary so you can copy-paste it
        print("price_book = {")
        for index, row in price_book_df.iterrows():
            key_name = f"{row['treatment_type']}_{row['description']}".replace(" ", "_")
            print(f'    "{key_name}": {round(row["cost"], 2)},')
        
        # Add the baseline daily rates
        print('    "ICU_Daily_Rate": 15000.00,')
        print('    "Ward_Daily_Rate": 4500.00')
        print("}")
        
    else:
        print("Error: The CSV does not have the expected columns ('treatment_type', 'description', 'cost').")
        print("Found columns:", df.columns.tolist())

except Exception as e:
    print(f"Error reading the file: {e}")
