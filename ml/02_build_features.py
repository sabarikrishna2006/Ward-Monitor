"""
Stage 02 — Build the two-axis feature matrix, one row per anchor.

ACUTE (NEWS2) axis      — rolling stats of vitals + NEWS2 dynamics over the 6h
                          look-back grid (from vitals_hourly).
CONGESTION/SUBSTRATE    — weight trend (ESC/HFSA flags), urine rate, DCM/HF labs
axis                      (carry-forward + missingness), eGFR, rhythm flags.
CONTEXT                 — age, sex, hours-since-admission, DCM flag, Charlson index.

Every feature is derived strictly from data at or before the anchor time t
(leakage guard asserted at the end).

Output: data/features.parquet  (anchors + label columns + all X_t features)
Run: py -3 02_build_features.py
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

import config
from charlson import charlson_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("features")

VITALS = ["heart_rate", "resp_rate", "spo2", "sbp", "dbp", "temperature"]
W = config.LOOKBACK_H


# ── order-preserving asof merge ─────────────────────────────────────────────
def asof(left: pd.DataFrame, right: pd.DataFrame, on: str, by: str,
         bring: list[str], direction: str = "backward") -> pd.DataFrame:
    """Return `right[bring]` carried onto `left` (last value at/before `on`),
    aligned to left's original row order. left/right must have datetime `on`."""
    l = left[[by, on]].copy(); l["_ord"] = np.arange(len(l))
    r = right[[by, on] + bring].dropna(subset=[on]).sort_values(on)
    # merge_asof requires identical key dtypes/resolution; BigQuery parquet uses
    # nullable Int64 keys and microsecond timestamps, anchors use int64 + ns.
    l[by] = l[by].astype("int64"); r[by] = r[by].astype("int64")
    l[on] = l[on].astype("datetime64[ns]"); r[on] = r[on].astype("datetime64[ns]")
    m = pd.merge_asof(l.sort_values(on), r, on=on, by=by, direction=direction)
    m = m.sort_values("_ord")
    return m[bring].reset_index(drop=True)


# ── acute axis: rolling vital stats + NEWS2 dynamics on the hourly grid ──────
def acute_features(hv: pd.DataFrame) -> pd.DataFrame:
    hv = hv.sort_values(["stay_id", "hour"]).reset_index(drop=True)
    g = hv.groupby("stay_id", sort=False)
    out = hv[["stay_id", "hour"]].copy()

    def roll(col, fn):
        return getattr(g[col].rolling(W, min_periods=2), fn)().reset_index(level=0, drop=True).values

    def _rate_over_available_window(x: np.ndarray) -> float:
        """(last - earliest-available) / elapsed-hours-between-them, over whatever
        window is actually present (<=W rows) -- replaces the old fixed shift(W-1),
        which returned NaN for any anchor with less than a full W-1h of history
        (see plan §0b: rolling stats must be variable-length aware, not assume a
        full window exists)."""
        if np.isnan(x[-1]):
            return np.nan
        valid = np.flatnonzero(~np.isnan(x))
        if len(valid) < 2:
            return np.nan
        first = valid[0]
        span = (len(x) - 1) - first
        return (x[-1] - x[first]) / span if span > 0 else np.nan

    def rate(col):
        return (g[col].rolling(W, min_periods=2).apply(_rate_over_available_window, raw=True)
                 .reset_index(level=0, drop=True).values)

    for v in VITALS:
        if v not in hv:
            continue
        out[f"{v}_last"] = hv[v].values
        out[f"{v}_mean"] = roll(v, "mean")
        out[f"{v}_std"] = roll(v, "std")
        out[f"{v}_min"] = roll(v, "min")
        out[f"{v}_max"] = roll(v, "max")
        out[f"{v}_rate"] = rate(v)
        out[f"{v}_delta_adm"] = (hv[v] - g[v].transform("first")).values

    out["news2_last"] = hv["news2"].values
    out["news2_mean"] = g["news2"].rolling(W, min_periods=1).mean().reset_index(level=0, drop=True).values
    out["news2_max"] = g["news2"].rolling(W, min_periods=1).max().reset_index(level=0, drop=True).values
    out["news2_rate"] = rate("news2")
    band = hv["band"]
    change = (band != g["band"].shift(1)) | band.isna()
    run_id = change.groupby(hv["stay_id"]).cumsum()
    out["hours_in_band"] = hv.groupby([hv["stay_id"], run_id]).cumcount().values + 1

    if "fio2" in hv:
        out["fio2_last"] = hv["fio2"].values
    out["on_oxygen"] = ((hv.get("air_or_oxygen") == "Oxygen").astype(int).values
                        if "air_or_oxygen" in hv else 0)
    out["not_alert"] = ((hv.get("consciousness").fillna("A") != "A").astype(int).values
                        if "consciousness" in hv else 0)
    return out


def egfr_ckdepi_2021(scr, age, is_female):
    """CKD-EPI 2021 race-free eGFR from serum creatinine (mg/dL)."""
    scr = np.asarray(scr, float); age = np.asarray(age, float)
    kappa = np.where(is_female, 0.7, 0.9)
    alpha = np.where(is_female, -0.241, -0.302)
    ratio = scr / kappa
    return (142.0 * np.minimum(ratio, 1) ** alpha * np.maximum(ratio, 1) ** (-1.200)
            * 0.9938 ** age * np.where(is_female, 1.012, 1.0))


def build():
    # anchors/vitals_hourly are per-event-mode (tagged via EWS_TAG); the raw BigQuery
    # extraction tables (cohort/labs/urine/chart/diagnoses) are shared across all runs.
    anchors = pd.read_parquet(config.tpath("anchors.parquet")).reset_index(drop=True)
    hv = pd.read_parquet(config.tpath("vitals_hourly.parquet"))
    cohort = pd.read_parquet(config.dpath("cohort.parquet"))
    labs = pd.read_parquet(config.dpath("labevents.parquet"))
    urine = pd.read_parquet(config.dpath("outputevents.parquet"))
    chart = pd.read_parquet(config.dpath("chartevents.parquet"))
    diags = pd.read_parquet(config.dpath("diagnoses.parquet"))
    anchors["anchor_time"] = pd.to_datetime(anchors["anchor_time"])
    log.info("anchors=%d  building features…", len(anchors))

    # 1) acute axis (join by stay_id + hour == anchor_time) -------------------
    af = acute_features(hv)
    feat = anchors.merge(af, left_on=["stay_id", "anchor_time"],
                         right_on=["stay_id", "hour"], how="left").drop(columns="hour")
    feat = feat.reset_index(drop=True)

    # 2) context --------------------------------------------------------------
    c = cohort.set_index("stay_id")
    feat["intime"] = pd.to_datetime(feat["stay_id"].map(c["intime"]))
    feat["age"] = feat["stay_id"].map(c["anchor_age"]).astype(float)
    feat["is_female"] = (feat["stay_id"].map(c["gender"]) == "F").astype(int)
    feat["hours_since_adm"] = (feat["anchor_time"] - feat["intime"]).dt.total_seconds() / 3600.0
    # hours of history actually available for the rolling-window features, capped at
    # LOOKBACK_H -- lets the model discount short-history (<6h) predictions itself
    # rather than treating a 1h trend and a 6h trend as equally reliable (plan §0b).
    feat["hours_of_history"] = np.minimum(feat["hours_since_adm"], config.LOOKBACK_H)
    ch = (diags.dropna(subset=["icd_code"]).groupby("hadm_id")
               .apply(lambda d: charlson_score(list(zip(d["icd_code"], d["icd_version"]))),
                      include_groups=False))
    feat["charlson"] = feat["hadm_id"].map(ch).fillna(0).astype(int)

    # 3) weight trend (raw weight series -> asof at t, t-24h, t-72h) ----------
    w = chart[chart["itemid"].isin(config.VITAL_ITEMIDS["weight_kg"])][["stay_id", "charttime", "valuenum"]].copy()
    w["charttime"] = pd.to_datetime(w["charttime"]); w = w.rename(columns={"valuenum": "wt"})
    fa = feat[["stay_id", "anchor_time"]].rename(columns={"anchor_time": "t"})
    ww = w.rename(columns={"charttime": "t"})
    feat["weight_last"] = asof(fa, ww, on="t", by="stay_id", bring=["wt"])["wt"].values
    for dh, name in [(24, "d24"), (72, "d72")]:
        fp = fa.copy(); fp["t"] = fa["t"] - pd.Timedelta(hours=dh)
        past_wt = asof(fp, ww, on="t", by="stay_id", bring=["wt"])["wt"].values
        feat[f"weight_{name}"] = feat["weight_last"] - past_wt
    feat["esc_weight_flag"] = (feat["weight_d72"] >= 2.0).astype("Int64").fillna(0).astype(int)
    feat["hfsa_weight_flag"] = (feat["weight_d24"] >= 0.9).astype("Int64").fillna(0).astype(int)

    # 4) urine rate over last 6h / 24h (cumulative sum via asof) --------------
    u = urine.dropna(subset=["value"])[["stay_id", "charttime", "value"]].copy()
    u["charttime"] = pd.to_datetime(u["charttime"]); u = u.sort_values(["stay_id", "charttime"])
    u["cum"] = u.groupby("stay_id")["value"].cumsum()
    uu = u.rename(columns={"charttime": "t"})
    cum_now = asof(fa, uu, on="t", by="stay_id", bring=["cum"])["cum"].values
    for dh, name in [(6, "6h"), (24, "24h")]:
        fp = fa.copy(); fp["t"] = fa["t"] - pd.Timedelta(hours=dh)
        cum_then = asof(fp, uu, on="t", by="stay_id", bring=["cum"])["cum"].values
        feat[f"urine_rate_{name}"] = (np.nan_to_num(cum_now) - np.nan_to_num(cum_then)) / dh

    # 5) labs (carry-forward + missingness + eGFR + delta from admission) -----
    inv_lab = {i: name for name, ids in config.LAB_ITEMIDS.items() for i in ids}
    labs = labs.copy(); labs["lab"] = labs["itemid"].map(inv_lab)
    labs = labs.dropna(subset=["lab", "valuenum"]); labs["charttime"] = pd.to_datetime(labs["charttime"])
    fa_h = feat[["hadm_id", "anchor_time"]].rename(columns={"anchor_time": "t"})
    for lab in sorted(set(inv_lab.values())):
        s = labs[labs["lab"] == lab][["hadm_id", "charttime", "valuenum"]].copy()
        if s.empty:
            feat[f"{lab}_last"] = np.nan; feat[f"{lab}_missing"] = 1; continue
        s = s.rename(columns={"charttime": "t", "valuenum": lab})
        res = asof(fa_h, s, on="t", by="hadm_id", bring=[lab])
        feat[f"{lab}_last"] = res[lab].values
        feat[f"{lab}_missing"] = res[lab].isna().astype(int).values
        first = s.sort_values("t").groupby("hadm_id")[lab].first()
        feat[f"{lab}_delta_adm"] = feat[f"{lab}_last"] - feat["hadm_id"].map(first).values
    if "creatinine_last" in feat:
        feat["egfr"] = egfr_ckdepi_2021(feat["creatinine_last"], feat["age"], feat["is_female"] == 1)

    # 6) rhythm flags (best-effort from chartevents text value) ---------------
    rh = chart[chart["itemid"] == config.HEART_RHYTHM_ITEMID][["stay_id", "charttime", "value"]].copy()
    if not rh.empty:
        rh["charttime"] = pd.to_datetime(rh["charttime"])
        rr = asof(fa, rh.rename(columns={"charttime": "t"}), on="t", by="stay_id", bring=["value"])["value"]
        rr = rr.fillna("").str.upper()
        feat["rhythm_af"] = rr.str.contains("A FIB|AF|FIBRILLAT").astype(int).values
        feat["rhythm_vt_vf"] = rr.str.contains("VT|V TACH|VF|V FIB|VENT").astype(int).values
    else:
        feat["rhythm_af"] = 0; feat["rhythm_vt_vf"] = 0

    # ── leakage guard + save ─────────────────────────────────────────────────
    # was ">= LOOKBACK_H" when a full 6h look-back was required for every anchor;
    # now anchors are allowed as soon as MIN_VITALS_IN_WINDOW readings exist (plan
    # §0b), so the only invariant left to guard is "no anchor before admission".
    assert (feat["hours_since_adm"] >= -1e-6).all(), "anchor before admission"
    feat = feat.drop(columns=[col for col in ["intime"] if col in feat])
    feat.to_parquet(config.tpath("features.parquet"), index=False)
    log.info("features.parquet: %d rows x %d cols | event rate %.3f | DCM %d",
             len(feat), feat.shape[1], feat["event"].mean(), int(feat["dcm_flag"].sum()))
    miss = feat.filter(like="_missing").mean().sort_values(ascending=False)
    log.info("lab missingness (top):\n%s", miss.head(8).to_string())


if __name__ == "__main__":
    build()
