import pandas as pd
import os

# Try to import plotting libraries, fallback gracefully if not installed
try:
    import matplotlib.pyplot as plt
    import seaborn as sns
    plotting_available = True
except ImportError:
    plotting_available = False

downloads_dir = r"c:\Users\ASUS\Downloads"
dataset_path = os.path.join(downloads_dir, "dcm_billing_ml_data.csv")

if not os.path.exists(dataset_path):
    print(f"Error: Dataset not found at {dataset_path}. Please run train_dcm_model.py first.")
    exit()

print("Loading DCM Billing Dataset...")
df = pd.read_csv(dataset_path)

print(f"\n==================================================")
print(f"       EDA REPORT: DILATED CARDIOMYOPATHY COHORT   ")
print(f"==================================================")
print(f"Total admissions analyzed: {len(df)}")

# 1. Summary Statistics
print("\n--- 1. COST DISTRIBUTION (in Rs.) ---")
print(f"Mean Cost:    Rs. {df['final_real_cost'].mean():,.2f}")
print(f"Median Cost:  Rs. {df['final_real_cost'].median():,.2f}")
print(f"Min Cost:     Rs. {df['final_real_cost'].min():,.2f}")
print(f"Max Cost:     Rs. {df['final_real_cost'].max():,.2f}")
print(f"Total Billing: Rs. {df['final_real_cost'].sum():,.2f}")

print("\n--- 2. CLINICAL RESOURCE UTILIZATION ---")
print(f"Average Labs/Patient:      {df['lab_count'].mean():.1f} tests")
print(f"Average Meds/Patient:      {df['med_count'].mean():.1f} prescriptions")
print(f"Average ICU Stay:          {df['icu_days'].mean():.2f} days")
print(f"Patients needing ICU:      {(df['icu_days'] > 0).sum()} ({(df['icu_days'] > 0).mean()*100:.1f}%)")
print(f"Patients needing Cath:     {(df['has_cardiac_cath'] == 1).sum()} ({(df['has_cardiac_cath'] == 1).mean()*100:.1f}%)")

# 2. Cost Variance Analysis (Deviation from base package)
base_package = 40000.0 + (3 * 4500.0) # Rs. 53,500
df['variance'] = df['final_real_cost'] - base_package

print("\n--- 3. BILL VARIANCE ANALYSIS ---")
print(f"Base PM-JAY Package Cost:  Rs. {base_package:,.2f}")
print(f"Average Cost Variance:     Rs. {df['variance'].mean():,.2f}")
print(f"Max Cost Variance:         Rs. {df['variance'].max():,.2f}")

# 3. Correlation Analysis
print("\n--- 4. CORRELATION WITH FINAL BILL ---")
correlations = df[['lab_count', 'med_count', 'icu_days', 'has_cardiac_cath', 'has_premium_med']].corrwith(df['final_real_cost'])
for col, val in correlations.items():
    print(f"  {col:<20} Correlation: {val:.4f}")

# 4. Generating and saving plots
if plotting_available:
    print("\nGenerating EDA Plots...")
    
    # Plot 1: Cost Distribution Histogram
    plt.figure(figsize=(10, 6))
    sns.histplot(df['final_real_cost'], kde=True, color='skyblue', bins=30)
    plt.title('Distribution of Total Hospital Bill for DCM Patients (Rs.)')
    plt.xlabel('Total Cost (Rs.)')
    plt.ylabel('Patient Count')
    plt.grid(True, alpha=0.3)
    dist_path = os.path.join(downloads_dir, "dcm_cost_distribution.png")
    plt.savefig(dist_path)
    plt.close()
    print(f"Saved Cost Distribution Plot: {dist_path}")
    
    # Plot 2: Correlation Heatmap
    plt.figure(figsize=(8, 6))
    sns.heatmap(df[['lab_count', 'med_count', 'icu_days', 'has_cardiac_cath', 'has_premium_med', 'final_real_cost']].corr(), 
                annot=True, cmap='coolwarm', fmt=".3f", linewidths=.5)
    plt.title('Correlation Matrix of Clinical Resources vs Final Cost')
    plt.tight_layout()
    corr_path = os.path.join(downloads_dir, "dcm_feature_correlations.png")
    plt.savefig(corr_path)
    plt.close()
    print(f"Saved Correlation Heatmap Plot: {corr_path}")
else:
    print("\nPlotting libraries (matplotlib/seaborn) not available. Skipping visual generation.")
