"""
Stage 00c — Re-extract the FEATURE substrate that the original pull left out.

WHY. `00_extract_cohort.py` filtered chartevents to `ALL_VITAL_ITEMIDS` (the seven
NEWS2 parameters plus GCS-total/O2-flow/FiO2/rhythm) and labevents to ten labs.
Every feature in this project therefore descends from a set chosen to *compute
NEWS2*. That is fine for a NEWS2 target and wrong for an escalation target — and,
critically, **a filtered extract makes its own feature set look complete**: you
cannot discover the omission by inspecting the parquet files, only by querying
d_items.

Coverage figures in config were MEASURED on this exact 10,775-stay CCU cohort.
Headline gaps closed here:
  * 220181 NIBP mean (MAP) — 98.3%, 56 rows/stay. Better covered than the SBP/DBP
    we do extract. MAP is the primary shock variable and it was being APPROXIMATED
    as (SBP + 2*DBP)/3 with the measured value sitting unused.
  * Flowsheet labs at >=95.8% with ~6 readings/stay — including HCO3 and ANION GAP,
    which are entirely new and are direct metabolic-acidosis markers. The previous
    "labs add nothing" result was obtained from labevents, where lactate is 45%
    missing and neither HCO3 nor anion gap exists at all.
  * GCS components at 99.1% (only the total was held; motor response is the most
    prognostic component).
  * "Nurse worry" signals at ~99% — the alarm limits a nurse SETS and how often
    they check parameters encode concern no vital VALUE carries. The JAMIA 2024
    review of 14 deployed systems lists a purpose-built "nurse worry factor" among
    the features that helped.

EXCLUDED ON PURPOSE — ventilator settings (PEEP, tidal volume). They exist only
after intubation, and intubation IS an event in the escalation target, so they leak
the outcome. Their ~27% coverage is exactly the ventilated fraction, which is the
tell. `config.LEAKY_POST_ESCALATION_ITEMIDS` records them so the exclusion is
explicit rather than an oversight.

Writes NEW files; never touches the existing parquets.
  data/chartevents_ext.parquet   stay_id, hadm_id, charttime, itemid, valuenum
  data/labevents_ext.parquet     hadm_id, charttime, itemid, valuenum

Run: PYTHONUTF8=1 py -3 00c_extract_features_ext.py
"""
from __future__ import annotations

import logging

import pandas as pd
from google.cloud import bigquery

import bq
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("extract_feat_ext")

GROUP_OF: dict[int, str] = {}
for name, d in (("hemo", config.HEMO_ITEMIDS), ("flowsheet_lab", config.FLOWSHEET_LAB_ITEMIDS),
                ("neuro", config.NEURO_ITEMIDS), ("nurse_concern", config.NURSE_CONCERN_ITEMIDS),
                ("frailty", config.FRAILTY_ITEMIDS),
                ("invasive_monitor", config.INVASIVE_MONITOR_ITEMIDS)):
    for i in d:
        GROUP_OF[i] = name
GROUP_OF[226531] = "weight"

LABEL_OF: dict[int, str] = {}
for d in (config.HEMO_ITEMIDS, config.FLOWSHEET_LAB_ITEMIDS, config.NEURO_ITEMIDS,
          config.NURSE_CONCERN_ITEMIDS, config.FRAILTY_ITEMIDS,
          config.INVASIVE_MONITOR_ITEMIDS):
    LABEL_OF.update(d)
LABEL_OF[226531] = "Admission Weight (lbs.)"


def main():
    co = pd.read_parquet(config.dpath("cohort.parquet"))
    stay_ids = [int(x) for x in co["stay_id"].unique()]
    hadm_ids = [int(x) for x in co["hadm_id"].unique()]
    N, NH = len(stay_ids), len(hadm_ids)
    log.info("CCU cohort: %d stays / %d admissions", N, NH)

    # ---- chartevents ----------------------------------------------------------
    items = [int(i) for i in config.EXTRA_CHART_ITEMIDS]
    leaky = set(int(i) for i in config.LEAKY_POST_ESCALATION_ITEMIDS)
    assert not (set(items) & leaky), \
        "post-escalation ventilator settings must never enter the feature extract"
    log.info("querying chartevents for %d itemids (ventilator settings excluded)…", len(items))
    ce = bq.query_df(
        f"SELECT stay_id, hadm_id, charttime, itemid, valuenum "
        f"FROM {config.icu('chartevents')} "
        f"WHERE stay_id IN UNNEST(@ids) AND itemid IN UNNEST(@items) AND valuenum IS NOT NULL",
        [bigquery.ArrayQueryParameter("ids", "INT64", stay_ids),
         bigquery.ArrayQueryParameter("items", "INT64", items)])
    ce["charttime"] = pd.to_datetime(ce["charttime"])
    ce.to_parquet(config.dpath("chartevents_ext.parquet"), index=False)
    log.info("chartevents_ext: %d rows, %d stays", len(ce), ce["stay_id"].nunique())

    # ---- labevents ------------------------------------------------------------
    litems = [int(i) for i in config.EXTRA_LAB_ITEMIDS]
    log.info("querying labevents for %d itemids…", len(litems))
    le = bq.query_df(
        f"SELECT hadm_id, charttime, itemid, valuenum "
        f"FROM {config.hosp('labevents')} "
        f"WHERE hadm_id IN UNNEST(@h) AND itemid IN UNNEST(@items) AND valuenum IS NOT NULL",
        [bigquery.ArrayQueryParameter("h", "INT64", hadm_ids),
         bigquery.ArrayQueryParameter("items", "INT64", litems)])
    le["charttime"] = pd.to_datetime(le["charttime"])
    le.to_parquet(config.dpath("labevents_ext.parquet"), index=False)
    log.info("labevents_ext: %d rows, %d admissions", len(le), le["hadm_id"].nunique())

    # ---- coverage report: verify the measured numbers, don't trust the comments --
    print("\n" + "=" * 96)
    print(f"EXPANDED FEATURE EXTRACT — coverage on {N:,} CCU stays / {NH:,} admissions")
    print("=" * 96)
    g = (ce.groupby("itemid").agg(n_stays=("stay_id", "nunique"), n_rows=("valuenum", "size"))
           .reset_index())
    g["group"] = g["itemid"].map(GROUP_OF)
    g["label"] = g["itemid"].map(LABEL_OF)
    g["pct"] = g["n_stays"] / N
    g["rows_per_stay"] = g["n_rows"] / g["n_stays"]
    for grp in ["hemo", "flowsheet_lab", "neuro", "nurse_concern", "frailty",
                "invasive_monitor", "weight"]:
        s = g[g.group == grp].sort_values("n_stays", ascending=False)
        if s.empty:
            continue
        print(f"\n  {grp.upper()}")
        print(f"    {'itemid':>7} {'label':34} {'stays':>7} {'coverage':>9} {'rows/stay':>10}")
        for r in s.itertuples():
            print(f"    {r.itemid:>7} {str(r.label)[:34]:34} {r.n_stays:>7,} "
                  f"{r.pct:>9.1%} {r.rows_per_stay:>10.1f}")
    print("\n  LABEVENTS (per-admission coverage)")
    gl = (le.groupby("itemid").agg(n_hadm=("hadm_id", "nunique"), n_rows=("valuenum", "size"))
            .reset_index())
    gl["label"] = gl["itemid"].map(config.EXTRA_LAB_ITEMIDS)
    print(f"    {'itemid':>7} {'label':34} {'adms':>7} {'coverage':>9} {'rows/adm':>10}")
    for r in gl.sort_values("n_hadm", ascending=False).itertuples():
        print(f"    {r.itemid:>7} {str(r.label)[:34]:34} {r.n_hadm:>7,} "
              f"{r.n_hadm/NH:>9.1%} {r.n_rows/r.n_hadm:>10.1f}")
    print(f"\n  EXCLUDED as post-escalation leakage: "
          f"{sorted(config.LEAKY_POST_ESCALATION_ITEMIDS)}")
    print("=" * 96 + "\n")


if __name__ == "__main__":
    main()
