"""
Read-only preview of what /api/cmo/metrics' Section-wise Accuracy table will
show once the gap_rows-based fix (backend/app/main.py get_cmo_metrics) is
deployed -- lets you see the real numbers now, without waiting on a redeploy.

Run from repo root (needs CLOUD_SQL_PASS exported, same as deploy.sh):
    python preview_cmo_sections.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from app.cloud_sql_db import get_engine
from sqlalchemy import text

_PASS3_SECTION_LABELS = {
    "s1": "Patient Demographics", "s2": "Chief Complaint", "s3": "History of Presenting Illness",
    "s4": "Significant Past History", "s5": "Examination Findings on Admission",
    "s6": "Laboratory Investigations", "s7": "Imaging & Procedure Findings",
    "s8": "Working Diagnosis at Admission", "s9": "Hospital Course", "s10": "Procedures Performed",
    "s11": "Discharge Medications", "s12": "Follow-up & Discharge Advice",
    "s13": "Discharge Diagnosis", "s14": "Condition at Discharge", "s15": "Patient Acknowledgement",
}

engine = get_engine()
with engine.connect() as conn:
    total_summaries = conn.execute(text(
        "SELECT COUNT(*) FROM app_summaries s JOIN app_encounters e ON e.id = s.encounter_id"
    )).scalar()
    denom = max(total_summaries, 1)

    rows = conn.execute(text("""
        SELECT
            gr->>'sec' AS nabh_section,
            COUNT(*) FILTER (WHERE gr->>'tier' = 'T1') AS t1,
            COUNT(*) FILTER (WHERE gr->>'tier' = 'T2') AS t2,
            COUNT(*) FILTER (WHERE gr->>'tier' = 'T3') AS t3
        FROM app_summaries s
        JOIN app_encounters e ON e.id = s.encounter_id
        CROSS JOIN LATERAL jsonb_array_elements(COALESCE(s.gap_rows, '[]'::jsonb)) AS gr
        WHERE gr->>'sec' IS NOT NULL
        GROUP BY gr->>'sec'
    """)).fetchall()
    counts = {sec: (t1, t2, t3) for sec, t1, t2, t3 in rows}

print(f"total_summaries (denominator): {total_summaries}\n")
print(f"{'SECTION':<32} {'ACCURACY':<10} {'T1':<8} {'T2':<8} {'T3'}")
for sec, label in _PASS3_SECTION_LABELS.items():
    t1, t2, t3 = counts.get(sec, (0, 0, 0))
    t1r = round(t1 / denom * 100, 1)
    t2r = round(t2 / denom * 100, 1)
    t3r = round(t3 / denom * 100, 1)
    acc = round(max(0.0, 100 - t1r - t2r - t3r), 1)
    print(f"{label:<32} {acc:<10} {t1r:<8} {t2r:<8} {t3r}")
