# -*- coding: utf-8 -*-
"""
cloud_ingest.py
===============
Pulls DCM patient data from Cloud SQL (PostgreSQL / MIMIC-IV schema)
and ingests it into the local SQLite database used by the FastAPI backend.

MIMIC-IV Cloud SQL tables used:
  ap_patients         -> subject_id, gender, anchor_age, anchor_year
  ap_admissions       -> subject_id, hadm_id, admittime, dischtime, diagnosis
  ap_chartevents      -> subject_id, hadm_id, itemid, charttime, value, valuenum
  ap_labevents        -> subject_id, hadm_id, itemid, charttime, value, valuenum
  ap_prescriptions    -> subject_id, hadm_id, drug, dose_val_rx, dose_unit_rx, freq

Vital sign ITEMIDs (MIMIC-IV MetaVision / eICU hybrid):
  Heart Rate:         220045
  Resp Rate:          220210
  SpO2:               220277
  SBP (arterial):     220179  (also 220050)
  DBP (arterial):     220180
  Temperature (C):    223762  (also 226329 Fahrenheit)
  Temperature (F):    223761

Lab ITEMIDs:
  Potassium:          227442 / 50971
  Creatinine:         220615 / 50912
  Lactate:            225668 / 50813
"""
import os
import sys
import random
from datetime import datetime

from google.cloud.sql.connector import Connector, IPTypes
import sqlalchemy
from sqlalchemy import text
from sqlalchemy.orm import Session

# Fix path so we can import our local models & database
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import engine as local_engine, init_db
from models import Patient, VitalTimeSeries, LabEvent, Medication

# ── Cloud SQL credentials ─────────────────────────────────────────────────────
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "healthcare-project-db-creds (1).json"
)
INSTANCE_CONNECTION_NAME = "healthcare-project-496207:asia-south1:healthcare-project-496207-instance"
DB_USER = "postgres"
DB_PASS = "foqalAnalyticsHealthcareDB2026"
DB_NAME = "postgres"

# ── MIMIC-IV vital sign itemids ────────────────────────────────────────────────
VITAL_ITEMIDS = {
    "heart_rate":  [220045],
    "resp_rate":   [220210],
    "spo2":        [220277],
    "sbp":         [220179, 220050],
    "dbp":         [220180, 220051],
    "temp_c":      [223762],
    "temp_f":      [223761],
}

# ── Lab itemids ────────────────────────────────────────────────────────────────
LAB_ITEMIDS = {
    "potassium":   [227442, 50971],
    "creatinine":  [220615, 50912],
    "lactate":     [225668, 50813],
}

# ── Indian DCM patient demographics (realistic names for demo) ────────────────
INDIAN_NAMES_M = [
    "Rajesh Kumar", "Arun Verma", "Mohan Singh", "Suresh Patel",
    "Vikram Sharma", "Deepak Rao", "Anand Gupta", "Sanjay Iyer",
    "Ramesh Nair", "Prasad Reddy", "Mahesh Joshi", "Harish Pillai",
    "Dinesh Joshi", "Sunil Mehta", "Ashok Tiwari", "Vijay Bhat",
    "Rakesh Desai", "Nitin Shah", "Amit Kulkarni", "Rohit Mishra",
]
INDIAN_NAMES_F = [
    "Priya Sharma", "Sunita Devi", "Rekha Patel", "Anita Singh",
    "Kavitha Nair", "Meena Iyer", "Saritha Pillai", "Lakshmi Reddy",
    "Geeta Rao", "Usha Mehta", "Asha Gupta", "Sujatha Kumar",
    "Revathy Pillai", "Malathi Krishnan", "Geetha Nair", "Vijayalakshmi",
    "Padmavathi", "Saraswathi Devi", "Kamala Rajan", "Hema Patel",
]
DCM_COMPLAINTS = [
    "Dilated Cardiomyopathy, NYHA Class III",
    "DCM with HFrEF (EF 28%), Heart Failure Exacerbation",
    "Dilated Cardiomyopathy, Decompensated HF",
    "DCM, Pulmonary Oedema, AF with RVR",
    "Ischaemic Cardiomyopathy, DCM Pattern",
    "DCM with Arrhythmia, VT Storm",
    "DCM Post-Partum Cardiomyopathy",
    "Dilated Cardiomyopathy, Cardiac Cachexia",
]
DCM_MEDS = [
    [("Carvedilol", "6.25mg", "BD"), ("Enalapril", "5mg", "BD"),
     ("Furosemide", "40mg", "OD"), ("Spironolactone", "25mg", "OD"),
     ("Digoxin", "0.125mg", "OD"), ("Warfarin", "5mg", "OD")],
    [("Metoprolol", "25mg", "BD"), ("Losartan", "50mg", "OD"),
     ("Furosemide", "80mg", "BD"), ("Aspirin", "75mg", "OD"),
     ("Atorvastatin", "40mg", "OD")],
    [("Carvedilol", "12.5mg", "BD"), ("Ramipril", "10mg", "OD"),
     ("Torsemide", "20mg", "OD"), ("Spironolactone", "50mg", "OD"),
     ("Amiodarone", "200mg", "OD")],
    [("Bisoprolol", "5mg", "OD"), ("Valsartan", "160mg", "BD"),
     ("Furosemide", "40mg", "BD"), ("Warfarin", "5mg", "OD"),
     ("Aspirin", "75mg", "OD"), ("Digoxin", "0.25mg", "OD")],
]

WARDS = ["Ward 4B", "Ward 4C"]


def get_cloud_conn():
    connector = Connector()
    def _get():
        return connector.connect(
            INSTANCE_CONNECTION_NAME, "pg8000",
            user=DB_USER, password=DB_PASS, db=DB_NAME,
            ip_type=IPTypes.PUBLIC,
        )
    return connector, sqlalchemy.create_engine("postgresql+pg8000://", creator=_get)


def fetch_dcm_patients(cloud_conn, limit=100):
    """
    Query DCM patients from Cloud SQL.
    Tries MIMIC-style tables first; falls back to any 'patients' table found.
    Returns list of dicts: {subject_id, gender, age}
    """
    # Try standard MIMIC-IV table names with ap_ prefix
    queries_to_try = [
        # Full MIMIC join with ICD-9/10 DCM codes
        """
        SELECT DISTINCT p.subject_id, p.gender, p.anchor_age as age
        FROM ap_patients p
        JOIN ap_diagnoses_icd d ON p.subject_id = d.subject_id
        WHERE d.icd_code IN (
            '4254','42541','42542','42549',    -- ICD-9 DCM
            'I420','I422','I425','I426','I427','I428','I429'  -- ICD-10 DCM
        )
        LIMIT %(limit)s
        """,
        # Fallback: just all patients
        "SELECT subject_id, gender, anchor_age as age FROM ap_patients LIMIT %(limit)s",
    ]

    for q in queries_to_try:
        try:
            rows = cloud_conn.execute(text(q), {"limit": limit}).fetchall()
            if rows:
                print(f"  Fetched {len(rows)} patients from Cloud SQL")
                return [{"subject_id": r[0], "gender": r[1], "age": r[2]} for r in rows]
        except Exception as e:
            print(f"  Query attempt failed: {e}")
    return []


def fetch_vitals(cloud_conn, subject_ids, limit_per_patient=50):
    """
    Fetch vital chartevents for given subject IDs.
    Returns list of dicts.
    """
    all_itemids = []
    for ids in VITAL_ITEMIDS.values():
        all_itemids.extend(ids)

    id_list = ", ".join(str(i) for i in subject_ids)
    itemid_list = ", ".join(str(i) for i in all_itemids)

    queries = [
        f"""
        SELECT subject_id, charttime, itemid, valuenum
        FROM ap_chartevents
        WHERE subject_id IN ({id_list})
          AND itemid IN ({itemid_list})
          AND valuenum IS NOT NULL
        ORDER BY subject_id, charttime DESC
        """,
        # Fallback without ap_ prefix
        f"""
        SELECT subject_id, charttime, itemid, valuenum
        FROM chartevents
        WHERE subject_id IN ({id_list})
          AND itemid IN ({itemid_list})
          AND valuenum IS NOT NULL
        ORDER BY subject_id, charttime DESC
        """,
    ]

    for q in queries:
        try:
            rows = cloud_conn.execute(text(q)).fetchall()
            if rows:
                print(f"  Fetched {len(rows)} vital rows from Cloud SQL")
                return rows
        except Exception as e:
            print(f"  Vitals query failed: {e}")
    return []


def fetch_labs(cloud_conn, subject_ids):
    """Fetch lab events for given subject IDs."""
    all_itemids = []
    for ids in LAB_ITEMIDS.values():
        all_itemids.extend(ids)

    id_list = ", ".join(str(i) for i in subject_ids)
    itemid_list = ", ".join(str(i) for i in all_itemids)

    queries = [
        f"""
        SELECT subject_id, charttime, itemid, valuenum
        FROM ap_labevents
        WHERE subject_id IN ({id_list})
          AND itemid IN ({itemid_list})
          AND valuenum IS NOT NULL
        ORDER BY subject_id, charttime DESC
        """,
        f"""
        SELECT subject_id, charttime, itemid, valuenum
        FROM labevents
        WHERE subject_id IN ({id_list})
          AND itemid IN ({itemid_list})
          AND valuenum IS NOT NULL
        ORDER BY subject_id, charttime DESC
        """,
    ]

    for q in queries:
        try:
            rows = cloud_conn.execute(text(q)).fetchall()
            if rows:
                print(f"  Fetched {len(rows)} lab rows from Cloud SQL")
                return rows
        except Exception as e:
            print(f"  Labs query failed: {e}")
    return []


def itemid_to_vital_field(itemid):
    for field, ids in VITAL_ITEMIDS.items():
        if itemid in ids:
            return field
    return None


def itemid_to_lab_field(itemid):
    for field, ids in LAB_ITEMIDS.items():
        if itemid in ids:
            return field
    return None


def ingest(max_patients=100):
    print("=" * 60)
    print("Foqal CareOS - DCM Patient Data Ingest")
    print("=" * 60)
    print("")
    print("NOTE: Cloud SQL clinical tables (ap_chartevents, ap_labevents)")
    print("are not yet populated with MIMIC data. Using high-quality")
    print("synthetic DCM patient data for the demo (100 patients).")
    print("When MIMIC data is loaded into Cloud SQL, re-run this script.")
    print("")

    # 1. Init local SQLite DB
    print("[1/3] Initializing local SQLite DB...")
    init_db()

    # 2. Connect to Cloud SQL to get patient IDs if available
    print("[2/3] Checking Cloud SQL for DCM patient list...")
    patients_raw = []
    connector, cloud_engine = get_cloud_conn()
    try:
        with cloud_engine.connect() as cloud_conn:
            patients_raw = fetch_dcm_patients(cloud_conn, limit=max_patients)
    except Exception as e:
        print(f"  Cloud SQL connection issue: {e}")
    finally:
        connector.close()

    if not patients_raw:
        print("  No clinical patient data in Cloud SQL yet.")
        print("  Generating {} synthetic DCM patients for demo...".format(max_patients))
        patients_raw = [
            {
                "subject_id": 10000 + i,
                "gender": random.choice(["M", "M", "M", "F"]),  # DCM is 3:1 M:F
                "age": random.randint(35, 78)
            }
            for i in range(max_patients)
        ]

    # 3. Write to local SQLite with synthetic vitals/labs
    print("[3/3] Writing {} patients to local SQLite...".format(len(patients_raw)))
    bed_num = 1

    with Session(local_engine) as session:
        # Clear existing data
        session.query(Medication).delete()
        session.query(LabEvent).delete()
        session.query(VitalTimeSeries).delete()
        session.query(Patient).delete()
        session.commit()

        for p_raw in patients_raw:
            sid    = p_raw["subject_id"]
            gender = p_raw.get("gender", "M") or "M"
            age    = p_raw.get("age", 60) or 60
            try:
                age = int(float(age))
            except Exception:
                age = 60

            # Pick an Indian name
            if str(gender).upper() in ("F", "FEMALE"):
                name = random.choice(INDIAN_NAMES_F)
            else:
                name = random.choice(INDIAN_NAMES_M)

            ward = random.choice(WARDS)
            room = ward.split()[-1]
            bed  = "{:02d}".format(bed_num % 30 + 1)
            bed_num += 1

            patient = Patient(
                subject_id=sid,
                name=name,
                age=age,
                sex=str(gender).upper()[0] if gender else "M",
                ward=ward,
                room=room,
                bed=bed,
                admitted=datetime.now().strftime("%d %b %Y"),
                complaint=random.choice(DCM_COMPLAINTS),
                hypercapnic_failure=0,
            )
            session.add(patient)

            # ── Vitals ──────────────────────────────────────────────────────
            # Since Cloud SQL has no MIMIC data yet, always use synthetic vitals
            _gen_synthetic_vitals(session, sid, age)

            # ── Labs ─────────────────────────────────────────────────────────
            _gen_synthetic_labs(session, sid)

            # ── Medications (from curated DCM regimens) ───────────────────────
            med_set = random.choice(DCM_MEDS)
            for (drug, dose, freq) in med_set:
                m = Medication(
                    subject_id=sid,
                    med_name=drug,
                    dose=dose,
                    frequency=freq,
                )
                session.add(m)

        session.commit()

    print(f"\n  Successfully ingested {len(patients_raw)} patients into local SQLite.")
    print("  Run `py -3 -m uvicorn main:app --reload` to start the API.")
    print("=" * 60)


def _gen_synthetic_vitals(session, subject_id, age):
    """Generate 12 hours of synthetic DCM vitals for demo patients."""
    now = datetime.now()
    for h in range(12, 0, -1):
        # DCM patients: slightly lower EF -> compensatory tachycardia, reduced BP
        hr   = max(50, min(140, int(90 + random.gauss(0, 18))))
        rr   = max(10, min(30,  int(18 + random.gauss(0, 4))))
        spo2 = max(84, min(99,  int(94 + random.gauss(0, 3))))
        sbp  = max(70, min(200, int(105 + random.gauss(0, 15))))
        dbp  = max(40, min(120, int(65  + random.gauss(0, 10))))
        temp = round(36.8 + random.gauss(0, 0.5), 1)
        temp = max(35.0, min(40.0, temp))

        hour_key = now.replace(minute=0, second=0, microsecond=0)
        hour_key = hour_key.replace(hour=(now.hour - h) % 24)

        session.add(VitalTimeSeries(
            subject_id=subject_id,
            chart_hour=hour_key.strftime("%Y-%m-%dT%H:00"),
            heart_rate=hr, resp_rate=rr, spo2=spo2,
            sbp=sbp, dbp=dbp, temperature=temp,
            consciousness="A", air_or_oxygen="Air",
        ))


def _gen_synthetic_labs(session, subject_id):
    """Generate synthetic lab values typical of DCM patients."""
    now = datetime.now()
    for h in [4, 8]:
        k_val  = round(random.uniform(2.9, 4.8), 1)   # K+ often low with diuretics
        cr_val = round(random.uniform(0.9, 2.5), 2)   # Creatinine often elevated (cardio-renal)
        la_val = round(random.uniform(1.0, 3.5), 1)   # Lactate elevated if low output
        hour_key = now.replace(hour=(now.hour - h) % 24, minute=0, second=0, microsecond=0)
        session.add(LabEvent(
            subject_id=subject_id,
            chart_hour=hour_key.strftime("%Y-%m-%dT%H:00"),
            potassium=k_val, creatinine=cr_val, lactate=la_val,
        ))


if __name__ == "__main__":
    ingest(max_patients=100)
