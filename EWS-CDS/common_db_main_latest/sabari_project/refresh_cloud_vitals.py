"""
Run this once, shortly before tomorrow's demo starts, to clear every patient's
"stale vitals" flag EXCEPT the two seeded demo-arc patients (Vikram Rao,
hadm_id 91007 CCU / 91008 General Ward) -- those must stay exactly as
seed_demo_arc_patient.py left them, untouched, so the escalation/de-escalation
walkthrough starts from its tested baseline.

For every other active patient, copies their MOST RECENT vitals reading
forward to right now (all fields: hr/rr/spo2/sbp/dbp/temp/consciousness/
air_or_oxygen/urine_output/fluid_balance/weight_kg) -- this is exactly what a
nurse re-checking and finding "no change" looks like clinically. It does NOT
alter anyone's NEWS2/status/escalation risk, it only refreshes the timestamp
so monitoring_plan()'s overdue check in main.py stops flagging them.

Run: CLOUD_SQL_PASS=... py -3 refresh_cloud_vitals.py
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from database import SessionLocal
from models import Patient, VitalTimeSeries

PROTECTED_HADM_IDS = {91007, 91008}  # Vikram Rao -- never touch these


def main():
    db = SessionLocal()
    try:
        patients = db.query(Patient).filter(
            Patient.status.notin_(["signed_off", "archived"])
        ).all()

        refreshed, skipped_protected, skipped_no_vitals = 0, 0, 0
        for p in patients:
            if p.hadm_id in PROTECTED_HADM_IDS:
                skipped_protected += 1
                continue

            last = (
                db.query(VitalTimeSeries)
                .filter(VitalTimeSeries.hadm_id == p.hadm_id)
                .order_by(VitalTimeSeries.chart_time.desc())
                .first()
            )
            if not last:
                skipped_no_vitals += 1
                continue

            db.add(VitalTimeSeries(
                hadm_id=p.hadm_id,
                chart_time=datetime.now(),
                heart_rate=last.heart_rate, resp_rate=last.resp_rate, spo2=last.spo2,
                sbp=last.sbp, dbp=last.dbp, temperature=last.temperature,
                consciousness=last.consciousness, air_or_oxygen=last.air_or_oxygen,
                urine_output=last.urine_output, fluid_balance=last.fluid_balance,
                weight_kg=last.weight_kg,
            ))
            refreshed += 1

        db.commit()
        print(f"Refreshed {refreshed} patients' vitals to now().")
        print(f"Skipped {skipped_protected} protected demo-arc patients (91007/91008 untouched).")
        print(f"Skipped {skipped_no_vitals} patients with no prior vitals to copy forward.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
