"""
extended_grid.py — fold the newly-extracted variables onto the hourly grid.

The existing `01_build_labels.assemble_hourly_vitals` only knows the seven NEWS2
parameters, because that is all `00_extract_cohort.py` pulled. This module adds the
substrate discovered by querying d_items directly (see 00c/00d), WITHOUT touching the
NEWS2 pipeline, so v1 artefacts stay reproducible.

FORWARD-FILL LIMITS ARE PER VARIABLE CLASS, and this matters. A heart rate from 20
hours ago is meaningless; a potassium from 20 hours ago is the patient's current
potassium. Using one global limit either throws away valid labs or invents stale
vitals. Limits below follow the measured sampling cadence:

    hemo (MAP)           6h    ~56 readings/stay, i.e. sub-hourly
    flowsheet labs      24h    ~6 readings/stay over a ~106h median stay
    neuro (GCS)         12h    ~14 readings/stay
    nurse_concern       12h    ~7 readings/stay (alarm limits change on rounds)
    frailty (Braden)    24h    ~8.6 readings/stay (assessed per shift)
    labevents           24h    intermittent draws
    invasive monitors  PRESENCE ONLY -- 8.6-27.4% coverage is too sparse for values,
                                but "somebody floated a PA catheter" is informative

LEAKAGE GUARD: ventilator settings are asserted absent. They exist only after
intubation, and intubation IS an event in the escalation target.
"""
from __future__ import annotations

import logging
import os

import numpy as np
import pandas as pd

import config

log = logging.getLogger("extended_grid")

FFILL_LIMIT_H = {
    "hemo": 6, "flowsheet_lab": 24, "neuro": 12,
    "nurse_concern": 12, "frailty": 24, "labevent": 24,
}

# short, stable column names -- itemid columns would be unreadable downstream
NAME_OF = {
    220181: "map", 220052: "map_art",
    227442: "potassium_f", 220645: "sodium_f", 220602: "chloride_f",
    220615: "creatinine_f", 225624: "bun_f", 227443: "hco3", 227073: "anion_gap",
    220621: "glucose_f", 220545: "hematocrit", 220228: "hemoglobin_f",
    220635: "magnesium", 227457: "platelets_f", 220546: "wbc",
    225625: "calcium", 225677: "phosphorous", 227467: "inr_f",
    227465: "pt", 227429: "troponin_f", 223830: "ph_art",
    223901: "gcs_motor", 220739: "gcs_eye", 223900: "gcs_verbal", 227346: "mental_status",
    220046: "hr_alarm_hi", 220047: "hr_alarm_lo", 223769: "spo2_alarm_hi",
    223770: "spo2_alarm_lo", 224161: "rr_alarm_hi", 224162: "rr_alarm_lo",
    223751: "nibp_alarm_hi", 223752: "nibp_alarm_lo", 224641: "alarms_on",
    224168: "params_checked", 226253: "spo2_desat_limit",
    224054: "braden_sensory", 224057: "braden_mobility", 224056: "braden_activity",
    224055: "braden_moisture", 224058: "braden_nutrition", 224059: "braden_friction",
    226531: "adm_weight_lbs",
    50813: "lactate_l", 50885: "bilirubin_l", 50820: "ph_l", 50821: "po2_l",
    50818: "pco2_l", 50802: "base_excess_l", 50862: "albumin_l", 51006: "bun_l",
}

CLASS_OF: dict[int, str] = {}
for i in config.HEMO_ITEMIDS:            CLASS_OF[i] = "hemo"
for i in config.FLOWSHEET_LAB_ITEMIDS:   CLASS_OF[i] = "flowsheet_lab"
for i in config.NEURO_ITEMIDS:           CLASS_OF[i] = "neuro"
for i in config.NURSE_CONCERN_ITEMIDS:   CLASS_OF[i] = "nurse_concern"
for i in config.FRAILTY_ITEMIDS:         CLASS_OF[i] = "frailty"
CLASS_OF[226531] = "frailty"
for i in config.EXTRA_LAB_ITEMIDS:       CLASS_OF[i] = "labevent"


def _assert_no_leaky_items(itemids) -> None:
    leaky = set(int(i) for i in config.LEAKY_POST_ESCALATION_ITEMIDS)
    bad = leaky & set(int(i) for i in itemids)
    assert not bad, (
        f"post-escalation ventilator settings present in the feature grid: {sorted(bad)}. "
        f"These exist only AFTER intubation, which is an event in the escalation target.")


def build_extended_grid(hours_index: pd.DataFrame) -> pd.DataFrame:
    """`hours_index` = the (stay_id, hour) skeleton from vitals_hourly.

    Returns one row per (stay_id, hour) with the extended variables forward-filled
    within their class limit, plus:
      <var>_hrs_since        hours since that variable was last actually MEASURED
                             (DETERIO's idea -- measurement frequency is a proxy for
                             clinical concern; a nurse checks more often when worried)
      has_<monitor>          presence flag for the sparse invasive monitors
      on_<drug>, <drug>_rate current infusion state from the allow-list
    """
    skel = hours_index[["stay_id", "hour"]].drop_duplicates().copy()
    skel["hour"] = pd.to_datetime(skel["hour"])
    out = skel.sort_values(["stay_id", "hour"]).reset_index(drop=True)

    frames = []
    ce_path = config.dpath("chartevents_ext.parquet")
    if os.path.exists(ce_path):
        ce = pd.read_parquet(ce_path, columns=["stay_id", "charttime", "itemid", "valuenum"])
        _assert_no_leaky_items(ce["itemid"].unique())
        ce["hour"] = pd.to_datetime(ce["charttime"]).dt.floor("h")
        frames.append(ce[["stay_id", "hour", "itemid", "valuenum"]])
    le_path = config.dpath("labevents_ext.parquet")
    if os.path.exists(le_path):
        le = pd.read_parquet(le_path, columns=["hadm_id", "charttime", "itemid", "valuenum"])
        co = pd.read_parquet(config.dpath("cohort.parquet"), columns=["stay_id", "hadm_id"])
        le = le.merge(co, on="hadm_id", how="inner")
        le["hour"] = pd.to_datetime(le["charttime"]).dt.floor("h")
        frames.append(le[["stay_id", "hour", "itemid", "valuenum"]])
    if not frames:
        log.warning("no extended sources on disk -- returning the bare skeleton")
        return out

    ev = pd.concat(frames, ignore_index=True)
    ev = ev[ev["itemid"].isin(NAME_OF)]
    ev["var"] = ev["itemid"].map(NAME_OF)
    ev["cls"] = ev["itemid"].map(CLASS_OF)

    # median-per-hour, then pivot to wide
    agg = (ev.groupby(["stay_id", "hour", "var"], observed=True)["valuenum"]
             .median().reset_index())
    wide = agg.pivot_table(index=["stay_id", "hour"], columns="var",
                           values="valuenum", observed=True).reset_index()
    out = out.merge(wide, on=["stay_id", "hour"], how="left")

    sparse = {NAME_OF[i] for i in config.INVASIVE_MONITOR_ITEMIDS if i in NAME_OF}
    var_cls = {NAME_OF[i]: CLASS_OF.get(i, "flowsheet_lab")
               for i in NAME_OF if NAME_OF[i] in out.columns}

    # Build derived columns in a dict and concat ONCE. Assigning ~90 columns one at a
    # time into a wide frame fragments the block manager and roughly triples runtime.
    g = out.groupby("stay_id", sort=False)
    pos = np.arange(len(out))
    derived: dict[str, np.ndarray] = {}
    drop: list[str] = []
    for var, cls in var_cls.items():
        if var not in out.columns:
            continue
        idx = np.where(out[var].notna().to_numpy(), pos, np.nan)
        last_idx = pd.Series(idx, index=out.index).groupby(out["stay_id"]).ffill()
        hrs_since = pos - last_idx.to_numpy()
        if var in sparse:
            # too sparse for values; keep only "has this monitor ever been used"
            derived[f"has_{var}"] = g[var].cummax().notna().astype(float).to_numpy()
            drop.append(var)
            continue
        derived[f"{var}_hrs_since"] = hrs_since
        lim = float(FFILL_LIMIT_H.get(cls, 12))
        filled = g[var].ffill(limit=int(lim)).to_numpy()
        # a value carried past its class limit is stale, not missing-at-random
        out[var] = np.where(hrs_since > lim, np.nan, filled)
    if drop:
        out = out.drop(columns=drop)
    if derived:
        out = pd.concat([out, pd.DataFrame(derived, index=out.index)], axis=1).copy()

    # ---- infusion state (allow-list only; leakage asserted at extraction) -----
    inf_path = config.dpath("infusions_ext.parquet")
    if os.path.exists(inf_path):
        inf = pd.read_parquet(inf_path)
        forbidden = set(int(i) for i in config.INFUSION_FORBIDDEN_ITEMIDS)
        assert not inf["itemid"].isin(forbidden).any(), \
            "forbidden (target-leaking) infusion itemid reached the feature grid"
        short = {225158: "nacl", 220949: "d5", 225152: "heparin",
                 227523: "magsulf", 227522: "kcl", 222056: "ntg", 228340: "furosemide"}
        inf["drug"] = inf["itemid"].map(short)
        inf = inf.dropna(subset=["drug"])
        inf["hour"] = pd.to_datetime(inf["starttime"]).dt.floor("h")
        r = (inf.groupby(["stay_id", "hour", "drug"], observed=True)["rate"]
                .max().reset_index()
                .pivot_table(index=["stay_id", "hour"], columns="drug",
                             values="rate", observed=True).reset_index())
        r.columns = [c if c in ("stay_id", "hour") else f"{c}_rate" for c in r.columns]
        out = out.merge(r, on=["stay_id", "hour"], how="left")
        g2 = out.groupby("stay_id", sort=False)
        for d in short.values():
            col = f"{d}_rate"
            if col not in out.columns:
                out[col] = np.nan
            out[f"on_{d}"] = out[col].notna().astype(float)
            out[col] = g2[col].ffill(limit=6)
        rate_cols = [f"{d}_rate" for d in short.values()]
        out["n_infusions_running"] = out[[f"on_{d}" for d in short.values()]].sum(axis=1)
        # rate CHANGE is the actual signal: nitroglycerin weaned as pressure falls,
        # furosemide escalated for congestion. Level alone misses the titration.
        g3 = out.groupby("stay_id", sort=False)
        for col in rate_cols:
            out[f"{col}_chg2h"] = out[col] - g3[col].shift(2)
        out["any_rate_increase_2h"] = (
            out[[f"{c}_chg2h" for c in rate_cols]].gt(0).any(axis=1).astype(float))

    log.info("extended grid: %d rows x %d columns (%d stays)",
             len(out), out.shape[1], out["stay_id"].nunique())
    return out


def multiwindow_features(grid: pd.DataFrame, anchors: pd.DataFrame,
                         value_cols: list[str],
                         windows=None) -> pd.DataFrame:
    """Per anchor, per variable, per window W: mean / std / slope, plus the explicit
    crossovers mean_2h - mean_6h and mean_2h - mean_12h, plus deviation from the
    patient's own 12h baseline.

    WHY THE EXPLICIT CROSSOVER AND NOT JUST THE TWO MEANS. Trees split on
    AXIS-ALIGNED thresholds. The diagonal boundary `mean_2h - mean_12h > 30` needs a
    STAIRCASE of (mean_2h, mean_12h) splits, and each step costs depth -- at
    max_depth=4 one path holds only four conditions, so a single diagonal consumes
    the whole tree. The explicit difference makes it ONE split. That is a genuine
    expansion of what is expressible at this depth, not a convenience.

    Clinically it separates two states the current feature set cannot: HR 100 on a
    12h mean of 100 (stably sick) from HR 100 on a 12h mean of 70 (accelerating).
    """
    windows = windows or config.LOOKBACK_WINDOWS
    g = grid.sort_values(["stay_id", "hour"]).set_index("hour")
    parts = []
    for W in windows:
        r = g.groupby("stay_id")[value_cols].rolling(f"{int(W)}h", min_periods=1)
        m = r.mean().rename(columns=lambda c: f"{c}_mean_{W}h")
        s = r.std().rename(columns=lambda c: f"{c}_std_{W}h")
        parts += [m, s]
    feat = pd.concat(parts, axis=1).reset_index()

    # slope over each window: (last - first) / hours, computed from the rolling mean
    # of the shortest window as the "last" proxy to stay cheap
    for W in windows:
        for c in value_cols:
            a, b = f"{c}_mean_{W}h", f"{c}_mean_{windows[0]}h"
            if a in feat.columns and b in feat.columns:
                feat[f"{c}_slope_{W}h"] = (feat[b] - feat[a]) / float(W)

    short, mid, long = windows[0], windows[1], windows[-1]
    for c in value_cols:
        s_, m_, l_ = f"{c}_mean_{short}h", f"{c}_mean_{mid}h", f"{c}_mean_{long}h"
        if s_ in feat.columns and m_ in feat.columns:
            feat[f"{c}_trend_{short}h_vs_{mid}h"] = feat[s_] - feat[m_]
        if s_ in feat.columns and l_ in feat.columns:
            feat[f"{c}_trend_{short}h_vs_{long}h"] = feat[s_] - feat[l_]
        if c in grid.columns and l_ in feat.columns:
            feat[f"{c}_dev_from_{long}h_baseline"] = grid[c].to_numpy() - feat[l_].to_numpy()

    a = anchors[["stay_id", "anchor_time"]].copy()
    a["hour"] = pd.to_datetime(a["anchor_time"]).dt.floor("h")
    merged = a.merge(feat, on=["stay_id", "hour"], how="left")
    return merged.drop(columns=["hour"])
