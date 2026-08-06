"""
Stage 00b — Re-extract escalation events with the EXPANDED CCU itemid list.

WHY THIS SCRIPT EXISTS. `00_extract_cohort.py` pulls inputevents/procedureevents
filtered to `config.ESCALATION_INPUT_ITEMIDS` / `ESCALATION_PROC_ITEMIDS`. Those
lists were chosen for a general deterioration model and are badly incomplete for a
cardiology unit — they contain no mechanical circulatory support at all (IABP,
Impella, ECMO: ~6% of this CCU), no cardiac arrest, no defibrillation, and not the
standalone Intubation itemid.

The trap: because the extract was filtered to the old definition, the parquet files
on disk contain ONLY those therapies. **A filtered extract makes its own definition
look complete.** Verifying "does our escalation target cover everything?" against
`data/procedureevents.parquet` will always answer yes. It took a `d_items` query to
find the gap, and it takes this re-pull to close it.

This writes a SEPARATE file and never touches the existing parquets, so every
current artefact stays reproducible.

Output: data/escalation_events_ext.parquet
    stay_id, hadm_id, starttime, itemid, source ('inputevents'|'procedureevents'),
    tier ('primary'|'ambiguous'), group (mcs|acute_event|rescue|vent|rrt|pressor|ambiguous)

Run: PYTHONUTF8=1 py -3 00b_extract_escalation_ext.py
"""
from __future__ import annotations

import logging

import pandas as pd
from google.cloud import bigquery

import bq
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("extract_esc_ext")

# itemid -> (group, tier). Groups let the label builder and the report attribute
# every event to a therapy class rather than a bare itemid.
GROUPS: dict[int, tuple[str, str]] = {}
for i in config.VASOPRESSOR_ITEMIDS:      GROUPS[i] = ("pressor", "primary")
for i in config.VENT_ITEMIDS:             GROUPS[i] = ("vent", "primary")
for i in config.RRT_ITEMIDS:              GROUPS[i] = ("rrt", "primary")
for i in config.MCS_ITEMIDS:              GROUPS[i] = ("mcs", "primary")
for i in config.ACUTE_EVENT_ITEMIDS:      GROUPS[i] = ("acute_event", "primary")
for i in config.RESCUE_PROC_ITEMIDS:      GROUPS[i] = ("rescue", "primary")
for i in config.AMBIGUOUS_ESCALATION_INPUT_ITEMIDS:
    GROUPS[i] = ("ambiguous", "ambiguous")

LABELS = {
    224272: "IABP line", 228169: "Impella Line", 229529: "ECMO Inflow Line",
    229530: "ECMO Outflow Line", 225466: "Cardiac Arrest", 225475: "Respiratory Arrest",
    225464: "Cardioversion/Defibrillation", 224385: "Intubation",
    225449: "Pericardiocentesis", 226477: "Temporary Pacemaker Wires Inserted",
    221347: "Amiodarone", 230034: "Amiodarone 150/100", 229654: "Amiodarone 450/250",
    228339: "Amiodarone 600/500", 225945: "Lidocaine", 221319: "Alteplase (TPA)",
}


def main():
    co = pd.read_parquet(config.dpath("cohort.parquet"))
    stay_ids = [int(x) for x in co["stay_id"].unique()]
    log.info("CCU cohort: %d stays", len(stay_ids))

    frames = []
    for table, items in (("procedureevents", config.ESCALATION_PROC_ITEMIDS_EXT),
                         ("inputevents", config.ESCALATION_INPUT_ITEMIDS_EXT)):
        items = sorted(set(int(i) for i in items))
        sql = (f"SELECT stay_id, hadm_id, starttime, itemid "
               f"FROM {config.icu(table)} "
               f"WHERE stay_id IN UNNEST(@ids) AND itemid IN UNNEST(@items)")
        params = [bigquery.ArrayQueryParameter("ids", "INT64", stay_ids),
                  bigquery.ArrayQueryParameter("items", "INT64", items)]
        log.info("querying %s for %d itemids…", table, len(items))
        d = bq.query_df(sql, params)
        d["source"] = table
        frames.append(d)
        log.info("  -> %d rows, %d distinct stays", len(d), d["stay_id"].nunique())

    ev = pd.concat(frames, ignore_index=True)
    ev["starttime"] = pd.to_datetime(ev["starttime"])
    ev["group"] = ev["itemid"].map(lambda i: GROUPS.get(int(i), ("unknown", "primary"))[0])
    ev["tier"] = ev["itemid"].map(lambda i: GROUPS.get(int(i), ("unknown", "primary"))[1])
    ev["label"] = ev["itemid"].map(LABELS).fillna("(in old definition)")

    out = config.dpath("escalation_events_ext.parquet")
    ev.to_parquet(out, index=False)
    log.info("wrote %s (%d rows)", out, len(ev))

    N = len(stay_ids)
    print("\n" + "=" * 82)
    print(f"ESCALATION EVENT INVENTORY — CCU cohort, {N:,} stays")
    print("=" * 82)
    for tier in ("primary", "ambiguous"):
        sub = ev[ev.tier == tier]
        print(f"\n  TIER: {tier}   ({sub.stay_id.nunique():,} stays, "
              f"{sub.stay_id.nunique()/N:.1%} of cohort)")
        print(f"    {'group':14} {'itemid':>7} {'label':32} {'stays':>7} {'pct':>7}")
        g = (sub.groupby(["group", "itemid", "label"])["stay_id"].nunique()
                .reset_index(name="n_stays")
                .sort_values(["group", "n_stays"], ascending=[True, False]))
        for r in g.itertuples():
            print(f"    {r.group:14} {r.itemid:>7} {r.label:32} "
                  f"{r.n_stays:>7,} {r.n_stays/N:>7.1%}")
    prim = ev[ev.tier == "primary"]
    print(f"\n  UNION of all PRIMARY escalation therapies: "
          f"{prim.stay_id.nunique():,} stays ({prim.stay_id.nunique()/N:.1%})")
    newg = prim[prim.group.isin(["mcs", "acute_event", "rescue"])]
    oldg = prim[prim.group.isin(["pressor", "vent", "rrt"])]
    only_new = set(newg.stay_id) - set(oldg.stay_id)
    print(f"  stays captured ONLY by the newly-added therapies: {len(only_new):,} "
          f"({len(only_new)/N:.1%})  <- invisible to the old definition")
    print("=" * 82 + "\n")


if __name__ == "__main__":
    main()
