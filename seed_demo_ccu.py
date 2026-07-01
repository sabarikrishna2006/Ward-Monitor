"""
Non-destructive demo seeder: adds 6 CCU demo patients with full 12h vitals
trajectories + labs + meds, WITHOUT truncating active_patients (so the 10 MIMIC
patients stay intact for the BigQuery/mimic_sync path).

Uses safe hadm_ids (91001-91006) that won't clash with MIMIC IDs or the
10001-10016 build_demo_db range. Reuses build_demo_db's tested trajectory logic.

Run from common_db/:  py seed_demo_ccu.py
"""
import sys, os, uuid
from datetime import datetime, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "sabari_project", "backend"))

from database import engine
from models import Patient, Medication, CcuTransfer, Escalation, DrugLabAction
from sqlalchemy.orm import Session
from sqlalchemy import text
import build_demo_db as bd   # reuse gen_vitals_trajectory, gen_labs, MEDS, ward_location_for

# 6 CCU/GW demo patients spanning the NEWS2 spectrum
DEMO = [
    (91001, "Ramesh Iyer",   61, "M", "4B", "21", "DCM HFrEF (EF 25%), Decompensated HF",   "critical_high", "DCM HFrEF (EF 25%)"),
    (91002, "Lakshmi Menon", 58, "F", "4B", "22", "DCM, AF with RVR, Pulmonary Oedema",      "critical_dl",   "DCM AF + pulm. oedema"),
    (91003, "Govind Rao",    70, "M", "4B", "23", "Ischaemic Cardiomyopathy, HF Exacerbation","warning_rr",   "Ischaemic CM HF flare"),
    (91004, "Fatima Begum",  53, "F", "4C", "24", "Post-Partum Cardiomyopathy, NYHA III",     "warning_spo2", "PPCM NYHA III"),
    (91005, "Joseph Thomas", 66, "M", "4C", "25", "DCM with VT risk (step-down candidate)",   "stable_watch", "DCM VT risk"),
    (91006, "Anjali Nair",   47, "F", "4C", "26", "DCM, NYHA II, Controlled",                 "stable_meds",  "DCM NYHA II (stable)"),
]
STEPDOWN_CANDIDATE = 91005   # seed a pending CCU->GW transfer for this one

print("=" * 64)
print("Seeding 6 demo CCU patients (non-destructive, IDs 91001-91006)")
print("=" * 64)

seeded, skipped = 0, 0
with Session(engine) as s:
    for sid, name, age, sex, ward_suffix, bed, complaint, scenario, dx in DEMO:
        if s.query(Patient).filter(Patient.hadm_id == sid).first():
            print(f"  [skip] {sid} {name} already exists")
            skipped += 1
            continue
        # CCU for acute, GENERAL_WARD for stable (except step-down candidate stays CCU)
        loc = "CCU" if (sid == STEPDOWN_CANDIDATE or not scenario.startswith("stable")) else "GENERAL_WARD"
        s.add(Patient(
            hadm_id=sid, subject_id=sid,
            patient_code=f"PT-26-{sid}", patient_name=name, anchor_age=age,
            gender=sex, ward=f"Ward {ward_suffix}", room=ward_suffix, bed=bed,
            admit_time=datetime.now() - timedelta(days=2), ews_complaint=complaint,
            admitting_diagnosis=complaint, diagnosis_short=dx, ward_location=loc,
            hypercapnic_failure=0, status="active", data_fetch_status="fetched",
        ))
        s.flush()   # ensure active_patients row exists before FK-referencing vitals/labs
        bd.gen_vitals_trajectory(s, sid, scenario)   # 12 hourly readings
        bd.gen_labs(s, sid, scenario)                # 2 lab rows (designed to trigger drug-lab rules)
        for drug, dose, freq in bd.MEDS.get(scenario, bd.MEDS["stable_low"]):
            s.add(Medication(hadm_id=sid, med_name=drug, dose=dose, frequency=freq))
        print(f"  [ok]   {name:16s} Ward {ward_suffix} Bed {bed}  {loc:13s} [{scenario}]")
        seeded += 1
    s.flush()

    # Pending step-down transfer for Joseph Thomas
    if not s.query(CcuTransfer).filter(CcuTransfer.hadm_id == STEPDOWN_CANDIDATE).first():
        s.add(CcuTransfer(
            hadm_id=STEPDOWN_CANDIDATE, patient_name="Joseph Thomas",
            diagnosis="DCM · VT risk", rationale="NEWS2 <= 2 sustained 8h+; haemodynamically stable.",
            recommended_by="Nurse Rekha Devi", target_ward="General Ward",
            news2_at_submit=2, stable_window_hours=8, status="pending",
            submitted_at=datetime.now() - timedelta(hours=1),
        ))

    # Escalations for critical patients (skip if already seeded for this hadm_id)
    ESCS = [
        # hadm_id, name, ward, bed, news2, level, observations, interventions, hrs_ago_start, hrs_ago_resolved
        (91001, "Ramesh Iyer",   "Ward 4B", "21", 9,  "doctor",
         "RR 26, SpO2 88%, BP 84/52 — supplemental O₂ in use",
         "O₂ titrated to 6L; head-of-bed 45°; furosemide 40mg IV stat",
         3, 1),
        (91002, "Lakshmi Menon", "Ward 4B", "22", 10, "consultant",
         "HR 128 AF with RVR, SpO2 86%, RR 28, bilateral crepitations",
         "Metoprolol IV rate-control; aggressive diuresis; cardiology called",
         5, None),  # still active
    ]
    for sid, sname, ward, bed, snews, slvl, sobs, sint, hrs_start, hrs_res in ESCS:
        if not s.query(Escalation).filter(Escalation.hadm_id == sid).first():
            esc = Escalation(
                hadm_id=sid, patient_name=sname, ward=ward, bed=bed,
                news2_score=snews, level=slvl, status="active" if hrs_res is None else "resolved",
                observations=sobs, interventions=sint,
                escalated_by="Nurse Rekha Devi", attending="Dr. Anand Sharma",
                escalated_at=datetime.now() - timedelta(hours=hrs_start),
            )
            if hrs_res is not None:
                esc.resolved_by = "Dr. Anand Sharma"
                esc.resolution_notes = "Patient stabilised post-intervention."
                esc.resolved_at = datetime.now() - timedelta(hours=hrs_res)
            s.add(esc)

    # Drug-Lab safety flags (NABH DL2) — pre-seeded so dashboard shows real interactions
    DLS = [
        # hadm_id, name, rule, severity, action, justification, recorded_by, cosigned_by, hrs_ago
        (91002, "Lakshmi Menon", "K⁺ + ACE Inhibitor", "CRITICAL",
         "held dose",
         "K⁺ 5.7 mmol/L with Ramipril active. Hold ACE inhibitor; recheck K⁺ in 4h.",
         "Nurse Rekha Devi", "Dr. Anand Sharma", 4),
        (91003, "Govind Rao",    "Creatinine + NSAID",  "WARNING",
         "held dose",
         "Creatinine 2.1 (AKI Stage 1). Ibuprofen held; switch to paracetamol.",
         "Nurse Rekha Devi", "Dr. Priya Mehta", 2),
    ]
    for sid, sname, rule, severity, action, justification, recby, cosby, hrs_ago in DLS:
        if not s.query(DrugLabAction).filter(DrugLabAction.hadm_id == sid).first():
            s.add(DrugLabAction(
                hadm_id=sid, rule_name=rule, severity=severity,
                action_taken=action, justification=justification,
                recorded_by=recby, cosigned_by=cosby,
                recorded_at=datetime.now() - timedelta(hours=hrs_ago),
            ))

    s.commit()

# app_encounters (so Ashmit's doctor queue sees them) + hospital_core bridge
with engine.begin() as c:
    hosp = c.execute(text("SELECT hospital_id FROM hospital_core.hospitals LIMIT 1")).fetchone()
    ward = c.execute(text("SELECT ward_id FROM hospital_core.wards LIMIT 1")).fetchone()
    for sid, name, *_ in DEMO:
        uhid = f"FOQAL-2026-{sid:07d}"
        c.execute(text("""
            INSERT INTO app_encounters (id, hadm_id, display_id, status, version, created_at, updated_at)
            VALUES (gen_random_uuid(), :h, :did, 'Pending Ingestion', 1, NOW(), NOW())
            ON CONFLICT (hadm_id) DO NOTHING
        """), {"h": sid, "did": f"PT-26-{sid}"})
        c.execute(text("""
            INSERT INTO hospital_core.patients (uhid, hospital_id, full_name, sex)
            VALUES (:u, :h, :n, 'M') ON CONFLICT (uhid) DO NOTHING
        """), {"u": uhid, "h": hosp[0], "n": name})
        c.execute(text("""
            INSERT INTO hospital_core.admissions
                (admission_id, uhid, hospital_id, ward_id, hadm_id, status, admitted_at, updated_at)
            VALUES (gen_random_uuid(), :u, :h, :w, :hid, 'admitted', NOW(), NOW())
            ON CONFLICT (hadm_id) DO NOTHING
        """), {"u": uhid, "h": hosp[0], "w": ward[0] if ward else None, "hid": sid})

# Verify
with engine.connect() as c:
    npat = c.execute(text("SELECT COUNT(*) FROM active_patients WHERE hadm_id BETWEEN 91001 AND 91006")).scalar()
    nvit = c.execute(text("SELECT COUNT(*) FROM ews_vitals_timeseries WHERE hadm_id BETWEEN 91001 AND 91006")).scalar()
    nbridge = c.execute(text("SELECT COUNT(*) FROM hospital_core.admissions WHERE hadm_id BETWEEN 91001 AND 91006")).scalar()

print("=" * 64)
print(f"Seeded {seeded}, skipped {skipped}")
print(f"  active_patients (91001-91006):        {npat}")
print(f"  ews_vitals_timeseries rows:           {nvit}  (expect ~72 = 6 x 12)")
print(f"  hospital_core.admissions bridge rows: {nbridge}")
print("=" * 64)
print("Start the Sabari backend (port 7816) + frontend to view the ward board.")
