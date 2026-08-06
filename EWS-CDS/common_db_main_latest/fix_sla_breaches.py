"""
Ward-admin SLA breach demo reset. Run from repo root on the server (needs
CLOUD_SQL_PASS exported, same as deploy.sh): python fix_sla_breaches.py

1. Clears every currently-breaching encounter (matches on hadm_id directly,
   not status -- the breach banner covers both 'Ready for Review' and
   'Awaiting Review', so filtering by a single status silently misses some).
2. Backdates ONE specific encounter's updated_at by 5 hours so it becomes
   the sole SLA breach -- for demoing the Follow Up / breach toast flow.
   Edit TARGET_HADM_ID / CLEAR_HADM_IDS below as needed.

CAUTION #1: a DB trigger (trg_encounters_updated_at -> set_updated_at()) forces
updated_at = NOW() on every UPDATE to app_encounters, unconditionally -- a plain
"SET updated_at = NOW() - INTERVAL '5 hours'" gets silently overwritten back to
now() by the trigger before the row is even written. This script disables the
trigger for the single backdating statement, then re-enables it immediately,
all inside one transaction.

CAUTION #2: opening this encounter's detail (review screen, etc.) after this
runs touches `last_accessed_at`, which -- via the shared update_encounter()
helper in cloud_sql_app_db.py -- goes through a normal UPDATE and so (trigger
back on) resets `updated_at` to now again, silently un-breaching it (see
main.py's get_encounter_by_hadm_id). Run this LAST, right before demoing, and
don't open the target patient's case before then.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from app.cloud_sql_db import get_engine
from sqlalchemy import text

# The one patient that should show the SLA breach after this runs.
TARGET_HADM_ID = 20026625

# Every other patient currently shown as a stale SLA breach that should clear.
CLEAR_HADM_IDS = [20001395, 20003174, 20000094]

engine = get_engine()

with engine.begin() as conn:
    cleared = conn.execute(text("""
        UPDATE app_encounters
        SET updated_at = NOW()
        WHERE hadm_id = ANY(:ids)
        RETURNING hadm_id
    """), {"ids": CLEAR_HADM_IDS}).fetchall()
    print(f"Cleared {len(cleared)} stale SLA breach(es): {[r[0] for r in cleared]}")

    # The BEFORE UPDATE trigger forces updated_at = NOW() on every write, so it
    # must be disabled for this one statement or the backdate is a silent no-op.
    conn.execute(text("ALTER TABLE app_encounters DISABLE TRIGGER trg_encounters_updated_at"))
    backdated = conn.execute(text("""
        UPDATE app_encounters
        SET updated_at = NOW() - INTERVAL '5 hours'
        WHERE hadm_id = :target
        RETURNING hadm_id
    """), {"target": TARGET_HADM_ID}).fetchall()
    conn.execute(text("ALTER TABLE app_encounters ENABLE TRIGGER trg_encounters_updated_at"))
    if backdated:
        print(f"Backdated hadm_id {TARGET_HADM_ID} by 5h -- it will now show as the SLA breach.")
    else:
        print(f"hadm_id {TARGET_HADM_ID} not found -- nothing backdated. "
              f"Edit TARGET_HADM_ID at the top of this script to the patient you want to use.")

print("\nDone. Refresh the ward-admin Summary Pipeline page to see the change.")
print("Reminder: do NOT open the target patient's case/review screen before demoing --")
print("viewing it resets the breach clock (last_accessed_at side effect).")
