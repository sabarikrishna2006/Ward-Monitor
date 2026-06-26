"""
One-time script: find the best DCM patient in MIMIC for the stakeholder replay demo.
Criteria:
  - ICD I42.x (ICD-10) or 425.x (ICD-9) as primary diagnosis
  - Has BNP data in ap_labevents
  - Has at least 12 hours of chartevents (enough for a 6-frame demo arc)
  - Peak-to-trough vital variability (suggests clinical deterioration + recovery arc)

Usage: python select_demo_patient.py
Output: prints the top 5 candidate hadm_ids with a clinical arc summary.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal
from sqlalchemy import text as sql_text

def main():
    db = SessionLocal()
    try:
        print("Searching for DCM patients with BNP data and vital variability...\n")

        # Find DCM patients in ap_diagnoses as primary diagnosis
        dcm_rows = db.execute(sql_text("""
            SELECT DISTINCT aa.hadm_id, aa.subject_id, aa.anchor_age, aa.gender, aa.admittime
            FROM ap_admissions aa
            JOIN ap_diagnoses ad ON aa.hadm_id = ad.hadm_id AND ad.seq_num = 1
            WHERE ad.icd_code LIKE 'I42%' OR ad.icd_code LIKE '425%'
            ORDER BY aa.admittime DESC
            LIMIT 200
        """)).fetchall()

        if not dcm_rows:
            print("No DCM patients found. Check that ap_admissions and ap_diagnoses tables are populated.")
            return

        print(f"Found {len(dcm_rows)} DCM admissions. Scoring for demo suitability...\n")

        candidates = []
        for hadm_id, subject_id, age, gender, admittime in dcm_rows:
            # BNP check
            bnp_row = db.execute(sql_text("""
                SELECT MAX(valuenum) FROM ap_labevents
                WHERE hadm_id = :h AND itemid IN (50963, 51921) AND valuenum IS NOT NULL
            """), {"h": hadm_id}).scalar()

            if not bnp_row:
                continue   # need BNP for NYHA

            # Vital span and variability
            vital_stats = db.execute(sql_text("""
                SELECT
                    COUNT(*) as n,
                    MIN(charttime) as t_start,
                    MAX(charttime) as t_end,
                    MIN(CASE WHEN itemid = 220179 THEN valuenum END) as sbp_min,
                    MAX(CASE WHEN itemid = 220179 THEN valuenum END) as sbp_max,
                    MIN(CASE WHEN itemid = 220277 THEN valuenum END) as spo2_min,
                    MAX(CASE WHEN itemid = 220045 THEN valuenum END) as hr_max,
                    MIN(CASE WHEN itemid = 220045 THEN valuenum END) as hr_min
                FROM ap_chartevents
                WHERE hadm_id = :h
                  AND itemid IN (220179, 220277, 220045, 220210)
            """), {"h": hadm_id}).fetchone()

            if not vital_stats or not vital_stats[1] or not vital_stats[2]:
                continue

            n, t_start, t_end, sbp_min, sbp_max, spo2_min, hr_max, hr_min = vital_stats
            span_hours = (t_end - t_start).total_seconds() / 3600
            if span_hours < 12:
                continue   # not enough temporal data for a 6-frame demo

            # Score: higher variability = more dramatic arc = better demo
            sbp_range = (sbp_max or 0) - (sbp_min or 0)
            hr_range = (hr_max or 0) - (hr_min or 0)
            spo2_dip = 100 - (spo2_min or 100)
            demo_score = sbp_range + hr_range * 0.5 + spo2_dip * 2 + (float(bnp_row) / 100)

            candidates.append({
                "hadm_id": hadm_id, "subject_id": subject_id, "age": int(age or 0),
                "gender": gender, "admittime": admittime,
                "bnp_max": round(float(bnp_row), 0),
                "span_hours": round(span_hours, 1),
                "vital_readings": n,
                "sbp_range": round(sbp_range or 0, 0),
                "hr_range": round(hr_range or 0, 0),
                "spo2_min": round(spo2_min or 100, 1),
                "demo_score": round(demo_score, 1),
            })

        if not candidates:
            print("No suitable candidates found (need BNP + 12h+ vitals + DCM diagnosis).")
            return

        # Sort by demo_score descending
        candidates.sort(key=lambda x: x["demo_score"], reverse=True)

        print("=" * 70)
        print(f"TOP {min(5, len(candidates))} REPLAY DEMO CANDIDATES")
        print("=" * 70)
        for i, c in enumerate(candidates[:5], 1):
            print(f"\n#{i}  hadm_id = {c['hadm_id']}  |  subject_id = {c['subject_id']}")
            print(f"    Age {c['age']}{c['gender']}  |  Admitted: {c['admittime']}")
            print(f"    BNP max: {c['bnp_max']} pg/mL  |  Span: {c['span_hours']}h  |  Readings: {c['vital_readings']}")
            print(f"    SBP range: {c['sbp_range']} mmHg  |  HR range: {c['hr_range']} bpm  |  SpO2 min: {c['spo2_min']}%")
            print(f"    Demo Score: {c['demo_score']}")

        best = candidates[0]
        print("\n" + "=" * 70)
        print(f"RECOMMENDED: hadm_id = {best['hadm_id']}")
        print(f"Run: POST /api/patients/{best['hadm_id']}/sync-mimic  to load this patient")
        print(f"Then: GET  /api/demo/replay/{best['hadm_id']}         to preview the arc")
        print("=" * 70)

    finally:
        db.close()


if __name__ == "__main__":
    main()
