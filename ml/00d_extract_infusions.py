"""
Stage 00d — Extract continuous-infusion events for the infusion-dynamics features.

WHY. `data/inputevents.parquet` was filtered to `ESCALATION_INPUT_ITEMIDS`
(vasopressors only), so the non-vasopressor drips a CCU actually titrates are absent.
Changes to those drips precede acute escalation: nitroglycerin weaned as pressure
falls, furosemide escalated for congestion, fluid rate raised for hypotension.

WHY THIS IS AN ALLOW-LIST AND NOT A GENERIC FLAG. A feature like
`on_continuous_iv_infusion` leaks the escalation target three separate ways:

  (a) vasopressors ARE the target. A generic infusion flag includes norepinephrine,
      so the feature would carry the label.
  (b) propofol / fentanyl / midazolam are induction and sedation agents given AT
      intubation -- and intubation is an event -- so their start time is essentially
      concurrent with the outcome.
  (c) packed red blood cells is arguably an escalation in its own right.

The exclusions are ASSERTED below, not merely intended, so the leak cannot be
reintroduced by someone widening the list later.

Output: data/infusions_ext.parquet
    stay_id, hadm_id, starttime, endtime, itemid, rate, amount, label

Run: PYTHONUTF8=1 py -3 00d_extract_infusions.py
"""
from __future__ import annotations

import logging

import pandas as pd
from google.cloud import bigquery

import bq
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("extract_infusions")


def main():
    allowed = sorted(int(i) for i in config.INFUSION_ALLOWED_ITEMIDS)
    forbidden = set(int(i) for i in config.INFUSION_FORBIDDEN_ITEMIDS)

    # --- the assertions that make this safe -----------------------------------
    overlap = set(allowed) & forbidden
    assert not overlap, f"allow-list contains forbidden itemids: {sorted(overlap)}"
    vaso = set(int(i) for i in config.VASOPRESSOR_ITEMIDS)
    assert not (set(allowed) & vaso), \
        "allow-list contains vasopressors -- these ARE the escalation target"
    tgt_proc = set(int(i) for i in config.ESCALATION_PROC_ITEMIDS_EXT)
    assert not (set(allowed) & tgt_proc), "allow-list overlaps the target procedures"
    log.info("leakage assertions passed: %d allowed itemids, %d explicitly forbidden",
             len(allowed), len(forbidden))

    co = pd.read_parquet(config.dpath("cohort.parquet"))
    stay_ids = [int(x) for x in co["stay_id"].unique()]

    sql = (f"SELECT stay_id, hadm_id, starttime, endtime, itemid, rate, amount "
           f"FROM {config.icu('inputevents')} "
           f"WHERE stay_id IN UNNEST(@ids) AND itemid IN UNNEST(@items)")
    d = bq.query_df(sql, [bigquery.ArrayQueryParameter("ids", "INT64", stay_ids),
                          bigquery.ArrayQueryParameter("items", "INT64", allowed)])
    d["starttime"] = pd.to_datetime(d["starttime"])
    d["endtime"] = pd.to_datetime(d["endtime"])
    d["label"] = d["itemid"].map(config.INFUSION_ALLOWED_ITEMIDS)

    # belt-and-braces: nothing forbidden may survive into the file
    assert not d["itemid"].isin(forbidden).any(), "forbidden itemid present in output"

    out = config.dpath("infusions_ext.parquet")
    d.to_parquet(out, index=False)
    log.info("wrote %s (%d rows, %d stays)", out, len(d), d["stay_id"].nunique())

    N = len(stay_ids)
    print("\n" + "=" * 86)
    print(f"INFUSION ALLOW-LIST — coverage on {N:,} CCU stays")
    print("=" * 86)
    g = (d.groupby(["itemid", "label"])
           .agg(n_stays=("stay_id", "nunique"), n_rows=("rate", "size"),
                n_with_rate=("rate", "count"))
           .reset_index().sort_values("n_stays", ascending=False))
    print(f"  {'itemid':>7} {'label':30} {'stays':>7} {'coverage':>9} "
          f"{'rows/stay':>10} {'has rate':>9}")
    for r in g.itertuples():
        print(f"  {r.itemid:>7} {str(r.label)[:30]:30} {r.n_stays:>7,} "
              f"{r.n_stays/N:>9.1%} {r.n_rows/r.n_stays:>10.1f} "
              f"{r.n_with_rate/r.n_rows:>9.1%}")
    print(f"\n  stays with >=1 allowed infusion: {d.stay_id.nunique():,} "
          f"({d.stay_id.nunique()/N:.1%})")
    print(f"  EXCLUDED as leakage: {sorted(config.INFUSION_FORBIDDEN_ITEMIDS.values())}")
    print("=" * 86 + "\n")


if __name__ == "__main__":
    main()
