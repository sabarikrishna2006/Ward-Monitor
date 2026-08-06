import pandas as pd
import sys

file_path = r'C:\Users\sabari krishna\Downloads\Foqal_CareOS_Integrated_Tracker.xlsx'
try:
    df = pd.read_excel(file_path)
    df.to_csv(sys.stdout, index=False)
except Exception as e:
    print('Error:', e)
