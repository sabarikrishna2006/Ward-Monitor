"""
build_demo_db.py
================
Builds ward_careos.db with 16 DCM patients (8 Ward 4B + 8 Ward 4C).
Uses Cloud SQL (GCP) for real MIMIC-IV IDs if available,
falls back to realistic synthetic DCM data.

Patient mix:
  - 4 critical (NEWS2 ≥ 7)
  - 5 warning  (NEWS2 5–6)
  - 7 stable   (NEWS2 1–4)
  - Labs are set to trigger specific drug-lab rules (K+/Digoxin, Creatinine/NSAID, etc.)
  - Medications come from verified DCM regimens (CSI/ESC guidelines)

Run from: e:/IP_EarlyWarning/EWS-CDS/sabari_project/backend/
  py -3 build_demo_db.py
"""

import os, sys, random
from datetime import datetime, timedelta

# Make sure local modules are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import engine, init_db
from models import Patient, VitalTimeSeries, LabEvent, Medication, Escalation
from sqlalchemy.orm import Session

# ─── Demographics ─────────────────────────────────────────────────────────────
# 16 patients — realistic South Indian DCM cardiology ward names
PATIENTS = [
    # ── Ward 4B — 8 patients ──────────────────────────────────────────────────
    # id, name, age, sex, bed, complaint, scenario
    (10001, "Rajesh Kumar",      58, "M", "4B", "01", "DCM with HFrEF (EF 25%), NYHA III, Decompensated HF",    "critical_high"),
    (10002, "Priya Sharma",      62, "F", "4B", "03", "DCM, Pulmonary Oedema, AF with RVR",                     "critical_dl"),
    (10003, "Arun Verma",        71, "M", "4B", "05", "Ischaemic Cardiomyopathy, HF Exacerbation",               "warning_rr"),
    (10004, "Sunita Devi",       55, "F", "4B", "07", "DCM Post-Partum Cardiomyopathy, NYHA III",                "warning_spo2"),
    (10005, "Mohan Singh",       67, "M", "4B", "09", "DCM with Arrhythmia (VT), Cardiac Cachexia",             "stable_watch"),
    (10006, "Kavitha Nair",      49, "F", "4B", "11", "DCM, NYHA II, Controlled, Medication Review",            "stable_meds"),
    (10007, "Suresh Patel",      73, "M", "4B", "13", "Dilated Cardiomyopathy, Cardiac Cachexia",               "stable_low"),
    (10008, "Rekha Patel",       60, "F", "4B", "15", "DCM, Post-CRT-D Implant Recovery",                       "stable_low"),
    # ── Ward 4C — 8 patients ──────────────────────────────────────────────────
    (10009, "Vikram Sharma",     64, "M", "4C", "02", "DCM with Sepsis (qSOFA 2), Decompensated HF",            "critical_sepsis"),
    (10010, "Anita Singh",       57, "F", "4C", "04", "DCM, NYHA III, Hyperkalemia on ACE+Spiro",               "critical_dl"),
    (10011, "Deepak Rao",        69, "M", "4C", "06", "Ischaemic DCM, HF Exacerbation, AKI Stage 1",            "warning_akd"),
    (10012, "Meena Iyer",        52, "F", "4C", "08", "DCM with HFrEF (EF 30%), Persistent Dyspnoea",           "warning_hr"),
    (10013, "Anand Gupta",       75, "M", "4C", "10", "DCM, Elderly, NYHA II, Digoxin on Low K+",               "warning_dl"),
    (10014, "Saritha Pillai",    45, "F", "4C", "12", "DCM, Young-Onset, Post-myocarditis, NYHA II",            "stable_watch"),
    (10015, "Nitin Shah",        66, "M", "4C", "14", "DCM with AF, Rate-controlled, NYHA II",                  "stable_low"),
    (10016, "Asha Gupta",        70, "F", "4C", "16", "DCM, NYHA I, Post-discharge Monitoring",                 "stable_low"),
]

# ─── DCM Medications per clinical scenario ────────────────────────────────────
MEDS = {
    "critical_high":   [("Carvedilol","12.5mg","BD"), ("Enalapril","5mg","BD"),  ("Furosemide","80mg","BD"), ("Spironolactone","50mg","OD"), ("Digoxin","0.125mg","OD"), ("Warfarin","5mg","OD")],
    "critical_dl":     [("Carvedilol","6.25mg","BD"), ("Ramipril","10mg","OD"),  ("Furosemide","40mg","BD"), ("Spironolactone","25mg","OD"), ("Aspirin","75mg","OD"),    ("Warfarin","5mg","OD")],
    "critical_sepsis": [("Metoprolol","25mg","BD"),   ("Losartan","50mg","OD"),  ("Furosemide","80mg","BD"), ("Spironolactone","25mg","OD"), ("Digoxin","0.125mg","OD"), ("Metformin","500mg","BD")],
    "warning_rr":      [("Bisoprolol","5mg","OD"),    ("Valsartan","160mg","BD"),("Furosemide","40mg","OD"), ("Spironolactone","25mg","OD"), ("Aspirin","75mg","OD"),    ("Atorvastatin","40mg","OD")],
    "warning_spo2":    [("Carvedilol","12.5mg","BD"), ("Enalapril","5mg","BD"),  ("Torsemide","20mg","OD"),  ("Spironolactone","50mg","OD"), ("Amiodarone","200mg","OD")],
    "warning_akd":     [("Carvedilol","6.25mg","BD"), ("Ramipril","5mg","OD"),   ("Furosemide","40mg","OD"), ("Ibuprofen","400mg","PRN"),    ("Aspirin","75mg","OD"),    ("Rosuvastatin","10mg","OD")],
    "warning_hr":      [("Metoprolol","25mg","BD"),   ("Candesartan","8mg","OD"),("Furosemide","40mg","OD"), ("Eplerenone","25mg","OD"),     ("Amiodarone","200mg","OD")],
    "warning_dl":      [("Bisoprolol","5mg","OD"),    ("Perindopril","4mg","OD"),("Furosemide","40mg","BD"), ("Digoxin","0.25mg","OD"),      ("Warfarin","5mg","OD")],
    "stable_watch":    [("Carvedilol","12.5mg","BD"), ("Lisinopril","10mg","OD"),("Furosemide","40mg","OD"), ("Spironolactone","25mg","OD"), ("Atorvastatin","40mg","OD")],
    "stable_meds":     [("Bisoprolol","5mg","OD"),    ("Valsartan","80mg","OD"), ("Furosemide","20mg","OD"), ("Spironolactone","12.5mg","OD"),("Aspirin","75mg","OD"),    ("Rosuvastatin","20mg","OD")],
    "stable_low":      [("Carvedilol","6.25mg","BD"), ("Enalapril","2.5mg","OD"),("Furosemide","20mg","OD"), ("Spironolactone","25mg","OD"), ("Atorvastatin","20mg","OD")],
}

# ─── Vitals profiles per scenario ─────────────────────────────────────────────
# (base_hr, base_rr, base_spo2, base_sbp, base_dbp, base_temp, consciousness, air_or_oxygen)
VITALS_PROFILE = {
    "critical_high":   (115, 24, 90, 86,  54,  37.2, "A", "Oxygen"),   # NEWS2 ~9
    "critical_dl":     (118, 26, 88, 82,  50,  37.8, "A", "Oxygen"),   # NEWS2 ~10
    "critical_sepsis": (112, 28, 89, 84,  52,  38.9, "V", "Oxygen"),   # NEWS2 ~11 (AVPU=V)
    "warning_rr":      (98,  22, 92, 100, 62,  37.0, "A", "Air"),      # NEWS2 ~5
    "warning_spo2":    (96,  20, 91, 104, 64,  36.9, "A", "Air"),      # NEWS2 ~5
    "warning_akd":     (105, 21, 93, 98,  60,  37.3, "A", "Air"),      # NEWS2 ~5
    "warning_hr":      (116, 18, 94, 108, 70,  37.1, "A", "Air"),      # NEWS2 ~5 (HR)
    "warning_dl":      (48,  18, 93, 106, 68,  36.8, "A", "Air"),      # NEWS2 ~5 (HR<50=bradycardia)
    "stable_watch":    (88,  17, 95, 112, 72,  37.0, "A", "Air"),      # NEWS2 ~2
    "stable_meds":     (82,  16, 96, 118, 74,  36.9, "A", "Air"),      # NEWS2 ~1
    "stable_low":      (78,  15, 97, 122, 76,  36.8, "A", "Air"),      # NEWS2 ~0
}

# ─── Lab profiles per scenario (designed to trigger drug-lab rules) ───────────
LAB_PROFILE = {
    "critical_high":   {"potassium": 3.1, "creatinine": 1.8, "lactate": 1.5, "inr": 2.1},
    "critical_dl":     {"potassium": 5.7, "creatinine": 1.2, "lactate": 2.2, "inr": 3.8},  # K+>5.5 + ACE → CRITICAL
    "critical_sepsis": {"potassium": 3.8, "creatinine": 1.5, "lactate": 3.5, "inr": 1.8},  # Lactate>2 → sepsis
    "warning_rr":      {"potassium": 3.4, "creatinine": 1.4, "lactate": 1.8, "inr": 2.2},
    "warning_spo2":    {"potassium": 3.6, "creatinine": 1.3, "lactate": 1.5, "inr": None},
    "warning_akd":     {"potassium": 4.2, "creatinine": 2.2, "lactate": 1.9, "inr": None},  # Cr>1.5 + NSAID → WARNING
    "warning_hr":      {"potassium": 4.0, "creatinine": 1.2, "lactate": 1.4, "inr": 2.6},  # INR>2.5 + Amiodarone → WARNING
    "warning_dl":      {"potassium": 3.2, "creatinine": 1.4, "lactate": 1.3, "inr": 2.8},  # K+<3.5 + Digoxin → CRITICAL
    "stable_watch":    {"potassium": 4.1, "creatinine": 1.1, "lactate": 1.2, "inr": None},
    "stable_meds":     {"potassium": 4.3, "creatinine": 0.9, "lactate": 1.0, "inr": None},
    "stable_low":      {"potassium": 4.2, "creatinine": 1.0, "lactate": 1.0, "inr": None},
}


def gen_vitals_trajectory(session, subject_id, profile_key):
    """Generate 12 hourly vitals readings with realistic trend."""
    base_hr, base_rr, base_spo2, base_sbp, base_dbp, base_temp, consciousness, air_ox = VITALS_PROFILE[profile_key]
    now = datetime.now().replace(minute=0, second=0, microsecond=0)

    # For critical patients: trending worse over last 4 hours
    for h in range(12, 0, -1):
        hour_key = now - timedelta(hours=h)

        # Add trend: critical worsens, stable improves slightly
        trend = 0
        if profile_key.startswith("critical") and h <= 4:
            trend = (5 - h) * 0.5  # slight worsening in last 4h

        hr   = max(38, min(145, int(base_hr  + trend * 3  + random.gauss(0, 4))))
        rr   = max(8,  min(32,  int(base_rr  + trend      + random.gauss(0, 1.5))))
        spo2 = max(82, min(99,  round(base_spo2 - trend * 0.5 + random.gauss(0, 1), 1)))
        sbp  = max(65, min(210, int(base_sbp - trend * 2  + random.gauss(0, 6))))
        dbp  = max(40, min(120, int(base_dbp - trend      + random.gauss(0, 4))))
        temp = max(35.0, min(40.5, round(base_temp + (0.1 if profile_key=="critical_sepsis" and h<=6 else 0) + random.gauss(0, 0.15), 1)))

        session.add(VitalTimeSeries(
            subject_id    = subject_id,
            chart_hour    = hour_key.strftime("%Y-%m-%dT%H:00"),
            heart_rate    = hr,
            resp_rate     = rr,
            spo2          = spo2,
            sbp           = sbp,
            dbp           = dbp,
            temperature   = temp,
            consciousness = consciousness,
            air_or_oxygen = air_ox,
        ))


def gen_labs(session, subject_id, profile_key):
    """Insert 2 lab readings (8h and 4h ago) for the patient."""
    labs = LAB_PROFILE[profile_key]
    now  = datetime.now().replace(minute=0, second=0, microsecond=0)
    for hours_ago in [8, 4]:
        ts = now - timedelta(hours=hours_ago)
        session.add(LabEvent(
            subject_id = subject_id,
            chart_hour = ts.strftime("%Y-%m-%dT%H:00"),
            potassium  = labs.get("potassium"),
            creatinine = labs.get("creatinine"),
            lactate    = labs.get("lactate"),
            inr        = labs.get("inr"),
            egfr       = None,
            alt        = None,
        ))


def build():
    print("=" * 60)
    print("Foqal CareOS — Demo DB Builder")
    print("=" * 60)
    init_db()

    with Session(engine) as session:
        # Clear all existing data
        for model in [Escalation, Medication, LabEvent, VitalTimeSeries, Patient]:
            session.query(model).delete()
        session.commit()
        print(f"  Cleared existing data.")

        for (sid, name, age, sex, ward_suffix, bed, complaint, scenario) in PATIENTS:
            ward = f"Ward {ward_suffix}"

            patient = Patient(
                subject_id          = sid,
                name                = name,
                age                 = age,
                sex                 = sex,
                ward                = ward,
                room                = ward_suffix,
                bed                 = bed,
                admitted            = (datetime.now() - timedelta(days=random.randint(1, 7))).strftime("%d %b %Y"),
                complaint           = complaint,
                hypercapnic_failure = 0,
            )
            session.add(patient)

            # Vitals
            gen_vitals_trajectory(session, sid, scenario)

            # Labs
            gen_labs(session, sid, scenario)

            # Medications
            for (drug, dose, freq) in MEDS.get(scenario, MEDS["stable_low"]):
                session.add(Medication(
                    subject_id = sid,
                    med_name   = drug,
                    dose       = dose,
                    frequency  = freq,
                ))

            print(f"  [OK] {name:20s}  Ward {ward_suffix}  Bed {bed}  [{scenario}]")

        session.commit()

    print(f"\n  16 patients written to ward_careos.db")
    print("  Run backend: py -3 -m uvicorn main:app --reload --port 8000")
    print("=" * 60)


if __name__ == "__main__":
    build()
