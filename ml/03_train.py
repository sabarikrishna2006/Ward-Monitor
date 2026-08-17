"""
Stage 03 — Train the XGBoost AFT survival model + baselines + ablations.

Models produced:
  * AFT-full     XGBoost `survival:aft` on the full two-axis feature set (PRIMARY)
  * AFT-news2    same objective, NEWS2-acute features only (ablation: does the
                 congestion/substrate axis add value?)
  * cox          lifelines CoxPH on a curated subset (linear survival baseline)
  * news2_slope  trivial heuristic risk = news2_last + k*news2_rate (must-beat gate)
  * quantile     3x `reg:quantileerror` on uncensored rows (documented ablation;
                 cannot use censored data)

Uncertainty band: parametric AFT quantiles AND split-conformal calibration of the
median (empirical ~90% coverage), computed on a held-out calibration split.

Split: GroupShuffleSplit by subject_id -> train / calib / test (70/15/15), so no
patient leaks across splits. DCM rows up-weighted; DCM test subcohort flagged.

Outputs:
  data/preds_test.parquet   test rows: labels + all model predictions/risks
  data/models/*.json|pkl    saved models + metadata
Run: py -3 03_train.py
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import pickle

import numpy as np
import pandas as pd
import xgboost as xgb
from scipy.stats import norm
from sklearn.model_selection import GroupShuffleSplit

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("train")

MODEL_DIR = config.dpath("models")
os.makedirs(MODEL_DIR, exist_ok=True)

DCM_UPWEIGHT = 3.0          # DCM rows count 3x in the loss
AFT_SIGMA = 1.0             # aft_loss_distribution_scale
AFT_DIST = "normal"         # {normal, logistic, extreme}; picked by val nloglik below

# non-feature columns
META = ["stay_id", "hadm_id", "subject_id", "anchor_time", "T_hours", "event",
        "cause", "dcm_flag", "news2_at_anchor"]
# curated, low-missingness subset for the Cox baseline (needs imputation)
COX_FEATURES = ["news2_last", "news2_rate", "heart_rate_last", "resp_rate_last",
                "spo2_last", "sbp_last", "age", "charlson", "hours_since_adm"]
# NEWS2-acute-only feature name prefixes (for the ablation model)
NEWS2_PREFIXES = ("news2_", "heart_rate_", "resp_rate_", "spo2_", "sbp_", "dbp_",
                  "temperature_", "hours_in_band", "on_oxygen", "not_alert", "fio2_")


def feature_cols(df) -> list[str]:
    return [c for c in df.columns if c not in META]


def three_way_split_legacy(df):
    """The original GroupShuffleSplit split. Patient-level and leak-free for any
    SINGLE build -- but NOT stable across builds: GroupShuffleSplit permutes the
    list of unique groups actually present, so changing the cohort (e.g. label v2
    drops 452 subjects whose event now fires before any anchor exists) reshuffles
    everyone. Measured agreement between the v1 and v2 builds was only 53%, which
    silently confounds any v1-vs-v2 comparison: the two models get different test
    patients. Kept only to reproduce pre-2026-07-27 numbers."""
    g = df["subject_id"].values
    idx = np.arange(len(df))
    gss = GroupShuffleSplit(n_splits=1, test_size=0.15, random_state=config.RANDOM_SEED)
    rest_i, test_i = next(gss.split(idx, groups=g))
    gss2 = GroupShuffleSplit(n_splits=1, test_size=0.1765, random_state=config.RANDOM_SEED)
    tr_i, cal_i = next(gss2.split(rest_i, groups=g[rest_i]))
    return rest_i[tr_i], rest_i[cal_i], test_i


def _subject_bucket(subject_ids: np.ndarray) -> np.ndarray:
    """Deterministic, uniform value in [0,1) per subject_id.

    md5 of "<subject_id>|<seed>", first 8 bytes as a big-endian integer, scaled to
    [0,1). md5 (not Python's built-in hash()) because hash() of a str is salted per
    process, so it would give a different split on every run."""
    uniq = np.unique(subject_ids)
    lut = {}
    for s in uniq:
        digest = hashlib.md5(f"{int(s)}|{config.RANDOM_SEED}".encode()).digest()
        lut[s] = int.from_bytes(digest[:8], "big") / float(1 << 64)
    return np.array([lut[s] for s in subject_ids], dtype=float)


def three_way_split(df, test_frac=0.15, calib_frac=0.15):
    """Patient-level 70/15/15 split that is STABLE ACROSS COHORTS.

    A subject's split is a pure function of its own subject_id, so it never depends
    on which other subjects happen to be present. That is what makes the label-v1
    vs label-v2 comparison valid: the same patient is a test patient under both
    builds, so the two models are scored on the same people.

    Still patient-level (every row of a subject lands in one split), so there is no
    leakage, exactly as before.
    """
    b = _subject_bucket(df["subject_id"].values)
    idx = np.arange(len(df))
    test_i = idx[b < test_frac]
    cal_i = idx[(b >= test_frac) & (b < test_frac + calib_frac)]
    tr_i = idx[b >= test_frac + calib_frac]
    return tr_i, cal_i, test_i


def _split_selftest():
    """The stability property, asserted rather than asserted-in-prose."""
    rng = np.random.default_rng(0)
    subj = rng.integers(1, 5000, size=4000)
    df = pd.DataFrame(dict(subject_id=subj, x=rng.normal(size=4000)))

    def assign(d):
        tr, cal, te = three_way_split(d)
        lab = np.empty(len(d), dtype=object)
        lab[tr] = "train"; lab[cal] = "calib"; lab[te] = "test"
        return pd.Series(lab, index=d["subject_id"].values).groupby(level=0).first()

    full = assign(df)
    # no patient in two splits
    per_subj = pd.DataFrame(dict(s=df.subject_id.values, lab=None))
    tr, cal, te = three_way_split(df)
    per_subj.loc[tr, "lab"] = "train"; per_subj.loc[cal, "lab"] = "calib"; per_subj.loc[te, "lab"] = "test"
    assert per_subj.groupby("s")["lab"].nunique().max() == 1, "a subject crossed splits"

    # drop a random 30% of SUBJECTS -- everyone remaining must keep their split
    keep = rng.choice(np.unique(subj), size=int(0.7 * len(np.unique(subj))), replace=False)
    sub = df[df.subject_id.isin(keep)]
    partial = assign(sub)
    common = full.index.intersection(partial.index)
    agree = (full.loc[common] == partial.loc[common]).mean()
    assert agree == 1.0, f"split not stable under cohort change: {agree:.2%} agreement"

    frac = full.value_counts(normalize=True)
    assert abs(frac.get("test", 0) - 0.15) < 0.03 and abs(frac.get("calib", 0) - 0.15) < 0.03, \
        f"split proportions off: {frac.to_dict()}"
    print(f"SELFTEST PASS -- three_way_split stable (100% agreement after dropping 30% of "
          f"subjects), proportions {dict(frac.round(3))}")
    return True


def make_dmatrix(X, T, event, weight=None):
    d = xgb.DMatrix(X, weight=weight)
    lo = T.astype(float).copy()
    hi = np.where(event == 1, T.astype(float), np.inf)   # censored -> upper = +inf
    d.set_float_info("label_lower_bound", lo)
    d.set_float_info("label_upper_bound", hi)
    return d


def train_aft(Xtr, Ttr, Etr, wtr, Xval, Tval, Eval, dist, sigma):
    dtr = make_dmatrix(Xtr, Ttr, Etr, wtr)
    dval = make_dmatrix(Xval, Tval, Eval)
    params = {
        "objective": "survival:aft",
        "eval_metric": "aft-nloglik",
        "aft_loss_distribution": dist,
        "aft_loss_distribution_scale": sigma,
        "tree_method": "hist",
        "learning_rate": 0.05,
        "max_depth": 4,
        "min_child_weight": 20,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_lambda": 2.0,
        "seed": config.RANDOM_SEED,
    }
    evals_result = {}
    booster = xgb.train(params, dtr, num_boost_round=600,
                        evals=[(dtr, "train"), (dval, "val")],
                        early_stopping_rounds=40, evals_result=evals_result, verbose_eval=False)
    best = evals_result["val"]["aft-nloglik"][booster.best_iteration]
    return booster, best


def q_factor(dist, sigma, q):
    """Multiplicative factor exp(sigma * F^{-1}(q)) for AFT parametric quantiles."""
    if dist == "normal":
        z = norm.ppf(q)
    elif dist == "logistic":
        z = np.log(q / (1 - q))
    else:  # extreme value (Weibull)
        z = np.log(-np.log(1 - q))
    return float(np.exp(sigma * z))


def main():
    df = pd.read_parquet(config.dpath("features.parquet"))
    feats = feature_cols(df)
    log.info("features=%d  rows=%d  event_rate=%.3f", len(feats), len(df), df["event"].mean())

    tr_i, cal_i, te_i = three_way_split(df)
    tr, cal, te = df.iloc[tr_i], df.iloc[cal_i], df.iloc[te_i]
    log.info("split: train=%d calib=%d test=%d (subjects %d/%d/%d)",
             len(tr), len(cal), len(te), tr.subject_id.nunique(),
             cal.subject_id.nunique(), te.subject_id.nunique())

    def XY(d, cols=feats):
        return d[cols].astype(float).values, d["T_hours"].values, d["event"].values
    Xtr, Ttr, Etr = XY(tr); Xcal, Tcal, Ecal = XY(cal); Xte, Tte, Ete = XY(te)
    wtr = 1.0 + DCM_UPWEIGHT * tr["dcm_flag"].values.astype(float)

    # ── pick AFT distribution by validation nloglik ──────────────────────────
    best_dist, best_booster, best_nll = None, None, np.inf
    for dist in ("normal", "logistic", "extreme"):
        b, nll = train_aft(Xtr, Ttr, Etr, wtr, Xcal, Tcal, Ecal, dist, AFT_SIGMA)
        log.info("AFT-full dist=%-9s val nloglik=%.4f", dist, nll)
        if nll < best_nll:
            best_dist, best_booster, best_nll = dist, b, nll
    log.info("chosen AFT distribution: %s", best_dist)
    aft = best_booster

    def aft_median(booster, X):
        return booster.predict(xgb.DMatrix(X), iteration_range=(0, booster.best_iteration + 1))
    med_te = aft_median(aft, Xte)
    # parametric quantiles
    q05f = q_factor(best_dist, AFT_SIGMA, 0.05)
    q95f = q_factor(best_dist, AFT_SIGMA, 0.95)
    par_lo, par_hi = med_te * q05f, med_te * q95f

    # ── split-conformal calibration of the median (uncensored calib events) ──
    med_cal = aft_median(aft, Xcal)
    ev = Ecal == 1
    logres = np.log(np.clip(Tcal[ev], 1e-3, None)) - np.log(np.clip(med_cal[ev], 1e-3, None))
    c_lo, c_hi = np.quantile(logres, 0.05), np.quantile(logres, 0.95)
    conf_lo, conf_hi = med_te * np.exp(c_lo), med_te * np.exp(c_hi)
    log.info("conformal log-offsets: lo=%.3f hi=%.3f (n_calib_events=%d)", c_lo, c_hi, ev.sum())

    # ── ablation: NEWS2-acute-only AFT ───────────────────────────────────────
    n2_feats = [c for c in feats if c.startswith(NEWS2_PREFIXES)]
    Xn_tr = tr[n2_feats].astype(float).values; Xn_te = te[n2_feats].astype(float).values
    Xn_cal = cal[n2_feats].astype(float).values
    aft_n2, _ = train_aft(Xn_tr, Ttr, Etr, wtr, Xn_cal, Tcal, Ecal, best_dist, AFT_SIGMA)
    med_te_n2 = aft_median(aft_n2, Xn_te)

    # ── must-beat heuristic: NEWS2 slope risk (higher => sooner event) ────────
    news2_slope_risk = np.nan_to_num(te["news2_last"].values) + 2.0 * np.nan_to_num(te["news2_rate"].values)

    # ── Cox PH baseline (lifelines, curated + imputed) ───────────────────────
    cox_risk = np.full(len(te), np.nan)
    try:
        from lifelines import CoxPHFitter
        cols = [c for c in COX_FEATURES if c in df.columns]
        med = tr[cols].median()
        cxtr = tr[cols].fillna(med).copy(); cxtr["T"] = Ttr; cxtr["E"] = Etr
        cph = CoxPHFitter(penalizer=0.1).fit(cxtr, "T", "E")
        cox_risk = cph.predict_partial_hazard(te[cols].fillna(med)).values.ravel()
        log.info("Cox fitted on %d curated features", len(cols))
    except Exception as e:
        log.warning("Cox baseline failed: %s", e)

    # ── ablation: reg:quantileerror on uncensored rows only ──────────────────
    quant_preds = {}
    try:
        m = Etr == 1
        dqt = xgb.DMatrix(Xtr[m], label=np.clip(Ttr[m], 1e-3, None))
        qp = {"objective": "reg:quantileerror", "quantile_alpha": config.QUANTILES,
              "tree_method": "hist", "learning_rate": 0.05, "max_depth": 4, "seed": config.RANDOM_SEED}
        qbooster = xgb.train(qp, dqt, num_boost_round=300)
        qout = qbooster.predict(xgb.DMatrix(Xte))   # shape (n, 3)
        for j, a in enumerate(config.QUANTILES):
            quant_preds[f"q_{a}"] = qout[:, j]
        log.info("quantile-regression ablation trained on %d uncensored rows", m.sum())
    except Exception as e:
        log.warning("quantile ablation failed: %s", e)

    # ── save predictions on test ─────────────────────────────────────────────
    out = te[META].copy()
    out["pred_median"] = med_te
    out["par_lo"], out["par_hi"] = par_lo, par_hi
    out["conf_lo"], out["conf_hi"] = conf_lo, conf_hi
    out["pred_median_news2only"] = med_te_n2
    out["news2_slope_risk"] = news2_slope_risk
    out["cox_risk"] = cox_risk
    for k, v in quant_preds.items():
        out[k] = v
    out.to_parquet(config.dpath("preds_test.parquet"), index=False)

    aft.save_model(os.path.join(MODEL_DIR, "aft_full.json"))
    aft_n2.save_model(os.path.join(MODEL_DIR, "aft_news2.json"))
    meta = dict(dist=best_dist, sigma=AFT_SIGMA, conf_lo=float(c_lo), conf_hi=float(c_hi),
                features=feats, news2_features=n2_feats, dcm_upweight=DCM_UPWEIGHT,
                val_nloglik=float(best_nll))
    with open(os.path.join(MODEL_DIR, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    with open(os.path.join(MODEL_DIR, "feature_sample_train.pkl"), "wb") as f:
        pickle.dump({"X": tr[feats].astype(float).values[:2000], "cols": feats}, f)
    log.info("saved models + preds_test.parquet (%d test rows)", len(out))


if __name__ == "__main__":
    main()
