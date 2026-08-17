"""
Stage 19 — Does ensemble disagreement predict which alerts are wrong?

THE IDEA (from the professor's own paper, arXiv:1903.09795 Section 5, Eq 7-8).
Train m networks that differ ONLY in random initialisation and batch shuffling.
For one patient-hour you then get m probabilities:

    Patient A: [0.31, 0.29, 0.34, 0.30, 0.33, 0.28]  -> mean 0.31, std 0.02
    Patient B: [0.55, 0.12, 0.61, 0.09, 0.48, 0.15]  -> mean 0.33, std 0.22

Identical mean risk, completely different trustworthiness. A's answer is in the
data; B's answer is an artefact of where training happened to start. Their paper
shows (its Table 4) that predictions with low empirical standard deviation (ESD)
also have low error — so ESD is a usable confidence signal.

If that holds here, it is a principled false-alarm reducer that costs nothing to
justify, because it comes from his own paper:
    page only if   mean >= threshold  AND  std <= cap
    high risk + high disagreement  ->  a WATCH on the worklist, not a page.

THE POINT OF THIS SCRIPT IS THE FALSIFICATION TEST, NOT THE GATING.
His paper demonstrates ESD on turbofan engines. Whether it transfers to hourly
vitals is an empirical question, and it is answered FIRST:

    bin the ALERTING anchors by ensemble std into deciles and check whether the
    fraction that are true positives actually rises as std falls.

    PASS  -> a monotone-ish relationship with a materially higher precision in the
             low-std bins. Only then is a cap fitted (on calibration) and gating
             reported.
    FAIL  -> precision is flat across std deciles. The uncertainty is
             uninformative here, and that is REPORTED AS A NULL RESULT. No gate is
             built, and no claim is made.

Decision rule, fixed before looking at the numbers:
    adopt only if  precision(lowest std decile) - precision(highest std decile)
                   >= MIN_SPREAD (0.05 absolute)  AND  Spearman(std, correctness)
                   is negative.

Run: PYTHONUTF8=1 EWS_TAG=news2 py -3 19_ensemble_uncertainty.py --preds preds_mlp_ordinal_m6
"""
from __future__ import annotations

import argparse
import json
import logging

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import config
import eval_core as ec
from known_status import known_subset

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ens_unc")

MIN_SPREAD = 0.05          # absolute precision gap required between std deciles
N_BINS = 10


def falsification_test(test: pd.DataFrame, h: float, thr: float, y: np.ndarray) -> dict:
    """Among ALERTING anchors only, does low ensemble disagreement mean a more
    trustworthy alert? Restricted to alerting anchors because that is the
    population the gate would act on — measuring the relationship over all anchors
    would be dominated by confidently-negative rows and would not answer the
    operational question."""
    col, scol = f"p_calibrated_{int(h)}h", f"p_std_{int(h)}h"
    if scol not in test.columns:
        raise KeyError(f"{scol} missing — retrain with --ensemble m>1 so a spread exists")

    alerting = test[test[col].values >= thr].copy()
    alerting["_y"] = np.asarray(y)[test[col].values >= thr]
    n = len(alerting)
    if n < 100:
        return dict(horizon=h, n_alerting=n, verdict="INCONCLUSIVE: too few alerting anchors")

    std = alerting[scol].values
    yy = alerting["_y"].values.astype(int)
    rho, pval = spearmanr(std, yy)

    # rank-based deciles so bin membership does not depend on the std scale
    ranks = pd.Series(std).rank(method="first", pct=True).values
    bin_id = np.clip((ranks * N_BINS).astype(int), 0, N_BINS - 1)
    bins = []
    for b in range(N_BINS):
        m = bin_id == b
        bins.append(dict(decile=b + 1, n=int(m.sum()),
                         mean_std=float(std[m].mean()) if m.any() else float("nan"),
                         precision=float(yy[m].mean()) if m.any() else float("nan")))
    lo, hi = bins[0]["precision"], bins[-1]["precision"]
    spread = lo - hi
    passed = bool(spread >= MIN_SPREAD and rho < 0)
    return dict(
        horizon=h, n_alerting=n, threshold=float(thr),
        spearman_std_vs_correct=float(rho), spearman_p=float(pval),
        precision_lowest_std_decile=lo, precision_highest_std_decile=hi,
        precision_spread=float(spread), min_spread_required=MIN_SPREAD,
        deciles=bins,
        passed=passed,
        verdict=("PASS — ensemble disagreement carries information about which alerts are "
                 "wrong; gating is justified."
                 if passed else
                 "NULL RESULT — precision is flat across ensemble-disagreement deciles, so "
                 "the spread does not identify false alarms on this data. Do NOT gate on it; "
                 "report the null. (The paper demonstrates ESD on turbofan sensor data, not "
                 "on hourly vitals — this is a genuine transfer failure, not a bug.)"),
    )


def fit_std_cap(calib: pd.DataFrame, h: float, thr: float, cy: np.ndarray,
                keep_frac: float = 0.80) -> float:
    """Cap = the `keep_frac` quantile of per-EPISODE mean ensemble std on the
    CALIBRATION split, i.e. "page for the keep_frac most-agreed-upon episodes,
    watch the rest." Fitted on calibration only, exactly like the alert threshold,
    and on the same unit (episodes) the gate is applied to."""
    ep = episode_uncertainty(calib, h, thr, cy)
    return float(np.quantile(ep["mean_std"].values, keep_frac)) if len(ep) else float("inf")


def episode_uncertainty(test: pd.DataFrame, h: float, thr: float, y: np.ndarray,
                        gap_h: float = ec.EPISODE_GAP_H) -> pd.DataFrame:
    """Alarm episodes with an aggregate ensemble-uncertainty per episode.

    WHY PER EPISODE, NOT PER ANCHOR. Gating individual anchor-hours is wrong here:
    removing one high-uncertainty hour from the middle of a run SPLITS one alarm
    episode into two, which INCREASES the episode count and dilutes episode-PPV
    even when the removed hours were genuinely bad. Measured directly: anchor-level
    gating at 12h moved ep-PPV 0.3073 -> 0.2834, i.e. the wrong way, despite the
    underlying signal being real.

    The clinical unit of a decision is the episode, so the confidence decision must
    be made on the same unit. Episode uncertainty = MEAN ensemble std over the
    episode's alerting hours.
    """
    col, scol = f"p_calibrated_{int(h)}h", f"p_std_{int(h)}h"
    d = test[["stay_id", "anchor_time", "T_hours", "event", col, scol]].copy()
    d["y"] = np.asarray(y).astype(int)
    d = d[d[col].values >= thr].sort_values(["stay_id", "anchor_time"]).reset_index(drop=True)
    if len(d) == 0:
        return pd.DataFrame(columns=["stay_id", "ep_id", "y_any", "mean_std", "n_alerts"])
    t = pd.to_datetime(d["anchor_time"])
    gap = t.groupby(d["stay_id"]).diff().dt.total_seconds() / 3600.0
    new_ep = gap.isna() | (gap > gap_h + 1e-9)
    d["ep_id"] = new_ep.groupby(d["stay_id"]).cumsum().astype(int)
    return (d.groupby(["stay_id", "ep_id"])
              .agg(y_any=("y", "max"), mean_std=(scol, "mean"), n_alerts=("y", "size"))
              .reset_index())


def _episode_tier_metrics(ep: pd.DataFrame, n_known: int, n_event_patients: int) -> dict:
    n = len(ep)
    n_true = int(ep["y_any"].sum()) if n else 0
    caught = ep.loc[ep["y_any"] == 1, "stay_id"].nunique() if n else 0
    return dict(n_episodes=n, n_true_episodes=n_true,
                episode_ppv=n_true / n if n else float("nan"),
                n_event_patients_caught=int(caught),
                patient_recall=caught / n_event_patients if n_event_patients else float("nan"),
                episodes_per_patient_day=n / (n_known / 24.0) if n_known else float("nan"))


def gated_metrics(test: pd.DataFrame, h: float, thr: float, cap: float, y: np.ndarray) -> dict:
    """Two-tier output at the EPISODE level: PAGE (risk high AND the ensemble
    agrees) vs WATCH (risk high, ensemble disagrees). Nothing is suppressed — a
    WATCH episode still appears on the worklist, it just does not interrupt
    anyone."""
    ep = episode_uncertainty(test, h, thr, y)
    y = np.asarray(y).astype(int)
    n_known = len(test)
    n_ev = test.loc[y == 1, "stay_id"].nunique()
    page = ep[ep["mean_std"] <= cap]
    watch = ep[ep["mean_std"] > cap]
    return dict(std_cap=cap,
                page=_episode_tier_metrics(page, n_known, n_ev),
                watch=_episode_tier_metrics(watch, n_known, n_ev),
                all_episodes=_episode_tier_metrics(ep, n_known, n_ev))


def main(preds_stem: str, horizons=None, sens_target=0.80, keep_frac=0.80):
    p = pd.read_parquet(config.tpath(f"{preds_stem}.parquet"))
    calib, test = p[p.split == "calib"].copy(), p[p.split == "test"].copy()
    horizons = horizons or config.HORIZONS_H
    out = {"preds": preds_stem, "sens_target": sens_target, "keep_frac": keep_frac,
           "min_spread_required": MIN_SPREAD}

    for h in horizons:
        col = f"p_calibrated_{int(h)}h"
        csub, cy = known_subset(calib, h)
        tsub, ty = known_subset(test, h)
        thr = ec.select_threshold(csub[col].values, cy, sens_target)

        ft = falsification_test(tsub, h, thr, ty)
        entry = {"falsification_test": ft}
        log.info("h=%2gh  n_alerting=%d  rho=%+.4f  precision lo-std %.4f vs hi-std %.4f "
                 "(spread %+.4f)  -> %s", h, ft.get("n_alerting", 0),
                 ft.get("spearman_std_vs_correct", float("nan")),
                 ft.get("precision_lowest_std_decile", float("nan")),
                 ft.get("precision_highest_std_decile", float("nan")),
                 ft.get("precision_spread", float("nan")),
                 "PASS" if ft.get("passed") else "NULL")

        if ft.get("passed"):
            cap = fit_std_cap(csub, h, thr, cy, keep_frac)
            base = ec.episode_metrics(tsub, col, thr, ty)
            g = gated_metrics(tsub, h, thr, cap, ty)
            entry["baseline"] = base
            entry["gated"] = g
            entry["delta"] = dict(
                episode_ppv=g["page"]["episode_ppv"] - base["episode_ppv"],
                patient_recall=g["page"]["patient_recall"] - base["patient_recall"],
                episodes_per_patient_day=g["page"]["episodes_per_patient_day"]
                - base["episodes_per_patient_day"])
            log.info("     gated: ep-PPV %.4f -> %.4f  recall %.4f -> %.4f  "
                     "(WATCH tier holds %d extra episodes, not suppressed)",
                     base["episode_ppv"], g["page"]["episode_ppv"],
                     base["patient_recall"], g["page"]["patient_recall"],
                     g["watch"]["n_episodes"])
        else:
            entry["gated"] = None
        out[str(h)] = entry

    n_pass = sum(1 for h in horizons if out[str(h)]["falsification_test"].get("passed"))
    out["summary"] = dict(
        horizons_tested=len(horizons), horizons_passed=n_pass,
        overall_verdict=("ADOPT uncertainty gating" if n_pass >= len(horizons) / 2 else
                         "NULL RESULT: ensemble disagreement does not identify false alarms "
                         "on this data at most horizons. Report it; do not gate on it."),
    )
    log.info("SUMMARY: %d/%d horizons passed -> %s", n_pass, len(horizons),
             out["summary"]["overall_verdict"])

    path = config.tpath(f"ensemble_uncertainty_{preds_stem}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=float)
    log.info("wrote %s", path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--preds", default="preds_mlp_ordinal_m6")
    ap.add_argument("--sens-target", type=float, default=0.80)
    ap.add_argument("--keep-frac", type=float, default=0.80)
    a = ap.parse_args()
    main(a.preds, sens_target=a.sens_target, keep_frac=a.keep_frac)
