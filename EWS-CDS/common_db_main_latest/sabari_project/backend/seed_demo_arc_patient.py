"""
Seeds ONE dedicated demo patient (hadm_id=91007, continuing the existing
91001-91006 demo-patient numbering already used in build_demo_db.py) with a
backdated vitals trend ending just before "now", so the live demo can start
with him already visibly elevated (HIGH tier, NEWS2 5-6) and the presenter
pushes him into CRITICAL and back down to stable LIVE via the real Nurse
Vitals Entry screen (N_VITALS) during the demo -- no scripted state changes
during the actual presentation, only real API calls through real UI.

Pre-seeded (this script, run once before the demo):
  - Patient row with a SANE admit_time (~30h before "now" -- MIMIC-sourced
    patients can carry de-identified admission dates decades away from
    wall-clock "now", which the escalation model has no tolerance for; see
    escalation_model.py's hours_since_adm sanity fallback).
  - A backdated vitals trend from admission through ~2h before "now": stable,
    then climbing into WARNING range (NEWS2 5-6, HIGH escalation tier).
  - Admission labs including potassium 5.8 (hyperkalemia range) and a
    lisinopril (ACE inhibitor) order -- together trigger drug_lab_rules.yaml's
    "Hyperkalemia risk with ACE inhibitors" CRITICAL rule immediately, no live
    action needed to show it.

NOT seeded (left for the live demo via the real /vitals endpoint + N_VITALS
screen): the final deterioration reading that pushes him to CRITICAL, and the
recovery readings that bring him back down. Those are real, presenter-typed,
live API calls -- watch them happen, don't narrate them from history.

Run: CLOUD_SQL_PASS=... py -3 seed_demo_arc_patient.py
"""
import os
from datetime import datetime, timedelta

from database import SessionLocal
from models import Patient, VitalTimeSeries, LabEvent, Medication, Escalation, DrugLabAction

HADM_ID = 91007
NOW = datetime.now()
ADMIT = NOW - timedelta(hours=30)


def upsert_patient(db):
    p = db.query(Patient).filter(Patient.hadm_id == HADM_ID).first()
    if p:
        db.delete(p)
        db.query(VitalTimeSeries).filter(VitalTimeSeries.hadm_id == HADM_ID).delete()
        db.query(LabEvent).filter(LabEvent.hadm_id == HADM_ID).delete()
        # Escalation/DrugLabAction history also needs clearing on reset -- a
        # prior dry run's "escalate" or "co-sign" test action otherwise
        # silently persists across reseeds (found during pre-demo QA: a test
        # escalation and a test co-sign action both survived a reseed here).
        db.query(Escalation).filter(Escalation.hadm_id == HADM_ID).delete()
        db.query(DrugLabAction).filter(DrugLabAction.hadm_id == HADM_ID).delete()
        db.query(Medication).filter(Medication.hadm_id == HADM_ID).delete()
        db.commit()

    p = Patient(
        hadm_id=HADM_ID, subject_id=HADM_ID, patient_code="PT-26-9107",
        patient_name="Vikram Rao", anchor_age=61, gender="M",
        ward="Ward 4B", room="12", bed="3",
        admit_time=ADMIT, ews_complaint="Chest pain, breathlessness",
        admitting_diagnosis="Decompensated heart failure",
        ward_location="CCU", status="active", data_fetch_status="fetched",
        hypercapnic_failure=0,
    )
    db.add(p)
    db.commit()
    return p


def seed_vitals(db):
    # (hours-before-now, hr, rr, spo2, sbp, dbp, temp) -- deliberately a SLOW,
    # MONOTONIC creep, each individual reading staying under NEWS2's own
    # warning/critical thresholds (so NEWS2 alone still reads low-moderate at
    # demo start), while the trend across all 7 points -- rising HR, falling
    # SBP/SpO2, rising RR -- is exactly what the escalation model's _rate/_std
    # features are built to catch. This is the actual point of the model: it
    # should read elevated BEFORE NEWS2 crosses its own threshold, not after.
    # A trajectory that instead waits until NEWS2 is already critical (the
    # first version of this script) undersells the product by showing the
    # model agreeing with what's already obvious rather than leading it.
    # Tested empirically tonight: this vitals-only model does NOT respond to a
    # slow creep OR a sharp compressed slope while values stay under NEWS2's
    # own thresholds -- both attempts left escalation risk near/below the 9.5%
    # base rate (2.5-3.1%). It responds to genuinely abnormal ABSOLUTE values.
    # So the baseline is deliberately boring on both signals -- nothing to
    # reconcile -- and the live bad-reading injection (see the demo script) is
    # the one moment, already verified, where NEWS2 and escalation risk jump
    # together (7->13-14 and 3.7%->21.3% respectively). Do not stage this
    # patient as a "the AI predicted it before NEWS2" example; that claim
    # belongs to the population-level median-lead-time statistic in the
    # practitioner stats panel (measured on held-out test data), not to a
    # hand-crafted trajectory that was tested and does not show it.
    points = [
        (16, 74, 15, 98, 120, 78, 36.7),
        (12, 76, 16, 98, 118, 76, 36.8),
        (8,  75, 16, 97, 120, 77, 36.7),
        (4,  77, 16, 97, 118, 75, 36.8),
        (1,  76, 15, 98, 119, 76, 36.7),
    ]
    for hrs_ago, hr, rr, spo2, sbp, dbp, temp in points:
        db.add(VitalTimeSeries(
            hadm_id=HADM_ID, chart_time=NOW - timedelta(hours=hrs_ago),
            heart_rate=hr, resp_rate=rr, spo2=spo2, sbp=sbp, dbp=dbp,
            temperature=temp, consciousness="A", air_or_oxygen="Air",
        ))
    db.commit()


def seed_labs_and_meds(db):
    # potassium 5.2 (not >5.5) triggers ONLY the WARNING-tier "early warning"
    # rule, not the CRITICAL hyperkalemia rule -- deliberately, so it doesn't
    # force status='critical'/news2=7 via main.py's critical-drug-lab-flag
    # override and contaminate the NEWS2-vs-escalation-model comparison this
    # trajectory exists to demonstrate. It's still a real, visible, non-zero
    # drug-lab flag for the P4 beat -- just not one that overrides NEWS2.
    db.add(LabEvent(
        hadm_id=HADM_ID, chart_time=ADMIT + timedelta(hours=1),
        potassium=5.2, creatinine=1.3, sodium=137, hemoglobin=12.4,
    ))
    db.add(Medication(hadm_id=HADM_ID, med_name="Lisinopril", dose="10mg", frequency="OD"))
    db.add(Medication(hadm_id=HADM_ID, med_name="Furosemide", dose="40mg", frequency="BD"))
    db.commit()


HADM_ID_2 = 91008  # "later that day" — Vikram Rao stepped down to General Ward,
                    # drug-lab conflict resolved, escalation risk back to LOW.
                    # A separate hadm_id because patient identity in this system
                    # is keyed on hadm_id, but same name/context so the demo
                    # narration reads as a continuation, not a new admission.


def upsert_recovered_patient(db):
    p = db.query(Patient).filter(Patient.hadm_id == HADM_ID_2).first()
    if p:
        db.delete(p)
        db.query(VitalTimeSeries).filter(VitalTimeSeries.hadm_id == HADM_ID_2).delete()
        db.query(LabEvent).filter(LabEvent.hadm_id == HADM_ID_2).delete()
        db.query(Medication).filter(Medication.hadm_id == HADM_ID_2).delete()
        db.query(Escalation).filter(Escalation.hadm_id == HADM_ID_2).delete()
        db.query(DrugLabAction).filter(DrugLabAction.hadm_id == HADM_ID_2).delete()
        db.commit()

    p = Patient(
        hadm_id=HADM_ID_2, subject_id=HADM_ID_2, patient_code="PT-26-9108",
        patient_name="Vikram Rao", anchor_age=61, gender="M",
        ward="Ward 2A", room="5", bed="1",
        admit_time=ADMIT, ews_complaint="Chest pain, breathlessness (step-down from CCU)",
        admitting_diagnosis="Decompensated heart failure — stabilised",
        ward_location="GENERAL_WARD", status="active", data_fetch_status="fetched",
        hypercapnic_failure=0,
    )
    db.add(p)
    db.commit()

    # A clean run of normal readings with NO spike anywhere in history, so both
    # the hysteresis latch and the 6-clock-hour feature window are genuinely
    # clear -- this reaches true LOW RISK, not just a released-but-elevated
    # HIGH, which a patient with a recent real spike could not honestly show
    # this soon (see escalation_model.py's HYSTERESIS_ANCHORS note).
    points = [
        (10, 78, 16, 97, 118, 76, 36.9),
        (8,  76, 16, 98, 116, 74, 36.8),
        (6,  74, 15, 98, 118, 76, 36.7),
        (4,  75, 15, 98, 120, 78, 36.7),
        (2,  74, 14, 99, 118, 76, 36.6),
        (0.5, 73, 14, 99, 118, 75, 36.6),
    ]
    for hrs_ago, hr, rr, spo2, sbp, dbp, temp in points:
        db.add(VitalTimeSeries(
            hadm_id=HADM_ID_2, chart_time=NOW - timedelta(hours=hrs_ago),
            heart_rate=hr, resp_rate=rr, spo2=spo2, sbp=sbp, dbp=dbp,
            temperature=temp, consciousness="A", air_or_oxygen="Air",
        ))
    db.commit()

    # Hyperkalemia resolved: potassium back to normal range, lisinopril held
    # (per the drug-lab action taken), only furosemide continued -- no
    # medication in the ACE-inhibitor/K-sparing-diuretic group remains active,
    # so drug_lab_rules.yaml's hyperkalemia rule no longer fires.
    db.add(LabEvent(
        hadm_id=HADM_ID_2, chart_time=NOW - timedelta(hours=3),
        potassium=4.3, creatinine=1.1, sodium=139, hemoglobin=12.6,
    ))
    db.add(Medication(hadm_id=HADM_ID_2, med_name="Furosemide", dose="40mg", frequency="BD"))
    db.commit()


def main():
    db = SessionLocal()
    try:
        upsert_patient(db)
        seed_vitals(db)
        seed_labs_and_meds(db)
        print(f"Seeded demo patient hadm_id={HADM_ID} (Vikram Rao, CCU), admit_time={ADMIT}")

        upsert_recovered_patient(db)
        print(f"Seeded demo patient hadm_id={HADM_ID_2} (Vikram Rao, stepped down to GW)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
