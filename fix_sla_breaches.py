"""
Ward-admin SLA breach demo reset. Run from repo root on the server (needs
CLOUD_SQL_PASS exported, same as deploy.sh): python fix_sla_breaches.py

1. Clears every currently-breaching "Awaiting Review" encounter by bumping
   its updated_at to now (ward-admin.html flags anything >4h old).
2. Backdates ONE specific encounter's updated_at by 5 hours so it becomes
   the sole SLA breach -- for demoing the Follow Up / breach toast flow.
   Edit TARGET_HADM_ID below to whichever patient you want to use.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from app.cloud_sql_db import get_engine
from sqlalchemy import text

# The one patient that should show the SLA breach after this runs.
TARGET_HADM_ID = 20003014

engine = get_engine()

with engine.begin() as conn:
    cleared = conn.execute(text("""
        UPDATE app_encounters
        SET updated_at = NOW()
        WHERE status = 'Awaiting Review'
          AND hadm_id != :target
          AND updated_at < NOW() - INTERVAL '4 hours'
        RETURNING hadm_id
    """), {"target": TARGET_HADM_ID}).fetchall()
    print(f"Cleared {len(cleared)} stale SLA breach(es): {[r[0] for r in cleared]}")

    backdated = conn.execute(text("""
        UPDATE app_encounters
        SET updated_at = NOW() - INTERVAL '5 hours'
        WHERE hadm_id = :target AND status = 'Awaiting Review'
        RETURNING hadm_id
    """), {"target": TARGET_HADM_ID}).fetchall()
    if backdated:
        print(f"Backdated hadm_id {TARGET_HADM_ID} by 5h -- it will now show as the SLA breach.")
    else:
        print(f"hadm_id {TARGET_HADM_ID} is not currently 'Awaiting Review' -- nothing backdated. "
              f"Edit TARGET_HADM_ID at the top of this script to the patient you want to use.")

print("\nDone. Refresh the ward-admin Summary Pipeline page to see the change.")
