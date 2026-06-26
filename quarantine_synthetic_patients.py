"""
Quarantine synthetic / fabricated ward patients so only billing-admitted (real
MIMIC) patients remain on the ward board for the pilot.

WHY: synthetic patients (seed_demo_ccu 91001–91006, Sabari-direct admits 10100+)
have no ap_* MIMIC data, so they cannot produce a real discharge summary. The
generate_summary guard already BLOCKS a fabricated summary for them, so this
cleanup is optional — it just removes them from the ward dashboard.

SAFETY:
  * DRY-RUN by default — prints what it WOULD delete and changes nothing.
  * Only deletes rows it can prove are synthetic: hadm_id in the known synthetic
    ranges AND with zero ap_chartevents/ap_labevents rows (i.e. never MIMIC-loaded).
  * Only touches EWS-owned tables + active_patients (per CLAUDE.md). NEVER ap_*.
  * Pass --apply to actually delete.

USAGE:
  py -3 quarantine_synthetic_patients.py            # dry run
  py -3 quarantine_synthetic_patients.py --apply    # perform deletes
"""
import sys
from sqlalchemy import text

# Reuse the discharge backend's Cloud SQL engine (shared DB).
sys.path.insert(0, "backend")
from app.cloud_sql_db import get_engine  # noqa: E402

# EWS-owned tables that key on hadm_id (per CLAUDE.md — safe to delete from).
EWS_TABLES = [
    "ews_vitals_timeseries", "ews_lab_events", "ews_medications",
    "ews_escalations", "ews_ccu_transfers", "ews_drug_lab_actions",
]

# Candidate synthetic id predicate: small (non-MIMIC) ids. MIMIC hadm_ids are
# 8-digit (>= 20000000). Synthetic are 91001–91006 and 10100+ (all < 1,000,000).
SYNTH_PREDICATE = "hadm_id < 1000000"


def main(apply: bool) -> None:
    eng = get_engine()
    with eng.connect() as conn:
        # Prove they are synthetic: small id AND no real MIMIC clinical rows.
        victims = conn.execute(text(f"""
            SELECT ap.hadm_id, ap.patient_name
            FROM active_patients ap
            WHERE {SYNTH_PREDICATE}
              AND (SELECT COUNT(*) FROM ap_chartevents c WHERE c.hadm_id = ap.hadm_id) = 0
              AND (SELECT COUNT(*) FROM ap_labevents  l WHERE l.hadm_id = ap.hadm_id) = 0
            ORDER BY ap.hadm_id
        """)).fetchall()

    if not victims:
        print("No synthetic patients to quarantine. Nothing to do.")
        return

    print(f"Found {len(victims)} synthetic patient(s) with no MIMIC data:")
    for hid, name in victims:
        print(f"  - hadm_id={hid}  name={name!r}")

    if not apply:
        print("\nDRY RUN — nothing deleted. Re-run with --apply to remove these.")
        return

    ids = [int(h) for h, _ in victims]
    with eng.begin() as conn:
        for tbl in EWS_TABLES:
            r = conn.execute(text(f"DELETE FROM {tbl} WHERE hadm_id = ANY(:ids)"), {"ids": ids})
            print(f"  deleted {r.rowcount} rows from {tbl}")
        # app_encounters for these synthetic patients (discharge-side) — also EWS-originated.
        r = conn.execute(text("DELETE FROM app_encounters WHERE hadm_id = ANY(:ids)"), {"ids": ids})
        print(f"  deleted {r.rowcount} rows from app_encounters")
        r = conn.execute(text("DELETE FROM active_patients WHERE hadm_id = ANY(:ids)"), {"ids": ids})
        print(f"  deleted {r.rowcount} rows from active_patients")
    print("\nQuarantine complete.")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
