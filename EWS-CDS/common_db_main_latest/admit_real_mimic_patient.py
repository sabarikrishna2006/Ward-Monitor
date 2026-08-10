"""
Admits real MIMIC-IV patients (real hourly vitals from the offline
extraction already sitting in ml/data/vitals_hourly_esc.parquet -- the exact
same source the escalation model was trained/tested on) into the live
demo cohort.

Does NOT touch Ashmit's ap_* tables and does not fabricate any number: the
vitals are the patient's actual recorded MIMIC-IV readings, re-timestamped
(same technique mimic_sync.py already uses) so the most recent one lands
~30 min ago.

Run: PYTHONUTF8=1 py -3 admit_real_mimic_patient.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "sabari_project", "backend"))

_env_path = os.path.join(os.path.dirname(__file__), ".env.secrets")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line.startswith("export "):
                _line = _line[len("export "):]
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"'))
os.environ.setdefault(
    "GOOGLE_APPLICATION_CREDENTIALS",
    os.path.join(os.path.dirname(__file__), "foqal-healthcare-project-google.json")
)

from datetime import datetime, timedelta
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ml"))
import config  # noqa: F401  -- registers db_dtypes so the parquet reads work

from database import SessionLocal
from models import Patient, VitalTimeSeries

# (hadm_id, subject_id, stay_id, anchor_cutoff, age, gender, display_name, ward, room, bed, dx_code, dx_title)
CANDIDATES = [
    # cutoffs chosen so each patient has >=18h of real trailing history behind
    # their non-vacuous anchor, not just the first hour or two of the stay
    (28986995, 15484593, 36801408, "2120-11-28 20:00:00", 59, "M", "Mohan Krishnan", "Ward 4B", "03", "03",
     "I5023", "Acute-on-chronic Systolic HF (DCM)"),
    (25178486, 11205212, 37385542, "2174-07-11 05:00:00", 73, "M", "Prakash Nair", "Ward 4C", "18", "18",
     "I5023", "Acute-on-chronic Systolic HF (DCM)"),
    (25867490, 11767260, 38547739, "2165-11-15 19:00:00", 76, "M", "Anand Menon", "Ward 4B", "05", "05",
     "I420", "Dilated Cardiomyopathy"),
]

def admit_one(hadm_id, subject_id, stay_id, anchor_cutoff, age, gender, name, ward, room, bed, dx_code, dx_title, db):
    existing = db.query(Patient).filter(Patient.hadm_id == hadm_id).first()
    if existing:
        print(f"hadm_id {hadm_id} already in active_patients -- skipping, not touching it.")
        return False

    v = pd.read_parquet(os.path.join("ml", "data", "vitals_hourly_esc.parquet"))
    cutoff = pd.Timestamp(anchor_cutoff)
    sub = v[(v.stay_id == stay_id) & (v.hour <= cutoff)].sort_values("hour")
    sub = sub.dropna(subset=["heart_rate", "resp_rate", "sbp", "dbp", "spo2"], how="all")
    if sub.empty:
        print(f"No real vitals rows found for stay_id={stay_id} -- skipping.")
        return False

    mimic_last = sub.hour.max()
    target_last = datetime.now() - timedelta(minutes=30)
    offset = target_last - mimic_last.to_pydatetime()

    p = Patient(
        hadm_id=hadm_id, subject_id=subject_id,
        anchor_age=age, gender=gender,
        patient_name=name,  # display placeholder -- MIMIC-IV is de-identified, no real name exists
        patient_code=f"PT-MIMIC-{hadm_id}",
        ward=ward, room=room, bed=bed,
        ward_location="CCU",
        hypercapnic_failure=0,
        diagnosis_short=dx_title,
        primary_diagnosis_title=f"{dx_code} {dx_title}",
        ews_complaint=dx_title,
        admitting_diagnosis=dx_title,
        admit_time=datetime.now() - timedelta(hours=len(sub)),
        status="active",
        data_fetch_status="fetched",
    )
    db.add(p)
    db.flush()

    def _n(x):
        # NaN must become NULL, not a literal float NaN -- a NaN written to a
        # Decimal-compared column (calculate_news2's _score_range) raises
        # decimal.InvalidOperation downstream, crashing the whole ward-data
        # response for every patient, not just this one.
        return None if pd.isna(x) else float(x)

    inserted = 0
    for _, row in sub.iterrows():
        new_time = row.hour.to_pydatetime() + offset
        consciousness = row.get("consciousness") or "A"
        db.add(VitalTimeSeries(
            hadm_id=hadm_id, chart_time=new_time,
            heart_rate=_n(row.get("heart_rate")), resp_rate=_n(row.get("resp_rate")),
            spo2=_n(row.get("spo2")), sbp=_n(row.get("sbp")), dbp=_n(row.get("dbp")),
            temperature=_n(row.get("temperature")),
            consciousness=consciousness,
            air_or_oxygen=row.get("air_or_oxygen") or "Air",
        ))
        inserted += 1
    db.commit()
    print(f"Admitted hadm_id={hadm_id} ({name}): {inserted} real vitals rows, re-anchored to end at {target_last}.")
    return True

def main():
    db = SessionLocal()
    try:
        for c in CANDIDATES:
            admit_one(*c, db=db)
    finally:
        db.close()

if __name__ == "__main__":
    main()
