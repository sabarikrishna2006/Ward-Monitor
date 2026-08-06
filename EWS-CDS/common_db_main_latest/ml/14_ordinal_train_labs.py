"""
Stage 14 — the discrete-time hazard model retrained on the FOCUSED feature set
PLUS the labs/congestion axis (see 09_focused_train.py::LABS_FEATURE_PREFIXES
for the exact list and reasoning). Same event label, cutpoints, split, and
person-period construction as 12_ordinal_train.py -- this changes ONLY which
input features the per-interval classifiers see, so its numbers are directly
comparable in 10_focused_report.py's model_comparison_table.

Mirrors 12_ordinal_train.py exactly; reuses its person-period/survival-curve
logic via import rather than reimplementing it.

Outputs:
  data/preds_ordinal_labs_news2.parquet
  data/models_ordinal_labs_news2/*.json|pkl
Run: EWS_TAG=news2 py -3 14_ordinal_train_labs.py
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ordinal_train_labs")

_t3 = importlib.import_module("03_train")
three_way_split = _t3.three_way_split
_t9 = importlib.import_module("09_focused_train")
focused_plus_labs_feature_cols = _t9.focused_plus_labs_feature_cols
news2_ruler_time = _t9.news2_ruler_time
LABS_FEATURE_PREFIXES = _t9.LABS_FEATURE_PREFIXES
_t12 = importlib.import_module("12_ordinal_train")
build_person_period_table = _t12.build_person_period_table
train_interval_classifier = _t12.train_interval_classifier
predict_hazard = _t12.predict_hazard
reconstruct_survival = _t12.reconstruct_survival
conditional_expected_time_24h = _t12.conditional_expected_time_24h
cindex = _t12.cindex
cluster_bootstrap_cindex_ci = _t12.cluster_bootstrap_cindex_ci

MODEL_DIR = config.dpath("models_ordinal_labs_news2")
os.makedirs(MODEL_DIR, exist_ok=True)
OUT_NAME = f"preds_ordinal_labs_{config.TAG}.parquet" if config.TAG else "preds_ordinal_labs.parquet"

META = ["stay_id", "hadm_id", "subject_id", "anchor_time", "T_hours", "event",
        "cause", "dcm_flag", "news2_at_anchor"]


def main():
    cutpoints = [0.0] + [float(h) for h in config.HORIZONS_H]
    df = pd.read_parquet(config.tpath("features.parquet"))
    feats = focused_plus_labs_feature_cols(df)
    log.info("ORDINAL+LABS feature set: %d columns (focused NEWS2 family + labs/congestion axis)", len(feats))
    log.info("rows=%d  event_rate=%.3f  horizons=%s", len(df), df["event"].mean(), config.HORIZONS_H)

    tr_i, cal_i, te_i = three_way_split(df)
    tr, cal, te = df.iloc[tr_i].copy(), df.iloc[cal_i].copy(), df.iloc[te_i].copy()
    log.info("split: train=%d calib=%d test=%d (subjects %d/%d/%d)",
             len(tr), len(cal), len(te), tr.subject_id.nunique(),
             cal.subject_id.nunique(), te.subject_id.nunique())

    pp_tr = build_person_period_table(tr, config.HORIZONS_H)
    pp_cal = build_person_period_table(cal, config.HORIZONS_H)
    log.info("person-period rows: train=%d (from %d anchors) calib=%d (from %d anchors)",
             len(pp_tr), len(tr), len(pp_cal), len(cal))

    boosters, calibrators, val_aucs = {}, {}, {}
    for j, h in enumerate(config.HORIZONS_H, start=1):
        sub_tr = pp_tr[pp_tr.interval_j == j]
        sub_cal = pp_cal[pp_cal.interval_j == j]
        Xtr_j = sub_tr[feats].astype(float).values
        ytr_j = sub_tr["py_label"].values.astype(float)
        Xcal_j = sub_cal[feats].astype(float).values
        ycal_j = sub_cal["py_label"].values.astype(float)

        booster, val_auc = train_interval_classifier(Xtr_j, ytr_j, Xcal_j, ycal_j)
        boosters[h] = booster
        val_aucs[h] = val_auc

        raw_hazard_cal = predict_hazard(booster, Xcal_j)
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        iso.fit(raw_hazard_cal, ycal_j)
        calibrators[h] = iso

        log.info("interval j=%d (<=%2gh)  train_rows=%6d (events=%4d)  calib_rows=%6d  val_auc=%.4f",
                 j, h, len(sub_tr), int(ytr_j.sum()), len(sub_cal), val_auc)

    def raw_hazard_matrix(d):
        X = d[feats].astype(float).values
        return np.column_stack([predict_hazard(boosters[h], X) for h in config.HORIZONS_H])

    def calibrated_hazard_matrix(raw_mat):
        # IsotonicRegression(y_min=0, y_max=1).predict() bounds the FITTED knots but
        # its interpolation step can round a hazard to e.g. 1.0000001 -- clip defensively
        # so (1 - hazard) never goes negative and breaks the survival curve's monotonicity.
        out = np.column_stack([calibrators[h].predict(raw_mat[:, j])
                               for j, h in enumerate(config.HORIZONS_H)])
        return np.clip(out, 0.0, 1.0)

    def assemble(d, split_name):
        out = d[META].copy()
        out["split"] = split_name
        raw_haz = raw_hazard_matrix(d)
        cal_haz = calibrated_hazard_matrix(raw_haz)
        S_raw = reconstruct_survival(raw_haz)
        S_cal = reconstruct_survival(cal_haz)
        assert (np.diff(S_cal, axis=1) <= 1e-9).all(), \
            "S(c_j) is not non-increasing -- person-period construction bug"
        for j, h in enumerate(config.HORIZONS_H):
            out[f"p_raw_{h}h"] = 1.0 - S_raw[:, j + 1]
            out[f"p_calibrated_{h}h"] = 1.0 - S_cal[:, j + 1]
        out["cond_time_24h"] = conditional_expected_time_24h(S_cal, cutpoints)
        out["ruler_time"] = news2_ruler_time(d)
        return out

    out_tr = assemble(tr, "train")
    out_cal = assemble(cal, "calib")
    out_te = assemble(te, "test")
    preds = pd.concat([out_tr, out_cal, out_te], ignore_index=True)
    preds.to_parquet(config.dpath(OUT_NAME), index=False)

    surv24_tr = 1.0 - out_tr["p_calibrated_24h"].values
    surv24_te = 1.0 - out_te["p_calibrated_24h"].values
    Ttr, Etr = tr["T_hours"].values, tr["event"].values
    Tte, Ete = te["T_hours"].values, te["event"].values

    c_haz_tr = cindex(Ttr, surv24_tr, Etr)
    c_haz_te = cindex(Tte, surv24_te, Ete)
    c_ruler_tr = cindex(Ttr, out_tr["ruler_time"].values, Etr)
    c_ruler_te = cindex(Tte, out_te["ruler_time"].values, Ete)
    ci_lo, ci_hi, n_boot_ok = cluster_bootstrap_cindex_ci(Tte, surv24_te, Ete, te["subject_id"].values)
    log.info("C-index  hazard+labs  train=%.4f test=%.4f  (test 95%% CI [%.4f, %.4f], n_boot=%d)",
             c_haz_tr, c_haz_te, ci_lo, ci_hi, n_boot_ok)
    log.info("C-index  ruler        train=%.4f test=%.4f", c_ruler_tr, c_ruler_te)
    if c_haz_te <= c_ruler_te:
        log.warning("*** hazard+labs model does NOT beat the NEWS2-slope ruler on test C-index. "
                    "Report this plainly -- do not bury it. ***")
    gap = c_haz_tr - c_haz_te
    if gap > 0.05:
        log.warning("*** train/test C-index gap = %.4f > 0.05 -- possible overfit, investigate before reporting. ***", gap)

    # feature-importance check across all 7 interval classifiers, aggregated by mean gain rank --
    # which of the NEW (labs/congestion) features actually got used across the horizons?
    gain_by_h = {}
    for h, booster in boosters.items():
        gain = booster.get_score(importance_type="gain")
        gain_by_h[h] = pd.Series({feats[int(k[1:])]: v for k, v in gain.items()})
    gain_df = pd.DataFrame(gain_by_h).fillna(0.0)
    mean_gain = gain_df.mean(axis=1).sort_values(ascending=False)
    is_labs_feat = {f: f.startswith(LABS_FEATURE_PREFIXES) for f in feats}
    log.info("Top 15 features by mean gain across all 7 intervals (labs/congestion marked):")
    for f, v in mean_gain.head(15).items():
        tag = "[LABS]" if is_labs_feat.get(f) else ""
        log.info("  %-28s mean_gain=%10.1f %s", f, v, tag)
    labs_feats_in_set = [f for f in feats if is_labs_feat.get(f)]
    n_labs_top30 = sum(f in mean_gain.head(30).index for f in labs_feats_in_set)
    log.info("Labs/congestion features that made the top-30 by mean gain: %d of %d added",
             n_labs_top30, len(labs_feats_in_set))

    for h, booster in boosters.items():
        booster.save_model(os.path.join(MODEL_DIR, f"hazard_interval_{h}h.json"))
    with open(os.path.join(MODEL_DIR, "calibrators.pkl"), "wb") as f:
        pickle.dump(calibrators, f)
    meta = dict(
        horizons=config.HORIZONS_H, features=feats,
        n_train_anchors=len(tr), n_calib_anchors=len(cal), n_test_anchors=len(te),
        n_train_stays=int(tr.subject_id.nunique()), n_calib_stays=int(cal.subject_id.nunique()),
        n_test_stays=int(te.subject_id.nunique()),
        per_interval_val_auc={str(h): val_aucs[h] for h in config.HORIZONS_H},
        c_index_hazard_train=float(c_haz_tr), c_index_hazard_test=float(c_haz_te),
        c_index_hazard_test_ci=[ci_lo, ci_hi], c_index_hazard_test_ci_n_boot=n_boot_ok,
        c_index_ruler_train=float(c_ruler_tr), c_index_ruler_test=float(c_ruler_te),
        top15_mean_gain=mean_gain.head(15).to_dict(),
    )
    with open(os.path.join(MODEL_DIR, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    log.info("saved %d interval models + calibrators + %s (%d rows total)",
             len(boosters), OUT_NAME, len(preds))


if __name__ == "__main__":
    main()
