import pandas as pd

# Load the Kaggle treatments dataset
file_path = r"C:\Users\ASUS\Downloads\treatments.csv"
df = pd.read_csv(file_path)

# Group by BOTH treatment type and description to get the exact mean cost
price_book_df = df.groupby(['treatment_type', 'description'])['cost'].mean().reset_index()

# This creates a precision price book, for example:
# MRI | Advanced protocol  | ₹4,158
# MRI | Basic screening    | ₹4,799
# ECG | Standard procedure | ₹582