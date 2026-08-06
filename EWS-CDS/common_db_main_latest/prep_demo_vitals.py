"""
prep_demo_vitals.py — run right before a demo.

Non-destructive top-up:
  1. Inserts ONE fresh vitals row (timestamp = now) for each demo patient
     91001-91006 so nobody shows OVERDUE, with a deliberate NEWS2 spread:
        91001 Ramesh   CRITICAL  (~12)
        91002 Lakshmi  CRITICAL  (~12)
        91003 Govind   MEDIUM    (5-6)   <- medium band now populated
        91004 Fatima   MEDIUM    (5-6)
        91005 Joseph   STABLE    (<=1)   step-down candidate
        91006 Anjali   STABLE    (0)
  2. Inserts one fresh STABLE vitals row for every other active patient
     (the billing/MIMIC admits) so they are de-escalation-ready
     (SpO2>=94, SBP>=90, NEWS2<=4) instead of "Overdue 139h".
  3. Resets Joseph Thomas (91005) to CCU and re-creates his PENDING
     CCU->GW transfer so the charge-nurse approval flow can be demoed again.

Run from common_db_main_latest/ (needs CLOUD_SQL_PASS):
    source .env.secrets && py -3 prep_demo_vitals.py
"""
import sys, os
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "sabari_project", "backend"))

from database import engine
from models import Patient, VitalTimeSeries, CcuTransfer
from sqlalchemy.orm import Session
from sqlalchemy import text

NOW = datetime.now()

# hadm_id -> (hr, rr, spo2, sbp, dbp, temp, avpu, o2)
DEMO_VITALS = {
    91001: (120, 26, 89,  84, 48, 36.9, "A", "Oxygen"),   # CRITICAL ~13
    91002: (124, 23, 87,  78, 48, 38.0, "A", "Oxygen"),   # CRITICAL ~12
    91003: ( 95, 22, 94, 105, 62, 38.3, "A", "Air"),      # MEDIUM 6
    91004: ( 96, 21, 95, 108, 64, 37.5, "A", "Air"),      # MEDIUM 5
    91005: ( 78, 15, 96, 112, 70, 36.8, "A", "Air"),      # STABLE <=1 (step-down)
    91006: ( 72, 14, 98, 118, 74, 36.7, "A", "Air"),      # STABLE 0
}
STABLE_ROW = (76, 16, 97, 116, 72, 36.9, "A", "Air")      # for billing/MIMIC patients

with Session(engine) as s:
    # Fetch all patients except signed_off/archived, and SKIP our specially seeded 
    # ML-demo patients (91007, 91008) so we don't accidentally overwrite their 
    # carefully staged trajectories with a flat 'stable' row!
    patients = s.query(Patient).filter(
        Patient.status.notin_(["signed_off", "archived"]),
        Patient.hadm_id.notin_([91007, 91008])
    ).all()
    demo_n, mimic_n = 0, 0
    for p in patients:
        hr, rr, spo2, sbp, dbp, temp, avpu, o2 = DEMO_VITALS.get(p.hadm_id, STABLE_ROW)
        s.add(VitalTimeSeries(
            hadm_id=p.hadm_id, chart_time=NOW,
            heart_rate=hr, resp_rate=rr, spo2=spo2, sbp=sbp, dbp=dbp,
            temperature=temp, consciousness=avpu, air_or_oxygen=o2,
        ))
        if p.hadm_id in DEMO_VITALS: demo_n += 1
        else: mimic_n += 1

    # Reset Joseph Thomas to CCU with a fresh pending step-down transfer
    joseph = s.query(Patient).filter(Patient.hadm_id == 91005).first()
    if joseph:
        joseph.ward_location = "CCU"
    has_pending = s.query(CcuTransfer).filter(
        CcuTransfer.hadm_id == 91005, CcuTransfer.status == "pending").first()
    if not has_pending:
        s.add(CcuTransfer(
            hadm_id=91005, patient_name="Joseph Thomas",
            diagnosis="DCM - VT risk", rationale="NEWS2 <= 2 sustained 8h+; haemodynamically stable.",
            recommended_by="Nurse Rekha Devi", target_ward="General Ward",
            news2_at_submit=1, stable_window_hours=8, status="pending",
            submitted_at=NOW,
        ))
    s.commit()

print(f"Fresh vitals: {demo_n} demo patients, {mimic_n} billing/MIMIC patients (all stamped {NOW:%H:%M})")
print("Joseph Thomas reset to CCU with a pending CCU->GW transfer.")
print("NEWS2 spread now: 2 critical / 2 medium / rest stable, nobody overdue.")
