import pandas as pd
import numpy as np

# Load the Google Sheet
url = 'https://docs.google.com/spreadsheets/d/192x8t_UGiNr0McZtp12pM66XJJQsAflq8DbvR-GRnDg/export?format=xlsx'
xls = pd.ExcelFile(url)

output_path = r'C:\Users\sabari krishna\Downloads\Foqal_CareOS_Integrated_Tracker.xlsx'

with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
    for sheet in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet)
        
        # Drop unnamed columns that sometimes get added during export
        df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
        
        if sheet == 'Use Cases & hadm_ids':
            if 'To Be Discussed (with Doctor/Professor)' in df.columns:
                def fill_discussion(row):
                    if pd.notna(row.get('To Be Discussed (with Doctor/Professor)')) and str(row.get('To Be Discussed (with Doctor/Professor)')).strip() != '':
                        return row['To Be Discussed (with Doctor/Professor)']
                    desc = str(row.get('Description', '')).lower()
                    if 'sepsis' in desc or 'shock' in desc:
                        return 'Review specific timeline for broad-spectrum antibiotics and fluid resuscitation guidelines alignment.'
                    elif 'heart' in desc or 'dcm' in desc or 'chf' in desc:
                        return 'Verify diuretic dosing triggers and NYHA class transition accuracy in the predictive model.'
                    elif 'copd' in desc or 'respiratory' in desc:
                        return 'Confirm O2 saturation target thresholds (e.g., 88-92% scale) are appropriately flagged.'
                    elif 'kidney' in desc or 'aki' in desc:
                        return 'Discuss creatinine baseline thresholds and drug-lab interaction rules for nephrotoxic meds.'
                    elif 'transfer' in desc or 'ccu' in desc:
                        return 'Validate standard operating procedures (SOPs) and response times for CCU escalation.'
                    elif 'billing' in desc or 'cost' in desc:
                        return 'Ensure itemized consumable costs reflect accurate tier-based pricing for the locality.'
                    else:
                        return 'Review clinical accuracy of parameter deterioration and validate escalation protocol adherence.'
                
                df['To Be Discussed (with Doctor/Professor)'] = df.apply(fill_discussion, axis=1)

        elif sheet == 'Synthetic Data':
            # Fill missing data in Synthetic Data sheet
            for i, row in df.iterrows():
                uc = str(row.get('Use Case', '')).lower()
                if 'dashboard demo' in uc:
                    if pd.isna(row.get('Data Entity')): df.at[i, 'Data Entity'] = 'Vitals & NEWS2 Scores'
                    if pd.isna(row.get('Description')): df.at[i, 'Description'] = 'Continuous stream of patient vital signs generating dynamic NEWS2 alerts.'
                    if pd.isna(row.get('Example Value')): df.at[i, 'Example Value'] = 'HR: 110, SpO2: 91% -> NEWS2 Score: 5'
                    if pd.isna(row.get('Records')): df.at[i, 'Records'] = '20 Active Patients'
                elif 'drug-lab' in uc:
                    if pd.isna(row.get('Data Entity')): df.at[i, 'Data Entity'] = 'Active Medications & Lab Results'
                    if pd.isna(row.get('Description')): df.at[i, 'Description'] = 'Cross-referenced drug prescriptions against live lab values to trigger contraindication alerts.'
                    if pd.isna(row.get('Example Value')): df.at[i, 'Example Value'] = 'Furosemide + K (2.8 mmol/L) -> Hypokalemia Risk'
                    if pd.isna(row.get('Records')): df.at[i, 'Records'] = '50+ Mock Lab Entries'
                elif 'predictive ml' in uc:
                    if pd.isna(row.get('Data Entity')): df.at[i, 'Data Entity'] = 'ML Deterioration Risk %'
                    if pd.isna(row.get('Description')): df.at[i, 'Description'] = 'AI-driven deterioration risk model predicting clinical decline within 6-12 hours.'
                    if pd.isna(row.get('Example Value')): df.at[i, 'Example Value'] = 'Risk: 82% (High likelihood of ICU transfer)'
                    if pd.isna(row.get('Records')): df.at[i, 'Records'] = 'Continuous Scoring'
                elif 'missing data fill' in uc:
                    if pd.isna(row.get('Data Entity')): df.at[i, 'Data Entity'] = 'Imputed Vital Signs'
                    if pd.isna(row.get('Description')): df.at[i, 'Description'] = 'Algorithmically imputed values for missing physiological data to maintain continuous monitoring.'
                    if pd.isna(row.get('Example Value')): df.at[i, 'Example Value'] = 'Last valid SpO2 carried forward for 4 hours'
                    if pd.isna(row.get('Records')): df.at[i, 'Records'] = 'Variable'
                elif 'cost estimation' in uc:
                    if pd.isna(row.get('Data Entity')): df.at[i, 'Data Entity'] = 'Provisional Billing Items'
                    if pd.isna(row.get('Description')): df.at[i, 'Description'] = 'Real-time financial estimation based on ward type, ongoing treatments, and insurance coverage.'
                    if pd.isna(row.get('Example Value')): df.at[i, 'Example Value'] = 'Ward Cost: $500/day, Lab Cost: $150 -> Total: $650'
                    if pd.isna(row.get('Records')): df.at[i, 'Records'] = '100+ Catalog Items'

        elif sheet == 'Mock Data Sources':
            # Fill missing Purpose in System
            if 'Purpose in System' in df.columns:
                def fill_purpose(row):
                    if pd.notna(row.get('Purpose in System')) and str(row.get('Purpose in System')).strip() != '':
                        return row['Purpose in System']
                    src = str(row.get('Source', '')).lower()
                    if 'ccu_seed' in src: return 'Bootstraps the database with deterministic patient states for consistent demonstration.'
                    if 'mimic' in src: return 'Provides highly realistic, anonymized historical EHR data for testing ML and clinical rules.'
                    if 'price list' in src: return 'Enables realistic billing estimation, out-of-pocket calculations, and financial workflows.'
                    if 'cloud sql' in src: return 'Primary operational data store serving the frontend with live patient state and vitals.'
                    if 'smtp' in src: return 'Facilitates real-world communication testing for user management (e.g., password reset).'
                    if 'gemini' in src: return 'Powers the AI-driven automated discharge summary generation based on clinical timelines.'
                    if 'credentials' in src: return 'Securely manages access to backend cloud services like BigQuery and Vertex AI.'
                    if 'sms' in src: return 'Simulates external alerting and family updates without incurring SMS gateway costs during demo.'
                    if 'payment' in src: return 'Provides UI continuity for the financial workflow without requiring actual payment processing.'
                    return 'Supports overall system architecture and provides necessary data flow for UI rendering.'
                df['Purpose in System'] = df.apply(fill_purpose, axis=1)

        # Write to excel
        df.to_excel(writer, sheet_name=sheet, index=False)

print(f"Successfully generated populated multi-tab tracker at: {output_path}")
