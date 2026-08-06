"""
Clears error_log -- the table backing the CMO dashboard's "Section-wise
Accuracy" / T1-T2-T3 rate numbers (see diagnose_accuracy_calc.py's findings:
51 rows logged against only 13 real current summaries, 25 of them with no
nabh_section at all -- almost certainly leftover clicks from testing the
Reject/Edit-correction flows while building those features, not genuine
attending corrections from real pilot review).

This does NOT touch app_summaries, app_encounters, or anything else -- only
error_log, which is purely a log table the CMO dashboard aggregates. Clearing
it resets Section-wise Accuracy to 100%/no-data going forward; it starts
filling again only from real "Flag Error" / "Edit & correct" / "Reject"
actions attendings take from now on.

Run from repo root (needs CLOUD_SQL_PASS exported, same as deploy.sh):
    python clear_error_log.py           # dry run (prints count only)
    python clear_error_log.py --apply    # actually deletes
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from app.cloud_sql_db import get_engine
from sqlalchemy import text

APPLY = "--apply" in sys.argv

engine = get_engine()

with engine.begin() as conn:
    count = conn.execute(text("SELECT COUNT(*) FROM error_log")).scalar()
    print(f"error_log currently has {count} row(s).")

    if not APPLY:
        print("\nDry run -- nothing deleted. Pass --apply to actually clear the table.")
    else:
        deleted = conn.execute(text("DELETE FROM error_log")).rowcount
        print(f"Deleted {deleted} row(s) from error_log.")
        print("CMO dashboard's Section-wise Accuracy will show no data / 100% until new errors are logged from real review activity.")
