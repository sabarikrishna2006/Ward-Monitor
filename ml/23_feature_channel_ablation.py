"""
Stage 23 — Is NEWS2 helping the model, or CROWDING OUT the raw vitals?

THE HYPOTHESIS UNDER TEST (Sabari's, 2026-07-27).
The pooled model's top four features by gain are all summaries of the NEWS2 score
itself (news2_mean 747.6, news2_at_anchor 545.9, news2_max 313.4, news2_last 288.3);
the first individual vital is heart_rate_last at rank 8 with 5.5x less gain than
news2_mean alone. I read that as "the vitals carry no extra information". The
sharper reading is the opposite:

  NEWS2 IS LOSSY COMPRESSION OF THE VITALS.
  A respiratory rate of 25 and a respiratory rate of 35 both score 3. Systolic BP
  of 90 and of 200 both score 3 (opposite ends, same score). NEWS2 throws away
  within-band magnitude, direction, and the identity of WHICH organ system is
  failing. If a greedy depth-4 tree finds NEWS2 splits first — and it will, because
  NEWS2 is a strong pre-aggregated ordinal — the residual signal in the raw vitals
  may simply never get reached.

If that is right, REMOVING the NEWS2 features should not hurt much, and might help,
because the model is then forced to use the un-compressed inputs.

FOUR CONFIGURATIONS, identical everything else (split, label, calibration,
reconstruction, hyperparameters unless stated):

  full          all 55 features (current baseline)
  news2_only    only news2_* + hours_in_band + context  -- how much is in the score alone?
  vitals_only   all 48 raw-vital features + context, NEWS2 features REMOVED
  vitals_deep   vitals_only with max_depth 4 -> 8, because depth is the mechanism
                by which crowding-out would happen: with depth 4 a path can combine
                only 4 features, so if NEWS2 occupies 2-3 levels the vitals rarely
                get used. If depth is the constraint, this is where it shows.

READING THE RESULT:
  vitals_only ~= full   -> NEWS2 is redundant; the vitals contain everything.
  vitals_only <  full   -> NEWS2 adds a genuine aggregation prior; not crowding out.
  vitals_only >  full   -> NEWS2 was actively hurting by dominating early splits.
  vitals_deep >> vitals_only -> depth was the binding constraint, not information.

Run: PYTHONUTF8=1 EWS_TAG=news2 py -3 23_feature_channel_ablation.py
"""
from __future__ import annotations

import argparse
import importlib
import json
import logging

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score, average_precision_score

import config
import eval_core as ec
from known_status import known_subset

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("feat_ablation")

_t3 = importlib.import_module("03_train")
_t9 = importlib.import_module("09_focused_train")
_t12 = importlib.import_module("12_ordinal_train")
three_way_split = _t3.three_way_split
news2_feature_cols = _t9.news2_feature_cols
build_person_period_table = _t12.build_person_period_table
reconstruct_survival = _t12.reconstruct_survival
cindex = _t12.cindex

# every feature name that is a function of the NEWS2 SCORE rather than of a vital
NEWS2_SCORE_PREFIXES = ("news2_",)
NEWS2_SCORE_EXTRA = ("hours_in_band",)


def split_feature_channels(feats: list[str]) -> dict[str, list[str]]:
    score = [c for c in feats if c.startswith(NEWS2_SCORE_PREFIXES) or c in NEWS2_SCORE_EXTRA]
    context = [c for c in feats if c in config.CONTEXT_FEATURES]
    vitals = [c for c in feats if c not in score and c not in context]
    return dict(full=sorted(feats),
                news2_only=sorted(set(score + context)),
                vitals_only=sorted(set(vitals + context)),
                vitals_deep=sorted(set(vitals + context)),
                _score=sorted(score), _vitals=sorted(vitals), _context=sorted(context))


def train_pooled(Xtr, ytr, Xval, yval, max_depth=4, rounds=2000):
    params = {"objective": "binary:logistic", "eval_metric": "auc", "tree_method": "hist",
              "learning_rate": 0.05, "max_depth": max_depth, "min_child_weight": 20,
              "subsample": 0.8, "colsample_bytree": 0.8, "reg_lambda": 2.0,
              "seed": config.RANDOM_SEED}
    ev = {}
    b = xgb.train(params, xgb.DMatrix(Xtr, label=ytr), num_boost_round=rounds,
                  evals=[(xgb.DMatrix(Xval, label=yval), "val")], evals_result=ev,
                  early_stopping_rounds=50, verbose_eval=False)
    return b, float(ev["val"]["auc"][b.best_iteration])


def run_config(df, feats, name, max_depth=4):
    """Pooled discrete-time hazard (cell B design) restricted to `feats`."""
    tr_i, cal_i, te_i = three_way_split(df)
    tr, cal, te = df.iloc[tr_i].copy(), df.iloc[cal_i].copy(), df.iloc[te_i].copy()
    pooled = feats + ["interval_j"]

    pp_tr = build_person_period_table(tr, config.HORIZONS_H)
    pp_cal = build_person_period_table(cal, config.HORIZONS_H)
    b, val_auc = train_pooled(pp_tr[pooled].astype(float).values,
                              pp_tr["py_label"].values.astype(float),
                              pp_cal[pooled].astype(float).values,
                              pp_cal["py_label"].values.astype(float),
                              max_depth=max_depth)

    calibrators = {}
    for j, h in enumerate(config.HORIZONS_H, start=1):
        s = pp_cal[pp_cal.interval_j == j]
        raw = b.predict(xgb.DMatrix(s[pooled].astype(float).values),
                        iteration_range=(0, b.best_iteration + 1))
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        iso.fit(raw, s["py_label"].values.astype(float))
        calibrators[h] = iso

    def assemble(d, split_name):
        X = d[feats].astype(float).values
        raw = np.column_stack([
            b.predict(xgb.DMatrix(np.column_stack([X, np.full(len(d), float(j))])),
                      iteration_range=(0, b.best_iteration + 1))
            for j in range(1, len(config.HORIZONS_H) + 1)])
        cal_h = np.clip(np.column_stack([calibrators[h].predict(raw[:, j])
                                         for j, h in enumerate(config.HORIZONS_H)]), 0.0, 1.0)
        S = reconstruct_survival(cal_h)
        assert (np.diff(S, axis=1) <= 1e-9).all()
        out = d[["stay_id", "subject_id", "anchor_time", "T_hours", "event"]].copy()
        out["split"] = split_name
        for j, h in enumerate(config.HORIZONS_H):
            out[f"p_calibrated_{h}h"] = 1.0 - S[:, j + 1]
        return out

    o_cal, o_te = assemble(cal, "calib"), assemble(te, "test")
    c_te = cindex(te["T_hours"].values, 1.0 - o_te["p_calibrated_24h"].values, te["event"].values)

    rows = []
    for h in config.HORIZONS_H:
        col = f"p_calibrated_{h}h"
        csub, cy = known_subset(o_cal, h)
        tsub, ty = known_subset(o_te, h)
        thr = ec.select_threshold(csub[col].values, cy, 0.80)
        row = ec.row_confusion(ty, tsub[col].values, thr)
        epm = ec.episode_metrics(tsub, col, thr, ty)
        br = float(np.mean(ty))
        rows.append(dict(config=name, horizon=h, n_features=len(feats), max_depth=max_depth,
                         c_index=c_te, base_rate=br,
                         auc=float(roc_auc_score(ty, tsub[col].values)),
                         auprc=float(average_precision_score(ty, tsub[col].values)),
                         row_sensitivity=row["sensitivity"], row_specificity=row["specificity"],
                         row_ppv=row["ppv"], row_lift=ec.lift(row["ppv"], br),
                         episode_ppv=epm["episode_ppv"], episode_lift=ec.lift(epm["episode_ppv"], br),
                         patient_recall=epm["patient_recall"],
                         episodes_per_patient_day=epm["episodes_per_patient_day"],
                         median_lead_time_h=epm["median_lead_time_h"]))
    log.info("%-12s  %2d feats  depth %d  best_iter %4d  pooled_val_auc %.4f  C-index %.4f",
             name, len(feats), max_depth, b.best_iteration, val_auc, c_te)
    return pd.DataFrame(rows), b, pooled


def main(horizons_to_print=(6, 12, 24)):
    df = pd.read_parquet(config.tpath("features.parquet"))
    feats = news2_feature_cols(df)
    ch = split_feature_channels(feats)
    log.info("channel split: %d NEWS2-score features, %d raw-vital features, %d context",
             len(ch["_score"]), len(ch["_vitals"]), len(ch["_context"]))
    log.info("  NEWS2-score features: %s", ch["_score"])
    log.info("  context features    : %s", ch["_context"])

    all_rows, gains = [], {}
    for name, depth in (("full", 4), ("news2_only", 4), ("vitals_only", 4), ("vitals_deep", 8)):
        tbl, booster, pooled = run_config(df, ch[name], name, max_depth=depth)
        all_rows.append(tbl)
        g = booster.get_score(importance_type="gain")
        ranked = sorted(g.items(), key=lambda kv: -kv[1])[:8]
        gains[name] = [(pooled[int(k[1:])], round(v, 1)) for k, v in ranked]

    out = pd.concat(all_rows, ignore_index=True)
    out.to_csv(config.dpath("feature_channel_ablation.csv"), index=False)

    print("\n" + "=" * 118)
    print("FEATURE-CHANNEL ABLATION — pooled discrete-time hazard, identical split/label/calibration")
    print("=" * 118)
    ci = out.drop_duplicates("config")[["config", "n_features", "max_depth", "c_index"]]
    print(f"  {'config':14} {'n_feats':>8} {'depth':>6} {'C-index':>9}")
    for r in ci.itertuples():
        print(f"  {r.config:14} {r.n_features:>8} {r.max_depth:>6} {r.c_index:>9.4f}")
    for h in horizons_to_print:
        s = out[out.horizon == h]
        print(f"\n  horizon {h}h   (base rate {s.base_rate.iloc[0]:.4f})")
        print(f"    {'config':14} {'AUC':>7} {'AUPRC':>7} {'sens':>7} {'spec':>7} "
              f"{'row-PPV':>8} {'ep-PPV':>8} {'ep-LIFT':>8} {'recall':>8} {'ep/day':>7}")
        for r in s.itertuples():
            print(f"    {r.config:14} {r.auc:>7.4f} {r.auprc:>7.4f} {r.row_sensitivity:>7.4f} "
                  f"{r.row_specificity:>7.4f} {r.row_ppv:>8.4f} {r.episode_ppv:>8.4f} "
                  f"{r.episode_lift:>8.3f} {r.patient_recall:>8.4f} {r.episodes_per_patient_day:>7.3f}")
    print("\n  TOP FEATURES BY GAIN, per configuration")
    for name, g in gains.items():
        print(f"    {name}:")
        for f, v in g:
            print(f"      {f:28} {v:>10.1f}")
    with open(config.dpath("feature_channel_ablation.json"), "w") as f:
        json.dump(dict(channels={k: v for k, v in ch.items() if k.startswith("_")},
                       gains=gains, table=out.to_dict("records")), f, indent=2, default=float)
    print("=" * 118 + "\n")
    log.info("wrote data/feature_channel_ablation.csv and .json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.parse_args()
    main()
