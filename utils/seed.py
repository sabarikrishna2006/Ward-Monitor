"""
Seed the SQLite database with mock patient data for the ward monitoring dashboard.
Creates realistic clinical scenarios: sepsis trajectory, AKI, hyperkalemia, etc.
"""
import json
import random
import sqlite3
from datetime import datetime, timedelta

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.ews import calculate_news2
from engine.drug_lab import check_all_rules


PATIENTS = [
    {'name': 'Gupta, V.', 'bed': 1, 'age': 45, 'gender': 'M', 'condition': 'Post-appendectomy recovery', 'stability': 'stable'},
    {'name': 'Singh, P.', 'bed': 2, 'age': 72, 'gender': 'F', 'condition': 'Community-acquired pneumonia', 'stability': 'stable'},
    {'name': 'Sharma, R.', 'bed': 3, 'age': 67, 'gender': 'M', 'condition': 'Urosepsis — deteriorating', 'stability': 'deteriorating_sepsis'},
    {'name': 'Kumar, S.', 'bed': 4, 'age': 58, 'gender': 'M', 'condition': 'Cellulitis, IV antibiotics', 'stability': 'stable'},
    {'name': 'Reddy, L.', 'bed': 5, 'age': 34, 'gender': 'F', 'condition': 'Appendicitis, pre-op', 'stability': 'stable'},
    {'name': 'Nair, M.', 'bed': 6, 'age': 81, 'gender': 'M', 'condition': 'COPD exacerbation', 'stability': 'stable_mild'},
    {'name': 'Patel, A.', 'bed': 7, 'age': 54, 'gender': 'F', 'condition': 'Type 2 DM, AKI developing', 'stability': 'aki_developing'},
    {'name': 'Joshi, K.', 'bed': 8, 'age': 62, 'gender': 'M', 'condition': 'DVT, anticoagulation', 'stability': 'stable'},
    {'name': 'Menon, D.', 'bed': 9, 'age': 70, 'gender': 'F', 'condition': 'Hypertension, hyperkalemia risk', 'stability': 'hyperkalemia'},
    {'name': 'Iyer, T.', 'bed': 10, 'age': 48, 'gender': 'M', 'condition': 'Cholecystitis', 'stability': 'stable'},
    {'name': 'Das, N.', 'bed': 11, 'age': 55, 'gender': 'F', 'condition': 'Asthma exacerbation', 'stability': 'stable'},
    {'name': 'Rao, B.', 'bed': 12, 'age': 78, 'gender': 'M', 'condition': 'Sepsis — no antibiotics yet', 'stability': 'sepsis_no_abx'},
]

BASE_MEDS = {
    'stable': [
        ('Paracetamol', '1g', 'Q6H PRN'),
        ('Omeprazole', '20mg', 'OD'),
    ],
    'deteriorating_sepsis': [
        ('Piperacillin-Tazobactam', '4.5g', 'Q8H'),
        ('Metronidazole', '500mg', 'Q8H'),
        ('Noradrenaline', '0.1 mcg/kg/min', 'Continuous'),
        ('Paracetamol', '1g', 'Q6H'),
        ('Enoxaparin', '40mg', 'OD'),
    ],
    'stable_mild': [
        ('Prednisolone', '30mg', 'OD'),
        ('Salbutamol nebulizer', '2.5mg', 'Q4H'),
        ('Paracetamol', '1g', 'Q6H PRN'),
    ],
    'aki_developing': [
        ('Metformin', '500mg', 'BD'),
        ('Ramipril', '5mg', 'OD'),
        ('Aspirin', '75mg', 'OD'),
        ('Paracetamol', '1g', 'Q6H PRN'),
    ],
    'hyperkalemia': [
        ('Lisinopril', '20mg', 'OD'),
        ('Spironolactone', '25mg', 'OD'),
        ('Amlodipine', '5mg', 'OD'),
        ('Paracetamol', '1g', 'Q6H PRN'),
    ],
    'sepsis_no_abx': [
        ('Paracetamol', '1g', 'Q6H PRN'),
        ('Omeprazole', '20mg', 'OD'),
    ],
    'stable': [
        ('Paracetamol', '1g', 'Q6H PRN'),
        ('Omeprazole', '20mg', 'OD'),
    ],
}

# Special medication overrides for specific conditions
SPECIAL_MEDS = {
    4: [  # Kumar — cellulitis
        ('Flucloxacillin', '1g', 'Q6H'),
        ('Paracetamol', '1g', 'Q6H PRN'),
        ('Omeprazole', '20mg', 'OD'),
    ],
    5: [  # Reddy — pre-op
        ('Paracetamol', '1g', 'Q6H PRN'),
        ('Ondansetron', '4mg', 'Q8H PRN'),
    ],
    8: [  # Joshi — DVT on anticoagulant
        ('Apixaban', '5mg', 'BD'),
        ('Paracetamol', '1g', 'Q6H PRN'),
        ('Omeprazole', '20mg', 'OD'),
    ],
    10: [  # Iyer — cholecystitis
        ('Co-amoxiclav', '625mg', 'TDS'),
        ('Metronidazole', '400mg', 'TDS'),
        ('Paracetamol', '1g', 'Q6H PRN'),
    ],
    11: [  # Das — asthma
        ('Prednisolone', '40mg', 'OD'),
        ('Salbutamol inhaler', '2 puffs', 'Q4H PRN'),
        ('Ipratropium nebulizer', '500mcg', 'Q6H'),
        ('Paracetamol', '1g', 'Q6H PRN'),
    ],
}


def _gen_vitals_sepsis_deteriorating(hours_ago):
    """Bed 3: Sharma — clear sepsis deterioration over 24h."""
    progress = max(0, (24 - hours_ago) / 24.0)  # 0 → 1 over 24h
    return {
        'heart_rate': 82 + progress * 38 + random.gauss(0, 3),
        'respiratory_rate': 16 + progress * 12 + random.gauss(0, 1),
        'spo2': 97 - progress * 7 + random.gauss(0, 0.5),
        'sbp': 125 - progress * 30 + random.gauss(0, 4),
        'dbp': 76 - progress * 12 + random.gauss(0, 3),
        'temperature': 37.1 + progress * 1.8 + random.gauss(0, 0.2),
        'consciousness': 'A' if progress < 0.7 else 'V',
        'air_or_oxygen': 'air' if progress < 0.5 else 'oxygen',
    }


def _gen_vitals_sepsis_no_abx(hours_ago):
    """Bed 12: Rao — sepsis criteria met, not improving without antibiotics."""
    progress = max(0, (24 - hours_ago) / 24.0)
    return {
        'heart_rate': 88 + progress * 22 + random.gauss(0, 3),
        'respiratory_rate': 17 + progress * 7 + random.gauss(0, 1),
        'spo2': 95 - progress * 3 + random.gauss(0, 0.5),
        'sbp': 108 - progress * 15 + random.gauss(0, 3),
        'dbp': 68 - progress * 8 + random.gauss(0, 2),
        'temperature': 38.2 + progress * 0.6 + random.gauss(0, 0.2),
        'consciousness': 'A',
        'air_or_oxygen': 'air',
    }


def _gen_vitals_aki(hours_ago):
    """Bed 7: Patel — AKI developing, vitals relatively stable but labs worsening."""
    progress = max(0, (24 - hours_ago) / 24.0)
    return {
        'heart_rate': 78 + progress * 10 + random.gauss(0, 2),
        'respiratory_rate': 15 + progress * 3 + random.gauss(0, 1),
        'spo2': 97 - progress * 2 + random.gauss(0, 0.3),
        'sbp': 142 + progress * 8 + random.gauss(0, 3),
        'dbp': 82 + progress * 5 + random.gauss(0, 2),
        'temperature': 36.8 + random.gauss(0, 0.2),
        'consciousness': 'A',
        'air_or_oxygen': 'air',
    }


def _gen_vitals_hyperkalemia(hours_ago):
    """Bed 9: Menon — hyperkalemia, vitals mostly stable."""
    return {
        'heart_rate': 68 + random.gauss(0, 3),
        'respiratory_rate': 14 + random.gauss(0, 1),
        'spo2': 97 + random.gauss(0, 0.3),
        'sbp': 138 + random.gauss(0, 4),
        'dbp': 78 + random.gauss(0, 3),
        'temperature': 36.6 + random.gauss(0, 0.2),
        'consciousness': 'A',
        'air_or_oxygen': 'air',
    }


def _gen_vitals_stable_mild(hours_ago):
    """Bed 6: COPD — mild, stable with occasional variation."""
    return {
        'heart_rate': 82 + random.gauss(0, 4),
        'respiratory_rate': 20 + random.gauss(0, 2),
        'spo2': 93 + random.gauss(0, 1),
        'sbp': 132 + random.gauss(0, 5),
        'dbp': 72 + random.gauss(0, 3),
        'temperature': 36.7 + random.gauss(0, 0.3),
        'consciousness': 'A',
        'air_or_oxygen': 'oxygen',
    }


def _gen_vitals_stable(hours_ago):
    """Stable patient — normal vitals with minor noise."""
    return {
        'heart_rate': 72 + random.gauss(0, 5),
        'respiratory_rate': 15 + random.gauss(0, 1.5),
        'spo2': 97 + random.gauss(0, 0.8),
        'sbp': 122 + random.gauss(0, 6),
        'dbp': 74 + random.gauss(0, 4),
        'temperature': 36.7 + random.gauss(0, 0.3),
        'consciousness': 'A',
        'air_or_oxygen': 'air',
    }


VITALS_GENERATORS = {
    'stable': _gen_vitals_stable,
    'deteriorating_sepsis': _gen_vitals_sepsis_deteriorating,
    'stable_mild': _gen_vitals_stable_mild,
    'aki_developing': _gen_vitals_aki,
    'hyperkalemia': _gen_vitals_hyperkalemia,
    'sepsis_no_abx': _gen_vitals_sepsis_no_abx,
}


def _clamp_vitals(vitals):
    """Ensure vitals stay in realistic ranges."""
    vitals['heart_rate'] = max(30, min(180, round(vitals['heart_rate'], 1)))
    vitals['respiratory_rate'] = max(6, min(40, round(vitals['respiratory_rate'], 1)))
    vitals['spo2'] = max(70, min(100, round(vitals['spo2'], 1)))
    vitals['sbp'] = max(60, min(220, round(vitals['sbp'], 1)))
    vitals['dbp'] = max(30, min(130, round(vitals['dbp'], 1)))
    vitals['temperature'] = max(34.0, min(41.0, round(vitals['temperature'], 1)))
    return vitals


def _gen_labs_for_patient(stability):
    """Generate lab values matching patient clinical story."""
    now = datetime.utcnow()
    labs = []

    if stability == 'deteriorating_sepsis':
        # Rising lactate, WBC, creatinine
        for h_offset in [0, 6, 12, 18]:
            t = now - timedelta(hours=h_offset)
            factor = (18 - h_offset) / 18.0
            labs.extend([
                (t, 'Lactate', round(1.2 + factor * 2.8, 1), 'mmol/L'),
                (t, 'WBC', round(11.0 + factor * 8.0, 1), 'x10^9/L'),
                (t, 'Creatinine', round(1.1 + factor * 0.6, 2), 'mg/dL'),
                (t, 'Potassium', round(4.0 + random.gauss(0, 0.2), 1), 'mmol/L'),
                (t, 'eGFR', round(72 - factor * 15, 0), 'mL/min'),
                (t, 'INR', round(1.1 + factor * 0.3, 1), ''),
                (t, 'Bicarbonate', round(24 - factor * 4, 1), 'mmol/L'),
                (t, 'Glucose', round(110 + factor * 40 + random.gauss(0, 10), 0), 'mg/dL'),
            ])

    elif stability == 'aki_developing':
        # Rising creatinine → drug-lab alert with metformin
        for h_offset in [0, 6, 12, 24]:
            t = now - timedelta(hours=h_offset)
            factor = (24 - h_offset) / 24.0
            labs.extend([
                (t, 'Creatinine', round(1.2 + factor * 1.6, 2), 'mg/dL'),
                (t, 'eGFR', round(58 - factor * 35, 0), 'mL/min'),
                (t, 'Potassium', round(4.5 + factor * 0.5, 1), 'mmol/L'),
                (t, 'Lactate', round(1.1 + factor * 0.4, 1), 'mmol/L'),
                (t, 'WBC', round(8.5, 1), 'x10^9/L'),
                (t, 'INR', round(1.0, 1), ''),
                (t, 'Bicarbonate', round(23 - factor * 3, 1), 'mmol/L'),
                (t, 'Glucose', round(165 + random.gauss(0, 15), 0), 'mg/dL'),
            ])

    elif stability == 'hyperkalemia':
        # High K+ → drug-lab alert with lisinopril
        t = now - timedelta(hours=2)
        labs.extend([
            (t, 'Potassium', 5.8, 'mmol/L'),
            (t, 'Creatinine', 1.4, 'mg/dL'),
            (t, 'eGFR', 48, 'mL/min'),
            (t, 'Lactate', 1.0, 'mmol/L'),
            (t, 'WBC', 7.2, 'x10^9/L'),
            (t, 'INR', 1.0, ''),
            (t, 'Bicarbonate', 25, 'mmol/L'),
            (t, 'Glucose', 98, 'mg/dL'),
        ])
        t6 = now - timedelta(hours=8)
        labs.extend([
            (t6, 'Potassium', 5.4, 'mmol/L'),
            (t6, 'Creatinine', 1.3, 'mg/dL'),
        ])

    elif stability == 'sepsis_no_abx':
        # High lactate, WBC — sepsis markers
        for h_offset in [0, 6]:
            t = now - timedelta(hours=h_offset)
            factor = (6 - h_offset) / 6.0 if h_offset <= 6 else 0
            labs.extend([
                (t, 'Lactate', round(2.0 + factor * 1.5, 1), 'mmol/L'),
                (t, 'WBC', round(14.0 + factor * 3.0, 1), 'x10^9/L'),
                (t, 'Creatinine', round(1.3 + factor * 0.2, 2), 'mg/dL'),
                (t, 'Potassium', round(4.2, 1), 'mmol/L'),
                (t, 'eGFR', round(55, 0), 'mL/min'),
                (t, 'INR', round(1.3, 1), ''),
                (t, 'Bicarbonate', round(20 - factor * 2, 1), 'mmol/L'),
                (t, 'Glucose', round(135 + random.gauss(0, 10), 0), 'mg/dL'),
            ])

    elif stability == 'stable_mild':
        t = now - timedelta(hours=4)
        labs.extend([
            (t, 'Potassium', 4.1, 'mmol/L'),
            (t, 'Creatinine', 1.0, 'mg/dL'),
            (t, 'eGFR', 78, 'mL/min'),
            (t, 'Lactate', 1.2, 'mmol/L'),
            (t, 'WBC', 9.0, 'x10^9/L'),
            (t, 'INR', 1.0, ''),
            (t, 'Bicarbonate', 24, 'mmol/L'),
            (t, 'Glucose', 95, 'mg/dL'),
        ])

    else:
        # Stable patients — normal labs
        t = now - timedelta(hours=random.randint(4, 12))
        labs.extend([
            (t, 'Potassium', round(random.uniform(3.8, 4.5), 1), 'mmol/L'),
            (t, 'Creatinine', round(random.uniform(0.7, 1.1), 2), 'mg/dL'),
            (t, 'eGFR', round(random.uniform(75, 100), 0), 'mL/min'),
            (t, 'Lactate', round(random.uniform(0.6, 1.5), 1), 'mmol/L'),
            (t, 'WBC', round(random.uniform(5.0, 9.5), 1), 'x10^9/L'),
            (t, 'INR', round(random.uniform(0.9, 1.2), 1), ''),
            (t, 'Bicarbonate', round(random.uniform(22, 26), 1), 'mmol/L'),
            (t, 'Glucose', round(random.uniform(80, 110), 0), 'mg/dL'),
        ])

    return labs


def seed_database(db_path):
    """Create and seed the database with mock patient data."""
    random.seed(42)  # Reproducible data

    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Create tables
    cur.execute('''CREATE TABLE patients (
        subject_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        bed_number INTEGER NOT NULL,
        age INTEGER NOT NULL,
        gender TEXT NOT NULL,
        ward TEXT NOT NULL,
        condition TEXT NOT NULL,
        admit_date TEXT NOT NULL
    )''')

    cur.execute('''CREATE TABLE vitals_timeseries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        heart_rate REAL,
        respiratory_rate REAL,
        spo2 REAL,
        sbp REAL,
        dbp REAL,
        temperature REAL,
        consciousness TEXT,
        air_or_oxygen TEXT DEFAULT 'air',
        FOREIGN KEY (subject_id) REFERENCES patients(subject_id)
    )''')

    cur.execute('''CREATE TABLE lab_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        item_name TEXT NOT NULL,
        value REAL NOT NULL,
        unit TEXT,
        FOREIGN KEY (subject_id) REFERENCES patients(subject_id)
    )''')

    cur.execute('''CREATE TABLE medications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id INTEGER NOT NULL,
        med_name TEXT NOT NULL,
        dose TEXT NOT NULL,
        frequency TEXT NOT NULL,
        start_date TEXT NOT NULL,
        FOREIGN KEY (subject_id) REFERENCES patients(subject_id)
    )''')

    cur.execute('''CREATE TABLE alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id INTEGER NOT NULL,
        alert_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        message TEXT NOT NULL,
        action TEXT,
        timestamp TEXT NOT NULL,
        acknowledged INTEGER DEFAULT 0,
        FOREIGN KEY (subject_id) REFERENCES patients(subject_id)
    )''')

    now = datetime.utcnow()
    admit_base = now - timedelta(days=3)

    for i, p in enumerate(PATIENTS):
        subject_id = i + 1
        admit_date = (admit_base + timedelta(hours=random.randint(0, 48))).strftime('%Y-%m-%d %H:%M:%S')

        cur.execute(
            'INSERT INTO patients VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (subject_id, p['name'], p['bed'], p['age'], p['gender'],
             '4B - General Medicine', p['condition'], admit_date)
        )

        # Medications
        meds = SPECIAL_MEDS.get(p['bed'], BASE_MEDS.get(p['stability'], BASE_MEDS['stable']))
        for med_name, dose, freq in meds:
            med_start = (now - timedelta(days=random.randint(1, 3))).strftime('%Y-%m-%d')
            cur.execute(
                'INSERT INTO medications (subject_id, med_name, dose, frequency, start_date) VALUES (?, ?, ?, ?, ?)',
                (subject_id, med_name, dose, freq, med_start)
            )

        # Vitals — 48 hours of hourly data
        gen = VITALS_GENERATORS.get(p['stability'], _gen_vitals_stable)
        for hours_ago in range(48, -1, -1):
            ts = (now - timedelta(hours=hours_ago)).strftime('%Y-%m-%d %H:%M:%S')
            v = _clamp_vitals(gen(hours_ago))
            cur.execute(
                'INSERT INTO vitals_timeseries (subject_id, timestamp, heart_rate, respiratory_rate, spo2, sbp, dbp, temperature, consciousness, air_or_oxygen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (subject_id, ts, v['heart_rate'], v['respiratory_rate'], v['spo2'],
                 v['sbp'], v['dbp'], v['temperature'], v['consciousness'], v['air_or_oxygen'])
            )

        # Labs
        for ts, item_name, value, unit in _gen_labs_for_patient(p['stability']):
            cur.execute(
                'INSERT INTO lab_events (subject_id, timestamp, item_name, value, unit) VALUES (?, ?, ?, ?, ?)',
                (subject_id, ts.strftime('%Y-%m-%d %H:%M:%S'), item_name, value, unit)
            )

    conn.commit()

    # Generate alerts from drug-lab rules
    all_alerts = check_all_rules(conn)
    for alert in all_alerts:
        cur.execute(
            'INSERT INTO alerts (subject_id, alert_type, severity, message, action, timestamp, acknowledged) VALUES (?, ?, ?, ?, ?, ?, 0)',
            (alert['subject_id'], alert['alert_type'], alert['severity'],
             alert['message'], alert['action'], now.strftime('%Y-%m-%d %H:%M:%S'))
        )

    # Add sepsis clinical alert for bed 12 (no antibiotics)
    cur.execute(
        'INSERT INTO alerts (subject_id, alert_type, severity, message, action, timestamp, acknowledged) VALUES (?, ?, ?, ?, ?, ?, 0)',
        (12, 'clinical', 'CRITICAL',
         'Sepsis-3 criteria met 6h ago. Lactate 3.5 mmol/L, WBC 17.0, HR 110, Temp 38.8°C. No antibiotics recorded.',
         'Urgent: Initiate sepsis 6-hour bundle. IV antibiotics within 1 hour. Repeat lactate in 2h. Fluid resuscitation.',
         (now - timedelta(hours=6)).strftime('%Y-%m-%d %H:%M:%S'))
    )

    conn.commit()

    # Print summary
    cur.execute('SELECT COUNT(*) FROM patients')
    print(f"  Patients: {cur.fetchone()[0]}")
    cur.execute('SELECT COUNT(*) FROM vitals_timeseries')
    print(f"  Vitals records: {cur.fetchone()[0]}")
    cur.execute('SELECT COUNT(*) FROM lab_events')
    print(f"  Lab events: {cur.fetchone()[0]}")
    cur.execute('SELECT COUNT(*) FROM medications')
    print(f"  Medications: {cur.fetchone()[0]}")
    cur.execute('SELECT COUNT(*) FROM alerts')
    print(f"  Alerts: {cur.fetchone()[0]}")

    # Print NEWS2 scores for verification
    print("\n  NEWS2 Scores:")
    for i, p in enumerate(PATIENTS):
        subject_id = i + 1
        cur.execute(
            'SELECT heart_rate, respiratory_rate, spo2, sbp, temperature, consciousness, air_or_oxygen '
            'FROM vitals_timeseries WHERE subject_id = ? ORDER BY timestamp DESC LIMIT 1',
            (subject_id,)
        )
        row = cur.fetchone()
        if row:
            vitals = {
                'heart_rate': row[0], 'respiratory_rate': row[1],
                'spo2': row[2], 'sbp': row[3], 'temperature': row[4],
                'consciousness': row[5] or 'A', 'air_or_oxygen': row[6] or 'air',
            }
            result = calculate_news2(vitals)
            flag = '[RED]' if result['color'] == 'red' else '[AMB]' if result['color'] == 'amber' else '[GRN]'
            print(f"    {flag} Bed {p['bed']:2d} {p['name']:15s} NEWS2={result['score']:2d} ({result['risk_level']})")

    conn.close()
    print("\n[OK] Database seeded successfully!")


if __name__ == '__main__':
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'ward.db')
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    print(f"Seeding database at {db_path}...")
    seed_database(db_path)
