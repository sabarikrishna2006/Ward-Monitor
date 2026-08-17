"""
Stage 12 — Train the v1 discrete-time hazard model (conditional-hazard
parameterization, XGBoost per interval, isotonic-calibrated, monotonic by
construction). This supersedes the AFT median as the primary output: the
model's answer IS a calibrated per-horizon probability curve, not a workaround
derived from one (plan §3).

Cutpoints: config.HORIZONS_H = [2, 4, 6, 9, 12, 18, 24]  (c_0=0 implicit).

For each interval j spanning (c_{j-1}, c_j], one binary XGBoost classifier is
trained on the person-period subset of anchors still at risk and with a KNOWN
outcome for that interval (Shroff arXiv:1903.09795's masking idea, applied
per-interval): patients censored partway through interval j are excluded from
j and drop out of the risk set for all later intervals too (see
build_person_period_table docstring for the exact rule).

The survival curve is then a running product of per-interval (1 - calibrated
hazard) terms, so it is non-increasing BY CONSTRUCTION -- no post-hoc
monotonicity patch, unlike independently-trained cumulative-form ordinal
regression.

Outputs:
  data/preds_ordinal_news2.parquet   every anchor (train+calib+test), same
                                      column shape as preds_focused_news2.parquet
                                      so 10_focused_report.py works unchanged.
  data/models_ordinal_news2/*.json|pkl  per-interval boosters + calibrators + meta.json
Run: EWS_TAG=news2 py -3 12_ordinal_train.py
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
from sklearn.isotonic import IsotonicRegression

import config
from known_status import known_subset  # noqa: F401 (kept for parity with 09_focused_train.py-style modules)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ordinal_train")

# 03_train.py / 09_focused_train.py aren't valid identifiers (leading digit).
_t3 = importlib.import_module("03_train")
three_way_split = _t3.three_way_split
_t9 = importlib.import_module("09_focused_train")
news2_feature_cols, news2_ruler_time = _t9.news2_feature_cols, _t9.news2_ruler_time

# tpath, not dpath: with EWS_TAG=news2 this still resolves to "models_ordinal_news2"
# (byte-identical to the previous hardcoded value, so v1 artefacts are untouched),
# but an EWS_TAG=news2_v2lab run now writes to its own directory instead of
# silently overwriting the v1 models.
MODEL_DIR = config.tpath("models_ordinal")
os.makedirs(MODEL_DIR, exist_ok=True)
OUT_SUFFIX: str | None = None    # set by __main__ so preds/model dir stay in step

META = ["stay_id", "hadm_id", "subject_id", "anchor_time", "T_hours", "event",
        "cause", "dcm_flag", "news2_at_anchor"]


# ══════════════════════════════════════════════════════════════════════════
# person-period table construction (plan §3 -- the genuinely new logic)
# ══════════════════════════════════════════════════════════════════════════
def build_person_period_table(df: pd.DataFrame, horizons: list[float]) -> pd.DataFrame:
    """Expand each anchor row into one row per interval j it is AT RISK for and
    has a KNOWN outcome in, with a new `interval_j` (1-indexed) and `py_label`
    (0/1) column. Per interval j spanning (c_{j-1}, c_j]:

      at risk       iff T_hours > c_{j-1} (and still in the risk set from
                    earlier intervals -- see below)
      label=1       event=1 and c_{j-1} < T_hours <= c_j (fails here; patient
                    exits the risk set, contributes no further rows)
      label=0       event=1 and T_hours > c_j (survives this interval), OR
                    event=0 (censored) and T_hours >= c_j (survives this
                    interval, still censored later)
      excluded      event=0 (censored) and c_{j-1} < T_hours < c_j -- censored
                    PARTWAY through the interval, outcome unknown; dropped
                    from interval j and from every later interval too (Shroff's
                    masking idea, applied per-interval rather than per-cumulative
                    horizon).
    """
    cutpoints = [0.0] + [float(h) for h in horizons]
    T = df["T_hours"].to_numpy(dtype=float)
    event = df["event"].to_numpy().astype(bool)
    still_at_risk = np.ones(len(df), dtype=bool)
    frames = []
    for j in range(1, len(cutpoints)):
        c_prev, c_j = cutpoints[j - 1], cutpoints[j]
        at_risk = still_at_risk & (T > c_prev)
        if not at_risk.any():
            still_at_risk = at_risk
            continue
        idx = np.where(at_risk)[0]
        Tj, Ej = T[idx], event[idx]

        fails = Ej & (Tj <= c_j)
        survives_event = Ej & (Tj > c_j)
        survives_censor = (~Ej) & (Tj >= c_j)
        unknown = (~Ej) & (Tj < c_j)

        label = np.full(len(idx), np.nan)
        label[fails] = 1.0
        label[survives_event] = 0.0
        label[survives_censor] = 0.0

        keep = ~unknown
        sub = df.iloc[idx[keep]].copy()
        sub["interval_j"] = j
        sub["py_label"] = label[keep]
        frames.append(sub)

        exits = fails | unknown
        new_at_risk = at_risk.copy()
        new_at_risk[idx[exits]] = False
        still_at_risk = new_at_risk

    if not frames:
        empty = df.iloc[0:0].copy()
        empty["interval_j"] = pd.Series(dtype=int)
        empty["py_label"] = pd.Series(dtype=float)
        return empty
    return pd.concat(frames, ignore_index=True)


# ══════════════════════════════════════════════════════════════════════════
# per-interval classifier + calibration
# ══════════════════════════════════════════════════════════════════════════
#: overridable regularisation. Defaults reproduce the original v1 model exactly;
#: `--regularise` tightens them for the wide (multi-window) feature space, where the
#: train/test C-index gap grew from 0.0505 (55 features) to 0.0686 (371 features).
REG = dict(min_child_weight=20, colsample_bytree=0.8, reg_lambda=2.0,
           reg_alpha=0.0, subsample=0.8, max_depth=4)


def train_interval_classifier(Xtr, ytr, Xval, yval):
    dtr = xgb.DMatrix(Xtr, label=ytr)
    dval = xgb.DMatrix(Xval, label=yval)
    params = {
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "tree_method": "hist",
        "learning_rate": 0.05,
        "max_depth": REG["max_depth"],
        "min_child_weight": REG["min_child_weight"],
        "subsample": REG["subsample"],
        "colsample_bytree": REG["colsample_bytree"],
        "reg_lambda": REG["reg_lambda"],
        "reg_alpha": REG["reg_alpha"],
        "seed": config.RANDOM_SEED,
    }
    evals_result = {}
    booster = xgb.train(params, dtr, num_boost_round=600,
                        evals=[(dtr, "train"), (dval, "val")],
                        early_stopping_rounds=40, evals_result=evals_result, verbose_eval=False)
    val_auc = evals_result["val"]["auc"][booster.best_iteration]
    return booster, float(val_auc)


def predict_hazard(booster, X):
    return booster.predict(xgb.DMatrix(X), iteration_range=(0, booster.best_iteration + 1))


# ══════════════════════════════════════════════════════════════════════════
# survival-curve reconstruction (plan §3's exact formulas)
# ══════════════════════════════════════════════════════════════════════════
def reconstruct_survival(hazards: np.ndarray) -> np.ndarray:
    """hazards: (n, K) per-interval hazard (calibrated or raw). Returns S of
    shape (n, K+1): S[:,0]=1, S[:,j] = S[:,j-1] * (1 - hazards[:,j-1]).
    A running product of terms in [0,1] -- non-increasing BY CONSTRUCTION."""
    n, K = hazards.shape
    S = np.empty((n, K + 1), dtype=float)
    S[:, 0] = 1.0
    for j in range(1, K + 1):
        S[:, j] = S[:, j - 1] * (1.0 - hazards[:, j - 1])
    return S


def conditional_expected_time_24h(S: np.ndarray, cutpoints: list[float]) -> np.ndarray:
    """E[T | T<=24h] = sum_j midpoint_j * P(fail in interval j) / P(T<=24h)."""
    K = S.shape[1] - 1
    midpoints = np.array([(cutpoints[j - 1] + cutpoints[j]) / 2.0 for j in range(1, K + 1)])
    p_fail = S[:, :-1] - S[:, 1:]              # (n, K), P(fail in interval j)
    p_by_24h = 1.0 - S[:, -1]                   # P(T<=24h)
    num = (p_fail * midpoints[None, :]).sum(axis=1)
    return num / np.clip(p_by_24h, 1e-9, None)


def cindex(T, score_higher_is_longer, event):
    m = ~np.isnan(score_higher_is_longer)
    return concordance_index(T[m], score_higher_is_longer[m], event[m])


def cluster_bootstrap_cindex_ci(T, score, event, subject_ids, n_boot=500, seed=config.RANDOM_SEED):
    """Patient-clustered bootstrap 95% CI on the C-index (resample subject_ids
    WITH replacement, not rows -- so repeated-measures rows from one patient
    don't get treated as independent evidence; plan §4.1)."""
    rng = np.random.default_rng(seed)
    uniq = np.unique(subject_ids)
    idx_by_subj = {s: np.where(subject_ids == s)[0] for s in uniq}
    boots = []
    for _ in range(n_boot):
        samp_subj = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([idx_by_subj[s] for s in samp_subj])
        try:
            boots.append(cindex(T[idx], score[idx], event[idx]))
        except Exception:
            continue
    if not boots:
        return float("nan"), float("nan"), 0
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return float(lo), float(hi), len(boots)


#: columns that are labels, identifiers, or bookkeeping -- never features
NON_FEATURE_COLS = {
    "stay_id", "hadm_id", "subject_id", "anchor_time", "T_hours", "event", "cause",
    "event_rule", "escalation_group", "split",
}


def extended_feature_cols(df: pd.DataFrame) -> list[str]:
    """Every numeric column except identifiers/labels.

    Used with features_mw.parquet (built by 02b_build_features_ext.py) for the
    escalation target, where the NEWS2-prefix selector would silently discard the
    very features the target needs -- MAP, HCO3, anion gap, infusion titration.
    `dcm_flag` and `already_high_at_anchor` ARE kept: a DCM diagnosis and a currently
    high NEWS2 are legitimate predictors of escalation, and NEWS2 is not the event
    here so there is no circularity.
    """
    num = df.select_dtypes(include=[np.number, "bool"]).columns
    feats = sorted(c for c in num if c not in NON_FEATURE_COLS)
    leaky = [c for c in feats if any(t in c.lower() for t in (
        "peep", "tidal_volume", "norepinephrine", "dopamine", "phenylephrine",
        "dobutamine", "vasopressin", "epinephrine", "milrinone", "propofol",
        "fentanyl", "midazolam", "prbc", "packed_red"))]
    assert not leaky, f"target-leaking columns reached the feature list: {leaky}"
    return feats


def main(feature_file="features.parquet", feature_set="news2", allowlist=None):
    cutpoints = [0.0] + [float(h) for h in config.HORIZONS_H]
    df = pd.read_parquet(config.tpath(feature_file))
    if feature_set == "extended":
        feats = extended_feature_cols(df)
        if allowlist:
            spec = json.load(open(config.dpath(allowlist)))
            wanted = [c for c in spec["features"] if c in df.columns]
            missing = set(spec["features"]) - set(wanted)
            assert not missing, f"allowlist names columns absent from {feature_file}: {sorted(missing)[:5]}"
            log.info("PRUNED to %d of %d features via %s (retains %.1f%% of summed gain)",
                     len(wanted), len(feats), allowlist, 100 * spec.get("gain_retained", float("nan")))
            feats = wanted
        log.info("EXTENDED feature set: %d columns from %s "
                 "(MAP / HCO3 / anion gap / infusion titration / nurse-concern / "
                 "multi-window trends + crossovers)", len(feats), feature_file)
    else:
        feats = news2_feature_cols(df)
        log.info("ORDINAL feature set: %d columns (same focused NEWS2 family + hours_of_history)", len(feats))
    log.info("rows=%d  event_rate=%.3f  horizons=%s", len(df), df["event"].mean(), config.HORIZONS_H)

    tr_i, cal_i, te_i = three_way_split(df)     # patient-level split, ONCE, before person-period expansion
    tr, cal, te = df.iloc[tr_i].copy(), df.iloc[cal_i].copy(), df.iloc[te_i].copy()
    log.info("split: train=%d calib=%d test=%d (subjects %d/%d/%d)",
             len(tr), len(cal), len(te), tr.subject_id.nunique(),
             cal.subject_id.nunique(), te.subject_id.nunique())

    pp_tr = build_person_period_table(tr, config.HORIZONS_H)
    pp_cal = build_person_period_table(cal, config.HORIZONS_H)
    log.info("person-period rows: train=%d (from %d anchors) calib=%d (from %d anchors)",
             len(pp_tr), len(tr), len(pp_cal), len(cal))

    # ---- train + calibrate one classifier per interval ----
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

    # ---- apply to every anchor in every split (inference doesn't need person-period masking) ----
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
    suffix = OUT_SUFFIX if OUT_SUFFIX is not None else ("_mw" if feature_set == "extended" else "")
    preds.to_parquet(config.tpath(f"preds_ordinal{suffix}.parquet"), index=False)

    # ---- honesty check: train vs test C-index, hazard model vs the NEWS2 ruler ----
    # score = predicted S(24h) = P(survive past 24h); higher => longer survival, matching
    # concordance_index's "higher score = longer time" convention (same as AFT's pred_median).
    surv24_tr = 1.0 - out_tr["p_calibrated_24h"].values
    surv24_te = 1.0 - out_te["p_calibrated_24h"].values
    Ttr, Etr = tr["T_hours"].values, tr["event"].values
    Tte, Ete = te["T_hours"].values, te["event"].values

    c_haz_tr = cindex(Ttr, surv24_tr, Etr)
    c_haz_te = cindex(Tte, surv24_te, Ete)
    c_ruler_tr = cindex(Ttr, out_tr["ruler_time"].values, Etr)
    c_ruler_te = cindex(Tte, out_te["ruler_time"].values, Ete)
    ci_lo, ci_hi, n_boot_ok = cluster_bootstrap_cindex_ci(Tte, surv24_te, Ete, te["subject_id"].values)
    log.info("C-index  hazard  train=%.4f test=%.4f  (test 95%% CI [%.4f, %.4f], n_boot=%d, clustered by subject_id)",
             c_haz_tr, c_haz_te, ci_lo, ci_hi, n_boot_ok)
    log.info("C-index  ruler   train=%.4f test=%.4f", c_ruler_tr, c_ruler_te)
    if c_haz_te <= c_ruler_te:
        log.warning("*** hazard model does NOT beat the NEWS2-slope ruler on test C-index. "
                    "Report this plainly -- do not bury it. ***")
    gap = c_haz_tr - c_haz_te
    if gap > 0.05:
        log.warning("*** train/test C-index gap = %.4f > 0.05 -- possible overfit, investigate before reporting. ***", gap)

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
    )
    with open(os.path.join(MODEL_DIR, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    log.info("saved %d interval models + calibrators + preds_ordinal.parquet (%d rows total)",
             len(boosters), len(preds))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default="features.parquet",
                    help="feature parquet under the current EWS_TAG "
                         "(features.parquet or features_mw.parquet)")
    ap.add_argument("--feature-set", choices=["news2", "extended"], default="news2",
                    help="news2 = the 55 NEWS2-derived columns (prefix selector). "
                         "extended = every numeric column in the file, for the "
                         "escalation target where the prefix selector would discard "
                         "MAP / HCO3 / anion gap / infusions.")
    ap.add_argument("--feature-allowlist", default=None,
                    help="JSON from make_feature_allowlist.py; prunes the feature set")
    ap.add_argument("--regularise", action="store_true",
                    help="tighten regularisation for the wide feature space "
                         "(min_child_weight 20->60, colsample 0.8->0.5, "
                         "reg_lambda 2->10, reg_alpha 0->1)")
    ap.add_argument("--suffix", default=None,
                    help="output suffix, e.g. _mwp for the pruned model")
    a = ap.parse_args()
    if a.regularise:
        REG.update(min_child_weight=60, colsample_bytree=0.5,
                   reg_lambda=10.0, reg_alpha=1.0)
    sfx = a.suffix if a.suffix is not None else ("_mw" if a.feature_set == "extended" else "")
    OUT_SUFFIX = sfx
    MODEL_DIR = config.tpath(f"models_ordinal{sfx}")
    os.makedirs(MODEL_DIR, exist_ok=True)
    main(feature_file=a.features, feature_set=a.feature_set, allowlist=a.feature_allowlist)
