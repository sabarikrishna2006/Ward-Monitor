"""
Stage 13 — AFT retrained on the FOCUSED feature set PLUS the labs/congestion axis
(lactate, troponin, creatinine/eGFR, potassium, weight trend + ESC/HFSA flags,
urine output rate, rhythm flags -- see 09_focused_train.py::LABS_FEATURE_PREFIXES
for the exact list and the mechanistic reasoning behind each one). Same event
label (sustained NEWS2>=7), same train/calib/test split, same horizons as
09_focused_train.py -- this changes ONLY which input features the model sees,
so its numbers are directly comparable in 10_focused_report.py's
model_comparison_table.

Mirrors 09_focused_train.py exactly; reuses all its helpers (half_median_correction,
prob_within_horizon, conditional_expected_time, news2_ruler_time, cindex) and
03_train.py's three_way_split/train_aft rather than reimplementing them.

Outputs:
  data/preds_focused_labs_news2.parquet   every anchor (train+calib+test) with all predictions
  data/models_news2_labs/aft_focused_labs.json
  data/models_news2_labs/calibrators.pkl
  data/models_news2_labs/meta.json
Run: EWS_TAG=news2 py -3 13_focused_train_labs.py
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
from sklearn.isotonic import IsotonicRegression

import config
from known_status import known_subset

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("focused_train_labs")

_t3 = importlib.import_module("03_train")
three_way_split, train_aft = _t3.three_way_split, _t3.train_aft
_t9 = importlib.import_module("09_focused_train")
focused_plus_labs_feature_cols = _t9.focused_plus_labs_feature_cols
half_median_correction = _t9.half_median_correction
prob_within_horizon = _t9.prob_within_horizon
conditional_expected_time = _t9.conditional_expected_time
news2_ruler_time = _t9.news2_ruler_time
cindex = _t9.cindex

MODEL_DIR = config.dpath("models_news2_labs")
os.makedirs(MODEL_DIR, exist_ok=True)
OUT_NAME = f"preds_focused_labs_{config.TAG}.parquet" if config.TAG else "preds_focused_labs.parquet"

AFT_SIGMA = 1.0

META = ["stay_id", "hadm_id", "subject_id", "anchor_time", "T_hours", "event",
        "cause", "dcm_flag", "news2_at_anchor"]


def main():
    df = pd.read_parquet(config.tpath("features.parquet"))
    feats = focused_plus_labs_feature_cols(df)
    log.info("FOCUSED+LABS feature set: %d columns (focused NEWS2 family + labs/congestion axis)", len(feats))
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

    best_dist, best_booster, best_nll = None, None, np.inf
    for dist in ("normal", "logistic", "extreme"):
        b, nll = train_aft(Xtr, Ttr, Etr, None, Xcal, Tcal, Ecal, dist, AFT_SIGMA)
        log.info("focused+labs AFT dist=%-9s val nloglik=%.4f", dist, nll)
        if nll < best_nll:
            best_dist, best_booster, best_nll = dist, b, nll
    log.info("chosen distribution: %s (val nloglik=%.4f)", best_dist, best_nll)
    aft = best_booster
    sigma = AFT_SIGMA
    med_corr = half_median_correction(best_dist, sigma)

    def raw_predict(X):
        return aft.predict(xgb.DMatrix(X), iteration_range=(0, aft.best_iteration + 1))

    raw_tr, raw_cal, raw_te = raw_predict(Xtr), raw_predict(Xcal), raw_predict(Xte)

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
    preds.to_parquet(config.dpath(OUT_NAME), index=False)

    c_aft_tr = cindex(Ttr, out_tr["pred_median"].values, Etr)
    c_aft_te = cindex(Tte, out_te["pred_median"].values, Ete)
    c_ruler_tr = cindex(Ttr, out_tr["ruler_time"].values, Etr)
    c_ruler_te = cindex(Tte, out_te["ruler_time"].values, Ete)
    log.info("C-index  AFT+labs   train=%.4f test=%.4f", c_aft_tr, c_aft_te)
    log.info("C-index  ruler      train=%.4f test=%.4f", c_ruler_tr, c_ruler_te)
    if c_aft_te <= c_ruler_te:
        log.warning("*** AFT+labs does NOT beat the NEWS2-slope ruler on test C-index. "
                    "Report this plainly -- do not bury it. ***")

    # feature-importance check: which of the NEW (labs/congestion) features actually
    # got used, vs. which contributed ~nothing (per user request -- verify, don't assert).
    gain = aft.get_score(importance_type="gain")
    imp = pd.Series({feats[int(k[1:])]: v for k, v in gain.items()}).sort_values(ascending=False)
    from importlib import import_module as _im
    labs_prefixes = _im("09_focused_train").LABS_FEATURE_PREFIXES
    is_labs_feat = {f: f.startswith(labs_prefixes) for f in feats}
    log.info("Top 15 features by gain (labs/congestion features marked):")
    for f, v in imp.head(15).items():
        tag = "[LABS]" if is_labs_feat.get(f) else ""
        log.info("  %-28s gain=%10.1f %s", f, v, tag)
    labs_imp = imp[[f for f in imp.index if is_labs_feat.get(f)]]
    log.info("Labs/congestion features that made the top-30 by gain: %d of %d added",
             sum(f in imp.head(30).index for f in labs_imp.index), len(labs_imp))

    aft.save_model(os.path.join(MODEL_DIR, "aft_focused_labs.json"))
    with open(os.path.join(MODEL_DIR, "calibrators.pkl"), "wb") as f:
        pickle.dump(calibrators, f)
    meta = dict(dist=best_dist, sigma=sigma, med_correction=med_corr,
                conf_lo=float(c_lo), conf_hi=float(c_hi), features=feats,
                val_nloglik=float(best_nll), horizons=config.HORIZONS_H,
                c_index_aft_train=float(c_aft_tr), c_index_aft_test=float(c_aft_te),
                c_index_ruler_train=float(c_ruler_tr), c_index_ruler_test=float(c_ruler_te),
                top15_feature_gain=imp.head(15).to_dict())
    with open(os.path.join(MODEL_DIR, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    log.info("saved model + %s (%d rows total)", OUT_NAME, len(preds))


if __name__ == "__main__":
    main()
