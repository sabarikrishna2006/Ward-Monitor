"""
Stage 09 — Train the FOCUSED base model: ONE event (time to sustained NEWS2>=7),
ONE feature family (the 7 NEWS2 parameters + trends + minimal context), ONE model
(XGBoost survival:aft). No DCM axis, no labs, no multi-model comparison.

This directly answers the 2026-07 review's core question -- "what do we actually
predict, and how accurate is it?" -- by reporting, from the SAME fitted model:

  1. pred_median        the naive AFT median (what the professor asked to see plotted,
                         with its known pathology explained, not hidden)
  2. p_event_within_h    P(T<=h | x) for h in {6,12,24}, ISOTONIC-CALIBRATED on a
                         held-out calibration split -- a real, checkable probability,
                         immune to the median's censoring-driven inflation.
  3. cond_time_within_h  E[T | T<=h, x] -- the conditional expected time, which is
                         the apples-to-apples quantity to compare against actual
                         event times (unlike the unconditional median).
  4. ruler_time          a trivial "extend the NEWS2 slope until it crosses 7"
                         baseline. The event is NEWS2-defined and the features are
                         NEWS2-only, so THIS is the floor the model must beat --
                         without it we cannot tell if the model adds anything.

WHY the naive median is expected to look bad (say this out loud, don't hide it):
if P(event within the horizon) < 50%, a PERFECTLY CALIBRATED model's median is
mathematically forced beyond the horizon (the survival curve never reaches 0.5
in-window). Our event rate is ~13%, so this is expected, not a model failure.
That is exactly why (2) and (3) exist.

Split: reuses 03_train.py's three_way_split (patient-level 70/15/15). Train and
test predictions are BOTH emitted (with a `split` column) for the overfitting
check the professor asked be applied to every model.

Outputs:
  data/preds_news2.parquet     every anchor (train+calib+test) with all predictions
  data/models_news2/aft_focused.json         the trained booster
  data/models_news2/calibrators.pkl          per-horizon isotonic calibrators
  data/models_news2/meta.json                dist, sigma, conformal offsets, features
Run: EWS_TAG=news2 py -3 09_focused_train.py
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import pickle

import numpy as np
import pandas as pd
import xgboost as xgb
from lifelines.utils import concordance_index
from scipy.stats import gumbel_l, logistic, norm
from sklearn.isotonic import IsotonicRegression

import config
from known_status import known_subset

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("focused_train")

# 03_train.py isn't a valid Python identifier (leading digit) -- import by file name.
_t = importlib.import_module("03_train")
three_way_split, make_dmatrix, train_aft = _t.three_way_split, _t.make_dmatrix, _t.train_aft

MODEL_DIR = config.dpath("models_news2")
os.makedirs(MODEL_DIR, exist_ok=True)

AFT_SIGMA = 1.0
DIST_RV = {"normal": norm, "logistic": logistic, "extreme": gumbel_l}

META = ["stay_id", "hadm_id", "subject_id", "anchor_time", "T_hours", "event",
        "cause", "dcm_flag", "news2_at_anchor"]


def news2_feature_cols(df: pd.DataFrame) -> list[str]:
    """The FOCUSED feature set: NEWS2 params/trends + minimal context. Nothing else
    (no labs, no weight, no BNP/eGFR/rhythm/Charlson/DCM flag as a feature)."""
    cols = [c for c in df.columns
            if c.startswith(config.NEWS2_FEATURE_PREFIXES) or c in config.CONTEXT_FEATURES]
    return sorted(set(cols))


# labs/congestion axis: adds INPUT features only, same event label, same split --
# compatible with the professor's locked NEWS2>=7 label (2026-07-22/23). Chosen
# by mechanistic plausibility for a CCU (cardiac) population at 2-24h horizons,
# not "include everything because it's there":
#   high-confidence (real mechanism + reasonable data availability): lactate
#     (perfusion/shock), troponin_t (myocardial injury), creatinine/egfr
#     (cardiorenal), potassium (arrhythmia risk), weight trend + ESC/HFSA flags
#     (guideline congestion signal), urine_rate (dynamic, bedside-checked hourly),
#     rhythm_af/vt_vf (direct arrhythmia precursors).
#   lower-confidence (kept in, expect little from them, not cherry-picked out):
#     bnp/nt_probnp (81.6% missing -- usually a one-off admission draw, not a
#     serial trend), sodium/hemoglobin/inr/platelets (more indirect/chronic
#     markers than acute 2-24h precursors).
LABS_FEATURE_PREFIXES = tuple(f"{lab}_" for lab in config.LAB_ITEMIDS) + (
    "egfr", "weight_", "esc_weight_flag", "hfsa_weight_flag", "urine_rate_", "rhythm_")


def focused_plus_labs_feature_cols(df: pd.DataFrame) -> list[str]:
    """news2_feature_cols() PLUS the labs/congestion axis above."""
    base = set(news2_feature_cols(df))
    labs = {c for c in df.columns if c.startswith(LABS_FEATURE_PREFIXES)}
    return sorted(base | labs)


def half_median_correction(dist: str, sigma: float) -> float:
    """XGBoost's raw survival:aft prediction is exp(mu), the location parameter --
    NOT the true median unless the assumed distribution is symmetric about 0.
    (normal/logistic: F^-1(0.5)=0, correction=1. extreme/Gumbel-min: F^-1(0.5)!=0,
    correction != 1.) true_median = raw_pred * this_factor, always correct."""
    return float(np.exp(sigma * DIST_RV[dist].ppf(0.5)))


def prob_within_horizon(raw_pred: np.ndarray, dist: str, sigma: float, h: float) -> np.ndarray:
    """Vectorized P(T <= h | x) directly from the fitted AFT distribution."""
    z = (np.log(h) - np.log(np.clip(raw_pred, 1e-6, None))) / sigma
    return DIST_RV[dist].cdf(z)


def conditional_expected_time(raw_pred: np.ndarray, dist: str, sigma: float, h: float,
                              grid_n: int = 400, eps: float = 1e-2) -> np.ndarray:
    """Vectorized E[T | T<=h, x] via numerical integration of the fitted density
    f_T(t) = f_Z((log t - mu)/sigma) / (t*sigma) on a grid over (eps, h].
    This is the quantity that is comparable to the actual time-to-event of patients
    who DID have the event within h -- unlike the unconditional median."""
    t_grid = np.linspace(eps, h, grid_n)                       # (G,)
    log_t = np.log(t_grid)
    mu = np.log(np.clip(raw_pred, 1e-6, None))                 # (N,)
    z = (log_t[None, :] - mu[:, None]) / sigma                 # (N,G)
    f = DIST_RV[dist].pdf(z) / (t_grid[None, :] * sigma)       # density of T, (N,G)
    num = np.trapezoid(t_grid[None, :] * f, t_grid, axis=1)
    den = np.trapezoid(f, t_grid, axis=1)
    return num / np.clip(den, 1e-12, None)


def news2_ruler_time(df: pd.DataFrame, target: float = 7.0, floor_time: float = 1e5) -> np.ndarray:
    """Trivial baseline: extrapolate this patient's OWN fitted NEWS2 slope
    (news2_last, news2_rate -- already-computed rolling-window features) forward
    until it crosses the target score. If the slope is flat/falling, the ruler
    predicts it will effectively never cross (a large time = lowest risk).
    This is the floor the AFT model must beat -- the event IS a NEWS2 threshold
    crossing and the features ARE NEWS2, so a naive linear extrapolation of the
    same score is a legitimate, non-trivial competitor."""
    last = df["news2_last"].values.astype(float)
    rate = df["news2_rate"].values.astype(float)
    time_to_cross = (target - last) / np.where(rate > 1e-6, rate, np.nan)
    time_to_cross = np.where((rate > 1e-6) & (time_to_cross > 0), time_to_cross, floor_time)
    return np.clip(time_to_cross, 1e-3, floor_time)


def cindex(T, score_higher_is_longer, event):
    m = ~np.isnan(score_higher_is_longer)
    return concordance_index(T[m], score_higher_is_longer[m], event[m])


def main():
    df = pd.read_parquet(config.tpath("features.parquet"))
    feats = news2_feature_cols(df)
    log.info("FOCUSED feature set: %d columns (NEWS2 params/trends + minimal context)", len(feats))
    log.info("features: %s", feats)
    log.info("rows=%d  event_rate=%.3f  DCM anchors=%d (not used as a feature)",
             len(df), df["event"].mean(), int(df["dcm_flag"].sum()))

    tr_i, cal_i, te_i = three_way_split(df)
    tr, cal, te = df.iloc[tr_i].copy(), df.iloc[cal_i].copy(), df.iloc[te_i].copy()
    log.info("split: train=%d calib=%d test=%d (subjects %d/%d/%d)",
             len(tr), len(cal), len(te), tr.subject_id.nunique(),
             cal.subject_id.nunique(), te.subject_id.nunique())

    def XY(d):
        return d[feats].astype(float).values, d["T_hours"].values, d["event"].values
    Xtr, Ttr, Etr = XY(tr); Xcal, Tcal, Ecal = XY(cal); Xte, Tte, Ete = XY(te)

    # ---- ONE model: pick AFT distribution by validation nloglik ----
    best_dist, best_booster, best_nll = None, None, np.inf
    for dist in ("normal", "logistic", "extreme"):
        b, nll = train_aft(Xtr, Ttr, Etr, None, Xcal, Tcal, Ecal, dist, AFT_SIGMA)
        log.info("focused AFT dist=%-9s val nloglik=%.4f", dist, nll)
        if nll < best_nll:
            best_dist, best_booster, best_nll = dist, b, nll
    log.info("chosen distribution: %s (val nloglik=%.4f)", best_dist, best_nll)
    aft = best_booster
    sigma = AFT_SIGMA
    med_corr = half_median_correction(best_dist, sigma)

    def raw_predict(X):
        return aft.predict(xgb.DMatrix(X), iteration_range=(0, aft.best_iteration + 1))

    raw_tr, raw_cal, raw_te = raw_predict(Xtr), raw_predict(Xcal), raw_predict(Xte)

    # ---- conformal calibration of the median (split-conformal on calib events) ----
    med_cal = raw_cal * med_corr
    ev_mask = Ecal == 1
    logres = np.log(np.clip(Tcal[ev_mask], 1e-3, None)) - np.log(np.clip(med_cal[ev_mask], 1e-3, None))
    c_lo, c_hi = np.quantile(logres, 0.05), np.quantile(logres, 0.95)
    log.info("conformal log-offsets: lo=%.3f hi=%.3f (n_calib_events=%d)", c_lo, c_hi, ev_mask.sum())

    def assemble(d, raw, split_name):
        out = d[META].copy()
        out["split"] = split_name
        out["pred_median"] = raw * med_corr
        out["conf_lo"] = out["pred_median"] * np.exp(c_lo)
        out["conf_hi"] = out["pred_median"] * np.exp(c_hi)
        out["ruler_time"] = news2_ruler_time(d)
        for h in config.HORIZONS_H:
            out[f"p_raw_{h}h"] = prob_within_horizon(raw, best_dist, sigma, h)
            out[f"cond_time_{h}h"] = conditional_expected_time(raw, best_dist, sigma, h)
        return out

    out_tr = assemble(tr, raw_tr, "train")
    out_cal = assemble(cal, raw_cal, "calib")
    out_te = assemble(te, raw_te, "test")

    # ---- isotonic calibration of P(T<=h), fit on calib using KNOWN-STATUS rows only ----
    calibrators = {}
    for h in config.HORIZONS_H:
        sub_cal, y_cal = known_subset(cal.assign(**{f"p_raw_{h}h": out_cal[f"p_raw_{h}h"].values}), h)
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        iso.fit(sub_cal[f"p_raw_{h}h"].values, y_cal)
        calibrators[h] = iso
        for out_d in (out_tr, out_cal, out_te):
            out_d[f"p_calibrated_{h}h"] = iso.predict(out_d[f"p_raw_{h}h"].values)
        dropped = 1.0 - len(sub_cal) / len(cal)
        log.info("horizon=%2dh  calib known-status rows=%d/%d (dropped %.1f%% unknown-status)",
                 h, len(sub_cal), len(cal), dropped * 100)

    preds = pd.concat([out_tr, out_cal, out_te], ignore_index=True)
    preds.to_parquet(config.tpath("preds_focused.parquet"), index=False)

    # ---- quick honesty check: train vs test C-index, AFT vs the NEWS2 ruler ----
    c_aft_tr = cindex(Ttr, out_tr["pred_median"].values, Etr)
    c_aft_te = cindex(Tte, out_te["pred_median"].values, Ete)
    c_ruler_tr = cindex(Ttr, out_tr["ruler_time"].values, Etr)
    c_ruler_te = cindex(Tte, out_te["ruler_time"].values, Ete)
    log.info("C-index  AFT   train=%.4f test=%.4f", c_aft_tr, c_aft_te)
    log.info("C-index ruler  train=%.4f test=%.4f", c_ruler_tr, c_ruler_te)
    if c_aft_te <= c_ruler_te:
        log.warning("*** AFT does NOT beat the NEWS2-slope ruler on test C-index. "
                    "Report this plainly -- do not bury it. ***")

    aft.save_model(os.path.join(MODEL_DIR, "aft_focused.json"))
    with open(os.path.join(MODEL_DIR, "calibrators.pkl"), "wb") as f:
        pickle.dump(calibrators, f)
    meta = dict(dist=best_dist, sigma=sigma, med_correction=med_corr,
                conf_lo=float(c_lo), conf_hi=float(c_hi), features=feats,
                val_nloglik=float(best_nll), horizons=config.HORIZONS_H,
                c_index_aft_train=float(c_aft_tr), c_index_aft_test=float(c_aft_te),
                c_index_ruler_train=float(c_ruler_tr), c_index_ruler_test=float(c_ruler_te))
    with open(os.path.join(MODEL_DIR, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    log.info("saved model + preds_news2.parquet (%d rows total)", len(preds))


if __name__ == "__main__":
    main()
