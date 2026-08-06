"""
Read-only diagnostic for the CMO dashboard's "Section-wise Accuracy" numbers
looking inflated (see billing_dashboard T1/T2/T3 rate calc in main.py ~5981).

Checks whether error_log has accumulated stale rows from regenerated/
re-edited summary_versions that no longer match each encounter's CURRENT
summary -- which would inflate the T1/T2/T3 rate % without the denominator
(total_summaries) growing to match.

Run from repo root (needs CLOUD_SQL_PASS exported, same as deploy.sh):
    python diagnose_accuracy_calc.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from app.cloud_sql_db import get_engine
from sqlalchemy import text

engine = get_engine()

with engine.connect() as conn:
    total_summaries = conn.execute(text("""
        SELECT COUNT(*) FROM app_summaries s JOIN app_encounters e ON e.id = s.encounter_id
    """)).scalar()
    print(f"total_summaries (denominator used for every section's rate): {total_summaries}\n")

    total_errors = conn.execute(text("SELECT COUNT(*) FROM error_log")).scalar()
    print(f"total error_log rows (all time): {total_errors}")

    # Errors whose summary_version doesn't match the encounter's CURRENT summary_version
    # -- these are "stale": logged against a summary that's since been superseded/regenerated.
    stale = conn.execute(text("""
        SELECT COUNT(*)
        FROM error_log el
        JOIN app_encounters e ON e.hadm_id = CAST(el.hadm_id AS INTEGER)
        JOIN app_summaries s  ON s.encounter_id = e.id
        WHERE el.summary_version IS NOT NULL
          AND s.summary_version IS NOT NULL
          AND el.summary_version != CAST(s.summary_version AS TEXT)
    """)).scalar()
    print(f"error_log rows logged against a SUPERSEDED summary_version (stale): {stale}\n")

    print(f"{'nabh_section':<28} {'t1':<5} {'t2':<5} {'t3':<5} {'stale_t1':<9} {'stale_t2':<9} {'stale_t3'}")
    rows = conn.execute(text("""
        SELECT
            el.nabh_section,
            COUNT(*) FILTER (WHERE el.error_tier = 1) AS t1,
            COUNT(*) FILTER (WHERE el.error_tier = 2) AS t2,
            COUNT(*) FILTER (WHERE el.error_tier = 3) AS t3,
            COUNT(*) FILTER (WHERE el.error_tier = 1 AND el.summary_version IS NOT NULL
                              AND s.summary_version IS NOT NULL
                              AND el.summary_version != CAST(s.summary_version AS TEXT)) AS stale_t1,
            COUNT(*) FILTER (WHERE el.error_tier = 2 AND el.summary_version IS NOT NULL
                              AND s.summary_version IS NOT NULL
                              AND el.summary_version != CAST(s.summary_version AS TEXT)) AS stale_t2,
            COUNT(*) FILTER (WHERE el.error_tier = 3 AND el.summary_version IS NOT NULL
                              AND s.summary_version IS NOT NULL
                              AND el.summary_version != CAST(s.summary_version AS TEXT)) AS stale_t3
        FROM error_log el
        LEFT JOIN app_encounters e ON e.hadm_id = CAST(el.hadm_id AS INTEGER)
        LEFT JOIN app_summaries s  ON s.encounter_id = e.id
        WHERE el.nabh_section IS NOT NULL
        GROUP BY el.nabh_section
        ORDER BY el.nabh_section
    """)).fetchall()
    for r in rows:
        print(f"{r[0]:<28} {r[1]:<5} {r[2]:<5} {r[3]:<5} {r[4]:<9} {r[5]:<9} {r[6]}")

    print("\nIf 'stale_*' columns are a large share of t1/t2/t3, the fix is to exclude")
    print("stale summary_versions from the rate calc (or delete/archive those rows).")
