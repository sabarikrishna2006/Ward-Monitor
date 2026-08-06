"""
Live Bill "everyone shows Day 0" fix (one-off demo data repair).

hospital_day (see _hospital_day() in backend/app/main.py) is computed as
NOW() - active_patients.estimate_generated_at, clamped to [0, los_days].
Every patient currently in the Admission phase got estimate_generated_at
stamped to the moment they were admitted through the ward UI -- and since
that all happened today during testing, every one of them shows Day 0 on
the billing dashboard's Live Bill screen, which looks wrong for a demo.

This backdates estimate_generated_at per-patient to the midpoint of their
own MIMIC length-of-stay (los_days // 2), so the ML cost model predicts
from partway through each patient's stay instead of uniformly Day 0 --
patients with a longer LOS end up further along, shorter-LOS patients less
so, matching their own individual case.

Run from repo root (needs CLOUD_SQL_PASS exported, same as deploy.sh):
    python backfill_hospital_day_midpoint.py           # dry run (prints only)
    python backfill_hospital_day_midpoint.py --apply    # writes the changes
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from app.cloud_sql_db import get_engine
from sqlalchemy import text

APPLY = "--apply" in sys.argv

engine = get_engine()

with engine.begin() as conn:
    # Same "Admission phase" set the billing dashboard's Live Bill list shows
    # (see billing_dashboard() in main.py) -- active patients with either a
    # cost estimate already saved, or an encounter still pre-signoff.
    rows = conn.execute(text("""
        SELECT ap.hadm_id, ap.los_days, ap.estimate_generated_at
        FROM active_patients ap
        LEFT JOIN app_encounters ae ON ae.hadm_id = ap.hadm_id
        LEFT JOIN billing_records br ON br.hadm_id = ap.hadm_id
        WHERE ap.estimate_generated_at IS NOT NULL
          AND (
            (ae.id IS NULL AND br.id IS NOT NULL
             AND COALESCE(br.billing_phase, '') NOT IN ('paid', 'claim_submitted', 'tpa_settled'))
            OR ae.status IN (
                'Pending Ingestion','Processing','Files Ready',
                'Ready for Review','Awaiting Review',
                'Awaiting Confirmation','Verifying Claims','Revision Requested'
            )
          )
        ORDER BY ap.hadm_id
    """)).fetchall()

    print(f"{'hadm_id':<10} {'los_days':<10} {'-> hospital_day (midpoint)'}")
    updates = []
    for hadm_id, los_days, est_gen in rows:
        los = int(los_days) if los_days else 4  # reasonable default for patients with no MIMIC LOS on file
        mid = max(1, los // 2)
        updates.append((hadm_id, mid))
        print(f"{hadm_id:<10} {los_days!s:<10} Day {mid}")

    print(f"\n{len(updates)} patient(s) {'updated' if APPLY else 'would be updated'} (dry run: pass --apply to write).")

    if APPLY:
        for hadm_id, mid in updates:
            conn.execute(text("""
                UPDATE active_patients
                SET estimate_generated_at = NOW() - (:mid || ' days')::interval
                WHERE hadm_id = :h
            """), {"h": hadm_id, "mid": mid})
        print("Done. Refresh the billing dashboard's Live Bill tab to see staggered Day N values.")
