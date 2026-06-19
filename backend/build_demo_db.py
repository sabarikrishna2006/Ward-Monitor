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
from database import engine
from models import Base, Patient, VitalTimeSeries, LabEvent, Medication, Escalation, CcuTransfer, DrugLabAction
from sqlalchemy.orm import Session


def init_db_fresh():
    """Drop all tables and recreate — ensures schema is always up-to-date."""
    # Ensure the data/ directory exists (database.py points here)
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(data_dir, exist_ok=True)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

# ─── Demographics ─────────────────────────────────────────────────────────────
# 16 patients — realistic South Indian DCM cardiology ward names
# id, name, age, sex, ward_suffix, bed, complaint, scenario, diagnosis_short
PATIENTS = [
    # ── Ward 4B — 8 patients ──────────────────────────────────────────────────
    (10001, "Rajesh Kumar",      58, "M", "4B", "01", "DCM with HFrEF (EF 25%), NYHA III, Decompensated HF",    "critical_high",   "DCM · HFrEF (EF 25%)"),
    (10002, "Priya Sharma",      62, "F", "4B", "03", "DCM, Pulmonary Oedema, AF with RVR",                     "critical_dl",     "DCM · AF + pulm. oedema"),
    (10003, "Arun Verma",        71, "M", "4B", "05", "Ischaemic Cardiomyopathy, HF Exacerbation",               "warning_rr",      "Ischaemic CM · HF flare"),
    (10004, "Sunita Devi",       55, "F", "4B", "07", "DCM Post-Partum Cardiomyopathy, NYHA III",                "warning_spo2",    "Post-partum CM · NYHA III"),
    (10005, "Mohan Singh",       67, "M", "4B", "09", "DCM with Arrhythmia (VT), Cardiac Cachexia",             "stable_watch",    "DCM · VT risk"),
    (10006, "Kavitha Nair",      49, "F", "4B", "11", "DCM, NYHA II, Controlled, Medication Review",            "stable_meds",     "DCM · NYHA II (stable)"),
    (10007, "Suresh Patel",      73, "M", "4B", "13", "Dilated Cardiomyopathy, Cardiac Cachexia",               "stable_low",      "DCM · cachexia"),
    (10008, "Rekha Patel",       60, "F", "4B", "15", "DCM, Post-CRT-D Implant Recovery",                       "stable_low",      "DCM · post-CRT-D"),
    # ── Ward 4C — 8 patients ──────────────────────────────────────────────────
    (10009, "Vikram Sharma",     64, "M", "4C", "02", "DCM with Sepsis (qSOFA 2), Decompensated HF",            "critical_sepsis", "DCM · sepsis (qSOFA 2)"),
    (10010, "Anita Singh",       57, "F", "4C", "04", "DCM, NYHA III, Hyperkalemia on ACE+Spiro",               "critical_dl",     "DCM · hyperkalaemia risk"),
    (10011, "Deepak Rao",        69, "M", "4C", "06", "Ischaemic DCM, HF Exacerbation, AKI Stage 1",            "warning_akd",     "Ischaemic DCM · AKI-1"),
    (10012, "Meena Iyer",        52, "F", "4C", "08", "DCM with HFrEF (EF 30%), Persistent Dyspnoea",           "warning_hr",      "DCM · HFrEF (EF 30%)"),
    (10013, "Anand Gupta",       75, "M", "4C", "10", "DCM, Elderly, NYHA II, Digoxin on Low K+",               "warning_dl",      "DCM · digoxin + low K⁺"),
    (10014, "Saritha Pillai",    45, "F", "4C", "12", "DCM, Young-Onset, Post-myocarditis, NYHA II",            "stable_watch",    "DCM · post-myocarditis"),
    (10015, "Nitin Shah",        66, "M", "4C", "14", "DCM with AF, Rate-controlled, NYHA II",                  "stable_low",      "DCM · AF (rate-ctrl)"),
    (10016, "Asha Gupta",        70, "F", "4C", "16", "DCM, NYHA I, Post-discharge Monitoring",                 "stale_vitals",    "DCM · NYHA I"),
]

# Which patients live in the CCU vs the General Ward (step-down).
# Acute (critical/warning) stay in CCU; stable patients are in the General Ward.
# Exception: 10005 is a stable patient kept in CCU as a step-down CANDIDATE (seeds a pending transfer).
CCU_STEPDOWN_CANDIDATES = {10005}

def ward_location_for(subject_id, scenario):
    is_stable = scenario.startswith("stable") or scenario == "stale_vitals"
    if is_stable and subject_id not in CCU_STEPDOWN_CANDIDATES:
        return "GENERAL_WARD"
    return "CCU"

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
    "stale_vitals":    [("Bisoprolol","5mg","OD"),    ("Aspirin","75mg","OD")],
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
    "stale_vitals":    (75,  14, 98, 118, 75,  36.6, "A", "Air"),      # NEWS2 0, but stale
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
    "stale_vitals":    {"potassium": 4.0, "creatinine": 1.0, "lactate": 1.0, "inr": None},
}

# ─── DCM / heart-failure I/O profiles (urine ml/4h, fluid balance ml/24h) ──────
# Decompensated HF → fluid overload (positive balance) + low urine output.
# Stable/euvolaemic → balanced or slightly negative on diuretics, normal urine.
DCM_PROFILE = {
    "critical_high":   (160, 840),
    "critical_dl":     (140, 760),
    "critical_sepsis": (120, 320),
    "warning_rr":      (240, 350),
    "warning_spo2":    (260, 300),
    "warning_akd":     (180, 420),   # AKI → reduced urine
    "warning_hr":      (280, 250),
    "warning_dl":      (300, 180),
    "stable_watch":    (380, 120),
    "stable_meds":     (420, -50),
    "stable_low":      (450, -120),
    "stale_vitals":    (400, 0),
}


def gen_vitals_trajectory(session, subject_id, profile_key):
    """Generate 12 hourly vitals readings with realistic trend."""
    base_hr, base_rr, base_spo2, base_sbp, base_dbp, base_temp, consciousness, air_ox = VITALS_PROFILE[profile_key]
    u_base, fb_base = DCM_PROFILE.get(profile_key, (350, 0))
    now = datetime.now()

    # The "stale" patient's whole chart is pushed ~13h into the past so its last
    # reading is overdue even against the slow General-Ward cadence (12h).
    stale_shift = 13 if profile_key == "stale_vitals" else 0

    # For critical patients: trending worse over last 4 hours
    for h in range(12, 0, -1):
        m_offset = random.randint(-15, 15)
        hour_key = now - timedelta(hours=h + stale_shift) + timedelta(minutes=m_offset)

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
        # I/O worsens slightly with the same trend (less urine, more positive balance)
        urine = max(40,  int(u_base  - trend * 12 + random.gauss(0, 20)))
        fbal  = int(fb_base + trend * 25 + random.gauss(0, 30))

        session.add(VitalTimeSeries(
            subject_id    = subject_id,
            chart_hour    = hour_key.strftime("%Y-%m-%dT%H:%M"),
            heart_rate    = hr,
            resp_rate     = rr,
            spo2          = spo2,
            sbp           = sbp,
            dbp           = dbp,
            temperature   = temp,
            consciousness = consciousness,
            air_or_oxygen = air_ox,
            urine_output  = urine,
            fluid_balance = fbal,
        ))


def gen_labs(session, subject_id, profile_key):
    """Insert 2 lab readings (8h and 4h ago) for the patient."""
    labs = LAB_PROFILE[profile_key]
    now  = datetime.now()
    for hours_ago in [8, 4]:
        m_offset = random.randint(-20, 20)
        ts = now - timedelta(hours=hours_ago) + timedelta(minutes=m_offset)
        session.add(LabEvent(
            subject_id = subject_id,
            chart_hour = ts.strftime("%Y-%m-%dT%H:%M"),
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
    init_db_fresh()
    print("  Schema recreated (drop + create).")

    with Session(engine) as session:

        for i, (sid, name, age, sex, ward_suffix, bed, complaint, scenario, dx_short) in enumerate(PATIENTS, start=1):
            ward = f"Ward {ward_suffix}"
            loc  = ward_location_for(sid, scenario)

            patient = Patient(
                subject_id          = sid,
                patient_code        = f"PT-26-{i:04d}",
                name                = name,
                age                 = age,
                sex                 = sex,
                ward                = ward,
                room                = ward_suffix,
                bed                 = bed,
                admitted            = (datetime.now() - timedelta(days=random.randint(1, 7))).strftime("%d %b %Y"),
                complaint           = complaint,
                diagnosis_short     = dx_short,
                ward_location       = loc,
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

            print(f"  [OK] {name:20s}  Ward {ward_suffix}  Bed {bed}  {loc:13s} [{scenario}]")

        # ── Seed one pending CCU→GW step-down transfer (Mohan Singh, stable in CCU) ──
        session.add(CcuTransfer(
            subject_id          = 10005,
            patient_name        = "Mohan Singh",
            diagnosis           = "DCM · VT risk",
            rationale           = "NEWS2 ≤ 2 sustained 8h+; haemodynamically stable; "
                                  "no escalation in 24h; inotropes weaned off.",
            recommended_by      = "Nurse Rekha Devi",
            target_ward         = "General Ward",
            news2_at_submit     = 2,
            stable_window_hours = 8,
            status              = "pending",
            submitted_at        = (datetime.now() - timedelta(hours=1)).isoformat(timespec="minutes"),
        ))

        session.commit()

    print(f"\n  16 patients written to ward_careos.db")
    print("  Run backend: py -3 -m uvicorn main:app --reload --port 8000")
    print("=" * 60)


if __name__ == "__main__":
    build()
