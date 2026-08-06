import pandas as pd

file_path = r'C:\Users\sabari krishna\Downloads\Foqal_CareOS_Integrated_Tracker.xlsx'

try:
    df = pd.read_excel(file_path)
    
    # Define the new content for the missing cells
    updates = {
        'De-escalation (Critical -> Stable)': 'Verify the step-down protocols: does transferring a patient back to the General Ward require mandatory review by the Attending Physician, or can the Charge Nurse authorize it based on the sustained NEWS2 drop?',
        'Stable (Continuous Normal)': 'Discuss the frequency of vital sign monitoring for highly stable patients. Should the system dynamically recommend reducing vitals collection frequency to reduce nursing workload?',
        'Drug-Lab Alert (Amiodarone + Hypokalemia)': 'Confirm the override policy for critical Drug-Lab alerts. Should residents be allowed to proceed with justification, or does a Tier 1 flag (like Amiodarone + Hypokalemia) require a Consultant\'s co-sign?',
        'Discharge Flow (Recovery -> Discharge)': 'Validate the handoff between clinical discharge and billing workflows. Should the system trigger predictive billing alerts to PM-JAY / insurance early in the recovery phase rather than at discharge initiation?',
        'SLA Breach (Pending > 10 mins)': 'Determine the appropriate auto-escalation chain for SLA breaches. If a Charge Nurse fails to acknowledge within 10 minutes, should the alert route directly to the Attending Physician or Code Blue team?',
        'Rapid Deterioration (Normal -> Critical < 2h)': 'Evaluate the system\'s sensitivity to rapid trend changes. Should a sudden multi-point jump in NEWS2 trigger a preemptive Rapid Response Team (RRT) alert even before crossing the absolute critical threshold?'
    }
    
    # Update the dataframe
    for idx, row in df.iterrows():
        scenario = row['Use Case / Scenario']
        if pd.isna(row['To Be Discussed (with Doctor/Professor)']):
            if scenario in updates:
                df.at[idx, 'To Be Discussed (with Doctor/Professor)'] = updates[scenario]
                
    # Save back to excel
    df.to_excel(file_path, index=False)
    print("Successfully updated the Excel file!")
    
except Exception as e:
    print('Error:', e)
