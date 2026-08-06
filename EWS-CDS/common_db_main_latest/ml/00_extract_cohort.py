"""
Stage 00 — Extract the CCU / cardiac-ICU cohort and raw event tables from
MIMIC-IV v3.1 (BigQuery) into local parquet.

Pulls (all filtered to the cohort's stay_ids / hadm_ids):
  cohort.parquet          one row per CCU icu-stay + demographics + DCM flag
  chartevents.parquet     vitals (+ GCS, O2 flow, FiO2, rhythm)
  labevents.parquet       DCM/HF labs
  inputevents.parquet     vasopressor/inotrope starts   (escalation events)
  procedureevents.parquet ventilation + RRT starts       (escalation events)
  outputevents.parquet    urine output (fluid status)
  diagnoses.parquet       ICD codes (Charlson comorbidity index)

We extract the cohort FIRST, then pass explicit stay_id / hadm_id arrays to the
event queries — this guarantees every table references the SAME stays even under
--limit (a bare LIMIT in a subquery is non-deterministic across queries).

Usage:
    py -3 00_extract_cohort.py --limit 200      # smoke test: 200 stays
    py -3 00_extract_cohort.py                  # full cohort
    py -3 00_extract_cohort.py --dry-run        # print scan-byte estimates only
"""
from __future__ import annotations

import argparse
import logging
import time

from google.cloud import bigquery

import config
import bq

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("extract")


def _int_array(name: str, values):
    return bigquery.ArrayQueryParameter(name, "INT64", list(values))


def cohort_sql(limit: int) -> str:
    lim = f"\nLIMIT {limit}" if limit and limit > 0 else ""
    return f"""
    WITH cohort AS (
      SELECT ie.stay_id, ie.hadm_id, ie.subject_id, ie.first_careunit,
             ie.intime, ie.outtime,
             pa.anchor_age, pa.gender, pa.dod,
             adm.admittime, adm.dischtime, adm.deathtime, adm.hospital_expire_flag
      FROM {config.icu('icustays')} ie
      JOIN {config.hosp('patients')}  pa  ON ie.subject_id = pa.subject_id
      JOIN {config.hosp('admissions')} adm ON ie.hadm_id   = adm.hadm_id
      -- CCU (medical Coronary Care Unit) ONLY. CVICU is cardiac-SURGERY ICU:
      -- its escalations are post-op, not medical HF deterioration -> excluded.
      WHERE ( ie.first_careunit LIKE '%Coronary Care Unit%'
           OR ie.first_careunit LIKE '%CCU%' )
        AND ie.first_careunit NOT LIKE '%CVICU%'
        AND pa.anchor_age >= {config.MIN_AGE}
    )
    SELECT c.*,
      (SELECT COUNT(1) > 0 FROM {config.hosp('diagnoses_icd')} d
         WHERE d.hadm_id = c.hadm_id
           AND ((d.icd_version = 10 AND d.icd_code LIKE 'I420%')
             OR (d.icd_version = 9  AND d.icd_code LIKE '4254%'))) AS dcm_flag,
      (SELECT COUNT(1) > 0 FROM {config.hosp('diagnoses_icd')} d
         WHERE d.hadm_id = c.hadm_id
           AND ((d.icd_version = 10 AND d.icd_code LIKE 'I42%')
             OR (d.icd_version = 9  AND d.icd_code LIKE '425%'))) AS cardiomyopathy_flag
    FROM cohort c
    ORDER BY c.stay_id{lim}
    """


def estimate_bytes(sql: str, params=None) -> float:
    cfg = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False,
                                  query_parameters=params or [])
    job = bq.client().query(sql, job_config=cfg)
    gb = job.total_bytes_processed / 1e9
    return gb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="max stays (0 = all)")
    ap.add_argument("--dry-run", action="store_true", help="print scan estimates, don't download")
    args = ap.parse_args()

    # 1) Cohort ---------------------------------------------------------------
    csql = cohort_sql(args.limit)
    if args.dry_run:
        log.info("Cohort query ~%.2f GB", estimate_bytes(csql))
    t0 = time.time()
    cohort = bq.query_df(csql)
    log.info("cohort: %d stays (%d unique hadm, %d DCM) in %.1fs",
             len(cohort), cohort["hadm_id"].nunique(),
             int(cohort["dcm_flag"].sum()), time.time() - t0)
    if cohort.empty:
        log.error("Empty cohort — aborting.")
        return
    cohort.to_parquet(config.dpath("cohort.parquet"), index=False)

    stay_ids = cohort["stay_id"].dropna().astype(int).tolist()
    hadm_ids = cohort["hadm_id"].dropna().astype(int).unique().tolist()

    # 2) Event tables ---------------------------------------------------------
    pulls = [
        ("chartevents",
         f"SELECT stay_id, hadm_id, charttime, itemid, valuenum, value "
         f"FROM {config.icu('chartevents')} "
         f"WHERE stay_id IN UNNEST(@stay_ids) AND itemid IN UNNEST(@items)",
         [_int_array("stay_ids", stay_ids), _int_array("items", config.ALL_VITAL_ITEMIDS)]),

        ("labevents",
         f"SELECT hadm_id, charttime, itemid, valuenum "
         f"FROM {config.hosp('labevents')} "
         f"WHERE hadm_id IN UNNEST(@hadm_ids) AND itemid IN UNNEST(@items)",
         [_int_array("hadm_ids", hadm_ids), _int_array("items", config.ALL_LAB_ITEMIDS)]),

        ("inputevents",
         f"SELECT stay_id, hadm_id, starttime, itemid, rate, amount "
         f"FROM {config.icu('inputevents')} "
         f"WHERE stay_id IN UNNEST(@stay_ids) AND itemid IN UNNEST(@items)",
         [_int_array("stay_ids", stay_ids), _int_array("items", config.ESCALATION_INPUT_ITEMIDS)]),

        ("procedureevents",
         f"SELECT stay_id, hadm_id, starttime, itemid "
         f"FROM {config.icu('procedureevents')} "
         f"WHERE stay_id IN UNNEST(@stay_ids) AND itemid IN UNNEST(@items)",
         [_int_array("stay_ids", stay_ids), _int_array("items", config.ESCALATION_PROC_ITEMIDS)]),

        ("outputevents",
         f"SELECT stay_id, hadm_id, charttime, itemid, value "
         f"FROM {config.icu('outputevents')} "
         f"WHERE stay_id IN UNNEST(@stay_ids) AND itemid IN UNNEST(@items)",
         [_int_array("stay_ids", stay_ids), _int_array("items", config.URINE_ITEMIDS)]),

        ("diagnoses",
         f"SELECT hadm_id, icd_code, icd_version, seq_num "
         f"FROM {config.hosp('diagnoses_icd')} "
         f"WHERE hadm_id IN UNNEST(@hadm_ids)",
         [_int_array("hadm_ids", hadm_ids)]),
    ]

    total_gb = 0.0
    for name, sql, params in pulls:
        if args.dry_run:
            gb = estimate_bytes(sql, params)
            total_gb += gb
            log.info("%-16s ~%.2f GB", name, gb)
            continue
        t0 = time.time()
        df = bq.query_df(sql, params)
        df.to_parquet(config.dpath(f"{name}.parquet"), index=False)
        log.info("%-16s %8d rows -> %s.parquet (%.1fs)", name, len(df), name, time.time() - t0)

    if args.dry_run:
        log.info("TOTAL estimated scan: ~%.2f GB", total_gb + estimate_bytes(csql))


if __name__ == "__main__":
    main()
