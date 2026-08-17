"""
Stage 04 — Evaluate the survival models against the pre-registered gates.

Metrics (overall + DCM subcohort):
  * Harrell C-index (+ cluster-bootstrap 95% CI by subject) for every model.
  * GATE 1: does AFT-full beat the NEWS2-slope heuristic (and Cox) on C-index?
  * GATE 2: alert burden — at 80% sensitivity, PPV / alerts-per-true-event /
            specificity for AFT-full vs NEWS2-slope vs NEWS2-only.
  * Interval coverage of the 5-95% band (conformal vs parametric); target ~0.90.
  * Median-time MAE on observed events; lead-time of true-positive alerts.
  * SHAP global importance (top features) for AFT-full.

Reads data/preds_test.parquet + data/models/. Writes data/metrics.json and
data/shap_summary.csv + charts/.
Run: py -3 04_evaluate.py
"""
from __future__ import annotations

import json
import logging
import os

import numpy as np
import pandas as pd
from lifelines.utils import concordance_index

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("eval")
CHARTS = config.dpath("charts"); os.makedirs(CHARTS, exist_ok=True)

# model column -> (score, higher_is_longer_survival)
MODELS = {
    "AFT-full":    ("pred_median", True),
    "AFT-news2":   ("pred_median_news2only", True),
    "Cox":         ("cox_risk", False),          # partial hazard: higher = sooner
    "NEWS2-slope": ("news2_slope_risk", False),  # heuristic risk: higher = sooner
}


def cindex(df, score_col, higher_is_longer):
    s = df[score_col].values.astype(float)
    if not higher_is_longer:
        s = -s
    m = ~np.isnan(s)
    if m.sum() < 10:
        return np.nan
    return concordance_index(df["T_hours"].values[m], s[m], df["event"].values[m])


def bootstrap_cindex(df, score_col, higher_is_longer, n=200):
    subs = df["subject_id"].unique()
    rng = np.random.default_rng(config.RANDOM_SEED)
    vals = []
    by_sub = {s: g for s, g in df.groupby("subject_id")}
    for _ in range(n):
        pick = rng.choice(subs, size=len(subs), replace=True)
        boot = pd.concat([by_sub[s] for s in pick], ignore_index=True)
        c = cindex(boot, score_col, higher_is_longer)
        if not np.isnan(c):
            vals.append(c)
    if not vals:
        return (np.nan, np.nan)
    return (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5)))


def alert_burden(df, score_col, higher_is_longer, sens_target=0.80):
    """At the threshold achieving `sens_target` recall of events, report PPV etc."""
    s = df[score_col].values.astype(float)
    risk = s if not higher_is_longer else -s          # higher risk = sooner event
    y = df["event"].values.astype(int)
    m = ~np.isnan(risk)
    risk, y = risk[m], y[m]
    if y.sum() == 0:
        return {}
    # threshold = the risk value at the (1-sens) quantile among positives
    thr = np.quantile(risk[y == 1], 1 - sens_target)
    pred = risk >= thr
    tp = int((pred & (y == 1)).sum()); fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum()); tn = int((~pred & (y == 0)).sum())
    sens = tp / (tp + fn) if (tp + fn) else np.nan
    ppv = tp / (tp + fp) if (tp + fp) else np.nan
    spec = tn / (tn + fp) if (tn + fp) else np.nan
    return dict(sensitivity=round(sens, 3), ppv=round(ppv, 3), specificity=round(spec, 3),
                alerts_per_true_event=round((tp + fp) / tp, 2) if tp else None,
                alert_rate=round(pred.mean(), 3))


def interval_coverage(df, lo_col, hi_col):
    ev = df[df["event"] == 1]
    if len(ev) == 0:
        return np.nan
    inside = (ev["T_hours"] >= ev[lo_col]) & (ev["T_hours"] <= ev[hi_col])
    return float(inside.mean())


def evaluate_block(df, label):
    res = {}
    for name, (col, hil) in MODELS.items():
        if col not in df:
            continue
        c = cindex(df, col, hil)
        lo, hi = bootstrap_cindex(df, col, hil)
        res[name] = dict(c_index=round(c, 4) if not np.isnan(c) else None,
                         ci95=[round(lo, 4), round(hi, 4)] if not np.isnan(lo) else None,
                         alert_burden_at_80_sens=alert_burden(df, col, hil))
    # median MAE + lead time on events (AFT-full)
    ev = df[df["event"] == 1]
    if len(ev):
        res["AFT-full"]["median_MAE_h"] = round(float(np.mean(np.abs(ev["pred_median"] - ev["T_hours"]))), 2)
        res["AFT-full"]["lead_time_median_h"] = round(float(ev["pred_median"].median()), 2)
    # interval coverage
    res["interval_coverage"] = dict(
        conformal=round(interval_coverage(df, "conf_lo", "conf_hi"), 3)
        if "conf_lo" in df else None,
        parametric=round(interval_coverage(df, "par_lo", "par_hi"), 3)
        if "par_lo" in df else None,
    )
    res["n_rows"] = len(df); res["n_events"] = int(df["event"].sum())
    log.info("[%s] AFT-full C=%s vs NEWS2-slope C=%s | coverage(conformal)=%s",
             label, res.get("AFT-full", {}).get("c_index"),
             res.get("NEWS2-slope", {}).get("c_index"),
             res["interval_coverage"]["conformal"])
    return res


def run_shap(metrics):
    try:
        import pickle, shap, xgboost as xgb
        aft = xgb.Booster(); aft.load_model(os.path.join(config.dpath("models"), "aft_full.json"))
        with open(os.path.join(config.dpath("models"), "feature_sample_train.pkl"), "rb") as f:
            sample = pickle.load(f)
        X, cols = sample["X"], sample["cols"]
        expl = shap.TreeExplainer(aft)
        sv = expl.shap_values(xgb.DMatrix(X, feature_names=cols))
        imp = pd.DataFrame({"feature": cols, "mean_abs_shap": np.abs(sv).mean(0)}) \
                .sort_values("mean_abs_shap", ascending=False)
        imp.to_csv(config.dpath("shap_summary.csv"), index=False)
        log.info("SHAP top-12:\n%s", imp.head(12).to_string(index=False))
        metrics["shap_top12"] = imp.head(12).to_dict("records")
    except Exception as e:
        log.warning("SHAP failed: %s", e)


def main():
    df = pd.read_parquet(config.dpath("preds_test.parquet"))
    log.info("test rows=%d events=%d DCM=%d", len(df), int(df["event"].sum()), int(df["dcm_flag"].sum()))
    metrics = {"overall": evaluate_block(df, "overall")}
    dcm = df[df["dcm_flag"]]
    if dcm["event"].sum() >= 10:
        metrics["dcm_subcohort"] = evaluate_block(dcm, "DCM")
    else:
        log.warning("DCM subcohort has <10 events (%d) — skipping stratified eval", int(dcm["event"].sum()))
    run_shap(metrics)

    # ---- gate verdicts ----
    o = metrics["overall"]
    aft_c = o.get("AFT-full", {}).get("c_index") or 0
    base_c = o.get("NEWS2-slope", {}).get("c_index") or 0
    cov = o["interval_coverage"]["conformal"]
    metrics["GATES"] = {
        "beats_news2_slope": bool(aft_c > base_c),
        "aft_c_index": aft_c, "news2_slope_c_index": base_c,
        "coverage_in_range": bool(cov is not None and 0.85 <= cov <= 0.95),
        "conformal_coverage": cov,
    }
    with open(config.dpath("metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    log.info("GATES: %s", json.dumps(metrics["GATES"], indent=2))
    log.info("wrote metrics.json")


if __name__ == "__main__":
    main()
