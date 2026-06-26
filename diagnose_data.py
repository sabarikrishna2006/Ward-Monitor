"""
Diagnostic: what data actually exists in Cloud SQL for the 10 cardiology seed patients?
Tells us whether mimic_sync (ap_* -> ews_*) can run WITHOUT BigQuery.
Run from common_db/:  py diagnose_data.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "sabari_project", "backend"))
from database import engine
from sqlalchemy import text

SEED = [25434637, 20553493, 28113079, 24339216, 28855911,
        29950776, 26972341, 26935676, 24823642, 23149252]

with engine.connect() as c:
    print("=" * 70)
    print("active_patients / ews_* (public) — what the WARD BOARD reads")
    print("=" * 70)
    for t in ["active_patients", "ews_vitals_timeseries", "ews_lab_events",
              "ews_medications", "ews_escalations", "ews_ccu_transfers"]:
        n = c.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
        print(f"  {t:28s} {n:>8} rows")

    print("\n" + "=" * 70)
    print("ap_* MIMIC cache (public) — what mimic_sync READS from")
    print("=" * 70)
    for t in ["ap_admissions", "ap_chartevents", "ap_labevents",
              "ap_prescriptions", "ap_outputevents", "ap_diagnoses"]:
        try:
            n = c.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            print(f"  {t:28s} {n:>8} rows total")
        except Exception as e:
            print(f"  {t:28s}  ERROR: {str(e)[:50]}")

    print("\n" + "=" * 70)
    print("Per-patient ap_chartevents / ap_labevents counts (the 10 seed pts)")
    print("=" * 70)
    for h in SEED:
        ce = c.execute(text("SELECT COUNT(*) FROM ap_chartevents WHERE hadm_id=:h"), {"h": h}).scalar()
        le = c.execute(text("SELECT COUNT(*) FROM ap_labevents  WHERE hadm_id=:h"), {"h": h}).scalar()
        rx = c.execute(text("SELECT COUNT(*) FROM ap_prescriptions WHERE hadm_id=:h"), {"h": h}).scalar()
        inap = c.execute(text("SELECT COUNT(*) FROM active_patients WHERE hadm_id=:h"), {"h": h}).scalar()
        flag = "OK sync-able" if (ce or le) else "EMPTY -> needs BigQuery fetch"
        print(f"  hadm {h}: chart={ce:>6} lab={le:>5} rx={rx:>4} active_pt={inap}  [{flag}]")

    print("\n" + "=" * 70)
    print("hospital_core.admissions bridge (new schema)")
    print("=" * 70)
    n = c.execute(text("SELECT COUNT(*) FROM hospital_core.admissions")).scalar()
    print(f"  hospital_core.admissions    {n:>8} rows")
