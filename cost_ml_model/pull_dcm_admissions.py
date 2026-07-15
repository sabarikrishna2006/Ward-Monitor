"""
Task 1 + Task 2 — Pull static per-admission data for the FULL DCM cohort from
BigQuery (MIMIC-IV), plus day-by-day ICU/Ward location tagging.

Cohort definition: ICD-10 I420 or ICD-9 4254 (Dilated Cardiomyopathy) AND has at
least one ICU stay — the stricter, more clinically defensible definition already
used by backend/app/bq_mimic_loader.get_top_dcm_patients(), just without its
LIMIT (we want every DCM+ICU admission, not a top-N richness-ranked sample).

Output:
  cost_ml_model/data/dcm_admissions_static.csv   — one row per hadm_id
  cost_ml_model/data/dcm_daily_location.csv      — one row per (hadm_id, hospital_day),
                                                    tagged ICU or Ward that day
"""
import os
import sys
import pandas as pd

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "backend"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.bq_mimic_loader import _query, _hosp, _icu  # noqa: E402
# NOTE: elixhauser.py (manual, unvalidated ICD regex mapping) is deliberately
# NOT used — no elixhauser_score in this version. BigQuery's official derived
# dataset (physionet-data.mimiciv_3_1_derived) has a validated `charlson`
# comorbidity table but no Elixhauser table; rather than ship an unvalidated
# manual mapping, we're leaving comorbidity scoring out until an official
# Elixhauser source is wired in.

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(OUT_DIR, exist_ok=True)


def get_dcm_cohort_hadm_ids():
    """Every DCM (ICD I420/4254) admission — ALL DCM-diagnosed patients, not just
    the ones who needed an ICU stay (Ashmit's correction: use the full cohort,
    matching the size of the original 7,077-admission dataset, not the stricter
    ICU-only subset)."""
    rows = _query(f"""
        SELECT DISTINCT a.hadm_id, a.subject_id
        FROM {_hosp('admissions')} a
        JOIN {_hosp('diagnoses_icd')} d ON a.hadm_id = d.hadm_id
        WHERE d.icd_code IN ('I420', '4254')
    """)
    return rows


def pull_admissions_and_demographics(hadm_ids):
    id_list = ",".join(str(h) for h in hadm_ids)
    rows = _query(f"""
        SELECT
            a.hadm_id, a.subject_id, a.admittime, a.dischtime,
            a.admission_type, a.insurance,
            p.gender, p.anchor_age, p.anchor_year
        FROM {_hosp('admissions')} a
        JOIN {_hosp('patients')} p ON a.subject_id = p.subject_id
        WHERE a.hadm_id IN ({id_list})
    """)
    df = pd.DataFrame(rows)
    df["admittime"] = pd.to_datetime(df["admittime"])
    df["dischtime"] = pd.to_datetime(df["dischtime"])
    # A handful of admissions have dischtime a few hours *before* admittime on the
    # same calendar day (MIMIC data quirk, not a real negative stay) — .dt.days
    # truncates toward -inf so e.g. -40min becomes -1. Floor at 0 (same-day stay).
    df["los_days_total"] = (df["dischtime"] - df["admittime"]).dt.days.clip(lower=0)
    df["age_at_admission"] = df["anchor_age"] + (df["admittime"].dt.year - df["anchor_year"])
    return df.drop(columns=["anchor_age", "anchor_year"])


def pull_primary_diagnosis(hadm_ids):
    """A handful of MIMIC admissions have seq_num=1 recorded under BOTH
    icd_version 9 and 10 (dual-coded) — that would otherwise produce 2 rows
    for 1 admission. Dedupe deterministically: prefer ICD-10 (more current),
    else whatever's there."""
    id_list = ",".join(str(h) for h in hadm_ids)
    rows = _query(f"""
        SELECT di.hadm_id, di.icd_code, di.icd_version,
               COALESCE(dd.long_title, di.icd_code) AS primary_diagnosis
        FROM {_hosp('diagnoses_icd')} di
        LEFT JOIN {_hosp('d_icd_diagnoses')} dd
               ON di.icd_code = dd.icd_code AND di.icd_version = dd.icd_version
        WHERE di.hadm_id IN ({id_list}) AND di.seq_num = 1
    """)
    df = pd.DataFrame(rows)
    df = df.sort_values("icd_version", ascending=False).drop_duplicates(subset="hadm_id", keep="first")
    return df[["hadm_id", "primary_diagnosis"]]


def pull_treating_specialty(hadm_ids):
    id_list = ",".join(str(h) for h in hadm_ids)
    rows = _query(f"""
        SELECT hadm_id, curr_service AS treating_specialty
        FROM (
            SELECT hadm_id, curr_service,
                   ROW_NUMBER() OVER (PARTITION BY hadm_id ORDER BY transfertime ASC) AS rn
            FROM {_hosp('services')}
            WHERE hadm_id IN ({id_list})
        )
        WHERE rn = 1
    """)
    return pd.DataFrame(rows)


def pull_icu_flag(hadm_ids):
    id_list = ",".join(str(h) for h in hadm_ids)
    rows = _query(f"""
        SELECT DISTINCT hadm_id
        FROM {_icu('icustays')}
        WHERE hadm_id IN ({id_list})
    """)
    icu_ids = {r["hadm_id"] for r in rows}
    return icu_ids


def pull_daily_location(hadm_ids, los_lookup):
    """For each admission, tag every calendar day (0..los_days_total) as ICU or
    Ward, based on the transfers table. Rule: any ICU time that day counts the
    whole day as an ICU day (simplest, defensible default — see plan)."""
    id_list = ",".join(str(h) for h in hadm_ids)
    rows = _query(f"""
        SELECT hadm_id, careunit, intime, outtime
        FROM {_hosp('transfers')}
        WHERE hadm_id IN ({id_list}) AND intime IS NOT NULL
    """)
    tdf = pd.DataFrame(rows)
    tdf["intime"] = pd.to_datetime(tdf["intime"])
    tdf["outtime"] = pd.to_datetime(tdf["outtime"]).fillna(tdf["intime"])
    tdf["is_icu"] = tdf["careunit"].str.contains("ICU", case=False, na=False)

    out_rows = []
    for hadm_id, grp in tdf.groupby("hadm_id"):
        admit_date = grp["intime"].min().normalize()
        los = los_lookup.get(hadm_id, 0)
        icu_days = set()
        for _, r in grp[grp["is_icu"]].iterrows():
            start_day = (r["intime"].normalize() - admit_date).days
            end_day = (r["outtime"].normalize() - admit_date).days
            icu_days.update(range(max(start_day, 0), max(end_day, start_day) + 1))
        for day in range(0, los + 1):
            out_rows.append({
                "hadm_id": hadm_id, "hospital_day": day,
                "was_in_icu_today": 1 if day in icu_days else 0,
            })
    return pd.DataFrame(out_rows)


def main():
    print("Pulling DCM (I420/4254) + ICU-stay cohort from BigQuery...")
    cohort = get_dcm_cohort_hadm_ids()
    hadm_ids = [r["hadm_id"] for r in cohort]
    print(f"  cohort size: {len(hadm_ids)} admissions")

    print("Pulling admissions + demographics...")
    adm = pull_admissions_and_demographics(hadm_ids)

    print("Pulling primary diagnosis...")
    diag = pull_primary_diagnosis(hadm_ids)

    print("Pulling treating specialty...")
    spec = pull_treating_specialty(hadm_ids)

    print("Pulling ICU flag...")
    icu_ids = pull_icu_flag(hadm_ids)

    static = (adm.merge(diag, on="hadm_id", how="left")
                 .merge(spec, on="hadm_id", how="left"))
    static["icu_flag"] = static["hadm_id"].isin(icu_ids).astype(int)
    static["treating_specialty"] = static["treating_specialty"].fillna("Unknown")
    static["primary_diagnosis"] = static["primary_diagnosis"].fillna("Unknown")
    static["insurance"] = static["insurance"].fillna("Unknown")

    out_static = os.path.join(OUT_DIR, "dcm_admissions_static.csv")
    static.to_csv(out_static, index=False)
    print(f"Saved {len(static)} rows -> {out_static}")

    print("\nPulling day-by-day ICU/Ward location (Task 2)...")
    los_lookup = dict(zip(static["hadm_id"], static["los_days_total"]))
    daily_loc = pull_daily_location(hadm_ids, los_lookup)
    out_daily = os.path.join(OUT_DIR, "dcm_daily_location.csv")
    daily_loc.to_csv(out_daily, index=False)
    print(f"Saved {len(daily_loc)} rows -> {out_daily}")

    print("\n--- Sanity check ---")
    print("Admissions:", len(static))
    print("Mean LOS (days):", static["los_days_total"].mean().round(1))
    print("ICU flag rate:", static["icu_flag"].mean().round(2))
    print("Gender counts:\n", static["gender"].value_counts())


if __name__ == "__main__":
    main()
