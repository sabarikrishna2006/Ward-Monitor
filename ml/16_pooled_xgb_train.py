"""
Stage 16 — Cell B of the architecture ablation: ONE pooled XGBoost with the
interval index as an input feature, instead of seven independent boosters.

WHY THIS SCRIPT EXISTS (the actual research question).
The professor's criticism is that `12_ordinal_train.py` trains seven completely
disjoint classifiers that "do not learn from each other", and that a shared-trunk
multi-head MLP would fix it. That is a correct description of the code — but his
proposed fix changes TWO things at once:

    independent -> shared        AND        gradient-boosted trees -> neural net

If the MLP wins we cannot say which change caused it; if it loses we cannot say
whether sharing didn't help or the MLP was simply a worse learner on tabular data.

This script changes ONLY the first. The person-period table for all seven
intervals is stacked into one training set (1.1M rows), `interval_j` is added as
an ordinary input column, and a single booster is fit. Every tree split is now
learned jointly from all intervals' data, so parameters ARE shared — with the
base learner held fixed at XGBoost.

  B ~= A  ->  parameter sharing was never the bottleneck. That is evidence, not
              an opinion, and it reframes the MLP from "the fix" to "the
              confirmation".
  B >  A  ->  the professor's diagnosis is confirmed and the MLP is justified.

Everything downstream of the hazard estimate is IDENTICAL to 12_ordinal_train.py
(same person-period masking, same isotonic calibration per interval, same
running-product survival reconstruction, same output schema) so the comparison
isolates the one change under test.

Run: PYTHONUTF8=1 EWS_TAG=news2 py -3 16_pooled_xgb_train.py
     PYTHONUTF8=1 EWS_TAG=news2_v2lab py -3 16_pooled_xgb_train.py
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
log = logging.getLogger("pooled_xgb")

_t3 = importlib.import_module("03_train")
_t9 = importlib.import_module("09_focused_train")
_t12 = importlib.import_module("12_ordinal_train")
three_way_split = _t3.three_way_split
news2_feature_cols, news2_ruler_time = _t9.news2_feature_cols, _t9.news2_ruler_time
build_person_period_table = _t12.build_person_period_table
reconstruct_survival = _t12.reconstruct_survival
conditional_expected_time_24h = _t12.conditional_expected_time_24h
cindex = _t12.cindex
cluster_bootstrap_cindex_ci = _t12.cluster_bootstrap_cindex_ci

MODEL_DIR = config.tpath("models_pooled_xgb")
os.makedirs(MODEL_DIR, exist_ok=True)

META = ["stay_id", "hadm_id", "subject_id", "anchor_time", "T_hours", "event",
        "cause", "dcm_flag", "news2_at_anchor"]

INTERVAL_COL = "interval_j"


def train_pooled(Xtr, ytr, Xval, yval):
    """Same hyperparameters as 12_ordinal_train.train_interval_classifier, with one
    deliberate exception: num_boost_round is raised from 600 to 2000.

    Reason — capacity fairness, not tuning. Cell A gets 600 rounds PER INTERVAL,
    i.e. up to 4,200 trees in total across its seven boosters. Capping the pooled
    model at 600 would hand A a 7x capacity advantage and confound the comparison
    with the very thing we are testing. Both models stop via early stopping on
    their own validation split, so neither is forced to use its ceiling.
    """
    dtr = xgb.DMatrix(Xtr, label=ytr)
    dval = xgb.DMatrix(Xval, label=yval)
    params = {
        "objective": "binary:logistic",
        "eval_metric": "auc",
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
    booster = xgb.train(params, dtr, num_boost_round=2000,
                        evals=[(dtr, "train"), (dval, "val")],
                        early_stopping_rounds=50, evals_result=evals_result,
                        verbose_eval=False)
    return booster, float(evals_result["val"]["auc"][booster.best_iteration])


def main():
    cutpoints = [0.0] + [float(h) for h in config.HORIZONS_H]
    df = pd.read_parquet(config.tpath("features.parquet"))
    feats = news2_feature_cols(df)
    pooled_feats = feats + [INTERVAL_COL]
    log.info("pooled feature set: %d columns (%d NEWS2 features + interval_j)",
             len(pooled_feats), len(feats))

    tr_i, cal_i, te_i = three_way_split(df)     # identical split to cell A
    tr, cal, te = df.iloc[tr_i].copy(), df.iloc[cal_i].copy(), df.iloc[te_i].copy()
    log.info("split: train=%d calib=%d test=%d (subjects %d/%d/%d)",
             len(tr), len(cal), len(te), tr.subject_id.nunique(),
             cal.subject_id.nunique(), te.subject_id.nunique())

    # ---- ONE training set, all intervals stacked -----------------------------
    pp_tr = build_person_period_table(tr, config.HORIZONS_H)
    pp_cal = build_person_period_table(cal, config.HORIZONS_H)
    log.info("POOLED person-period rows: train=%d calib=%d  (cell A trains 7 disjoint "
             "subsets of these same rows; this trains one model on all of them)",
             len(pp_tr), len(pp_cal))
    log.info("rows per interval (train): %s",
             pp_tr.groupby(INTERVAL_COL).size().to_dict())

    Xtr = pp_tr[pooled_feats].astype(float).values
    ytr = pp_tr["py_label"].values.astype(float)
    Xcal = pp_cal[pooled_feats].astype(float).values
    ycal = pp_cal["py_label"].values.astype(float)

    booster, val_auc = train_pooled(Xtr, ytr, Xcal, ycal)
    log.info("pooled booster: best_iteration=%d  pooled_val_auc=%.4f",
             booster.best_iteration, val_auc)

    # ---- per-interval isotonic calibration (IDENTICAL to cell A) -------------
    # Calibrating per interval, not globally, keeps calibration out of the
    # comparison: any A-vs-B difference is then attributable to the hazard
    # estimate itself rather than to how it was calibrated.
    calibrators, per_interval_val_auc = {}, {}
    for j, h in enumerate(config.HORIZONS_H, start=1):
        sub = pp_cal[pp_cal[INTERVAL_COL] == j]
        Xj = sub[pooled_feats].astype(float).values
        yj = sub["py_label"].values.astype(float)
        raw = booster.predict(xgb.DMatrix(Xj), iteration_range=(0, booster.best_iteration + 1))
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        iso.fit(raw, yj)
        calibrators[h] = iso
        try:
            from sklearn.metrics import roc_auc_score
            per_interval_val_auc[str(h)] = float(roc_auc_score(yj, raw))
        except Exception:
            per_interval_val_auc[str(h)] = float("nan")
        log.info("interval j=%d (<=%2gh)  calib_rows=%6d  interval_val_auc=%.4f",
                 j, h, len(sub), per_interval_val_auc[str(h)])

    # ---- inference: same anchor, seven interval-stamped copies ---------------
    def hazard_matrix(d):
        """(n, 7) hazards. Built one interval at a time rather than materialising a
        7n-row matrix: 7 predictions of (n x 56) instead of one (7n x 56)."""
        X = d[feats].astype(float).values
        raw = np.empty((len(d), len(config.HORIZONS_H)), dtype=float)
        for j, _h in enumerate(config.HORIZONS_H, start=1):
            Xj = np.column_stack([X, np.full(len(d), float(j))])
            raw[:, j - 1] = booster.predict(xgb.DMatrix(Xj),
                                            iteration_range=(0, booster.best_iteration + 1))
        return raw

    def calibrated(raw):
        out = np.column_stack([calibrators[h].predict(raw[:, j])
                               for j, h in enumerate(config.HORIZONS_H)])
        return np.clip(out, 0.0, 1.0)   # isotonic interpolation can emit 1.0000001

    def assemble(d, split_name):
        out = d[META].copy()
        out["split"] = split_name
        raw = hazard_matrix(d)
        cal_h = calibrated(raw)
        S_raw, S_cal = reconstruct_survival(raw), reconstruct_survival(cal_h)
        assert (np.diff(S_cal, axis=1) <= 1e-9).all(), "S(c_j) is not non-increasing"
        for j, h in enumerate(config.HORIZONS_H):
            out[f"p_raw_{h}h"] = 1.0 - S_raw[:, j + 1]
            out[f"p_calibrated_{h}h"] = 1.0 - S_cal[:, j + 1]
        out["cond_time_24h"] = conditional_expected_time_24h(S_cal, cutpoints)
        out["ruler_time"] = news2_ruler_time(d)
        return out

    out_tr, out_cal, out_te = assemble(tr, "train"), assemble(cal, "calib"), assemble(te, "test")
    preds = pd.concat([out_tr, out_cal, out_te], ignore_index=True)
    preds.to_parquet(config.tpath("preds_pooled_xgb.parquet"), index=False)

    surv24_tr = 1.0 - out_tr["p_calibrated_24h"].values
    surv24_te = 1.0 - out_te["p_calibrated_24h"].values
    c_tr = cindex(tr["T_hours"].values, surv24_tr, tr["event"].values)
    c_te = cindex(te["T_hours"].values, surv24_te, te["event"].values)
    ci_lo, ci_hi, n_boot = cluster_bootstrap_cindex_ci(
        te["T_hours"].values, surv24_te, te["event"].values, te["subject_id"].values)
    log.info("C-index  POOLED  train=%.4f test=%.4f  (95%% CI [%.4f, %.4f], n_boot=%d)",
             c_tr, c_te, ci_lo, ci_hi, n_boot)
    if (c_tr - c_te) > 0.05:
        log.warning("*** train/test C-index gap %.4f > 0.05 -- possible overfit ***", c_tr - c_te)

    booster.save_model(os.path.join(MODEL_DIR, "pooled_hazard.json"))
    with open(os.path.join(MODEL_DIR, "calibrators.pkl"), "wb") as f:
        pickle.dump(calibrators, f)
    gain = booster.get_score(importance_type="gain")
    interval_gain_rank = sorted(gain.items(), key=lambda kv: -kv[1])
    idx_name = f"f{len(feats)}"          # interval_j is the last column
    with open(os.path.join(MODEL_DIR, "meta.json"), "w") as f:
        json.dump(dict(
            architecture="pooled XGBoost, interval_j as input feature (ablation cell B)",
            horizons=config.HORIZONS_H, features=pooled_feats,
            n_pooled_train_rows=int(len(pp_tr)), n_pooled_calib_rows=int(len(pp_cal)),
            best_iteration=int(booster.best_iteration), pooled_val_auc=val_auc,
            per_interval_val_auc=per_interval_val_auc,
            c_index_train=float(c_tr), c_index_test=float(c_te),
            c_index_test_ci=[ci_lo, ci_hi], c_index_test_ci_n_boot=n_boot,
            interval_j_gain=float(gain.get(idx_name, float("nan"))),
            interval_j_gain_rank=int([k for k, _ in interval_gain_rank].index(idx_name)) + 1
            if idx_name in gain else None,
            top10_gain=[(k, round(v, 1)) for k, v in interval_gain_rank[:10]],
        ), f, indent=2)
    log.info("saved pooled model + calibrators + preds_pooled_xgb.parquet (%d rows)", len(preds))
    log.info("interval_j gain rank among %d features: %s", len(pooled_feats),
             ([k for k, _ in interval_gain_rank].index(idx_name) + 1) if idx_name in gain else "n/a")


if __name__ == "__main__":
    main()
