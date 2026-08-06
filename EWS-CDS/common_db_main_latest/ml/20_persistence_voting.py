"""
Stage 20 — Alert-rule search: TEMPORAL persistence (k-of-m over time) and the
professor's INTERVAL voting, both measured rather than assumed.

────────────────────────────────────────────────────────────────────────────
PART 1 — Why interval voting is (almost entirely) a no-op, proved not asserted
────────────────────────────────────────────────────────────────────────────
The suggestion was: "if any interval predicts deterioration, treat the patient as
positive", or a majority / 3-of-6 rule across the seven interval outputs.

The seven outputs of this model are CUMULATIVE probabilities, and they are
non-decreasing by construction:
        P(T<=2h) <= P(T<=4h) <= ... <= P(T<=24h)
because S(c_j) = S(c_{j-1})(1-h_j) is a running product of terms in [0,1].

Consequence, with a COMMON threshold tau:
        OR_j [ P_j >= tau ]   ==   [ P_24h >= tau ]        (exactly, always)
        AND_j[ P_j >= tau ]   ==   [ P_2h  >= tau ]        (exactly, always)
        (k-of-7 with a common tau) == [ P_{(8-k)th horizon} >= tau ]
i.e. every voting rule collapses to picking ONE horizon. There is no extra
information in the vote. `prove_interval_voting_is_redundant()` asserts this
numerically on the real predictions.

With PER-HORIZON thresholds (each fitted to 80% sensitivity at its own horizon)
the collapse is no longer exact, so that variant is MEASURED instead of dismissed.

────────────────────────────────────────────────────────────────────────────
PART 2 — Temporal persistence: the version of the idea that carries information
────────────────────────────────────────────────────────────────────────────
Alert only if the score has been above threshold in at least k of the last m
HOURS. Successive hours are genuinely different observations, so unlike the
interval vote this is not redundant.

Mechanism: a single artefactual reading (one bad cuff, one motion-corrupted SpO2)
raises NEWS2 for exactly one hour and cannot survive a k-of-m rule.

Cost, which must be reported every time the benefit is: persistence delays the
first alert, so it spends DETECTION LEAD TIME to buy precision.

Selection protocol, fixed BEFORE looking at test:
    * sweep m in {2,3,4,6}, k in {2..m}
    * evaluate on the CALIBRATION split only
    * choose the rule maximising episode-PPV SUBJECT TO patient recall >= floor
      (default 0.90; the unconstrained recall is ~0.96, so this is an explicit,
      bounded budget of recall we are willing to spend)
    * freeze it, apply once to test, report PPV gained / recall lost / delay added

KILL SWITCH: if no (k,m) clears the recall floor with a meaningful PPV gain, that
is reported as a null result and the rule is not adopted.

Run: PYTHONUTF8=1 EWS_TAG=news2 py -3 20_persistence_voting.py --preds preds_ordinal
"""
from __future__ import annotations

import argparse
import json
import logging

import numpy as np
import pandas as pd

import config
import eval_core as ec
from known_status import known_subset

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("persistence")

RECALL_FLOOR = 0.90
GRID = [(k, m) for m in (2, 3, 4, 6) for k in range(2, m + 1)]


# ══════════════════════════════════════════════════════════════════════════
def prove_interval_voting_is_redundant(df: pd.DataFrame, tau: float = 0.15) -> dict:
    """Assert, on the real predictions, that a common-threshold vote across the
    seven cumulative horizons is identical to thresholding a single horizon."""
    P = np.column_stack([df[f"p_calibrated_{h}h"].values for h in config.HORIZONS_H])
    max_viol = float(np.min(np.diff(P, axis=1)))
    assert max_viol >= -1e-9, f"cumulative probabilities are not non-decreasing ({max_viol})"

    above = P >= tau
    any_fires = above.any(axis=1)
    all_fires = above.all(axis=1)
    agree_or = float((any_fires == above[:, -1]).mean())
    agree_and = float((all_fires == above[:, 0]).mean())
    kof7 = {}
    for k in range(1, len(config.HORIZONS_H) + 1):
        vote = above.sum(axis=1) >= k
        equiv_idx = len(config.HORIZONS_H) - k          # k-of-7 == the (8-k)-th horizon
        kof7[k] = dict(equivalent_horizon_h=config.HORIZONS_H[equiv_idx],
                       agreement=float((vote == above[:, equiv_idx]).mean()))
    assert agree_or == 1.0 and agree_and == 1.0, "voting collapse failed — check monotonicity"
    return dict(tau=tau, n_rows=len(df),
                or_vote_equals_24h_horizon=agree_or,
                and_vote_equals_2h_horizon=agree_and,
                k_of_7_equivalences=kof7,
                conclusion=("With a common threshold every k-of-7 vote across the cumulative "
                            "horizons is EXACTLY equivalent to thresholding one horizon "
                            "(agreement 1.000). The vote adds no information."))


def interval_vote_with_own_thresholds(calib, test, sens_target=0.80) -> dict:
    """The one non-degenerate reading of the interval-vote idea: each horizon gets
    its OWN 80%-sensitivity threshold (fitted on calib), then vote. Because the
    thresholds differ, this no longer collapses exactly — so it is measured."""
    thr, cols = {}, {}
    for h in config.HORIZONS_H:
        col = f"p_calibrated_{h}h"
        csub, cy = known_subset(calib, h)
        thr[h] = ec.select_threshold(csub[col].values, cy, sens_target)
        cols[h] = col
    h_ref = config.PRIMARY_HORIZON if hasattr(config, "PRIMARY_HORIZON") else 12
    tsub, ty = known_subset(test, h_ref)
    above = np.column_stack([tsub[cols[h]].values >= thr[h] for h in config.HORIZONS_H])
    out = {}
    for k in range(1, len(config.HORIZONS_H) + 1):
        vote = above.sum(axis=1) >= k
        d = tsub.copy(); d["_vote"] = vote.astype(float)
        m = ec.episode_metrics(d, "_vote", 0.5, ty)
        out[f"{k}_of_7"] = dict(episode_ppv=m["episode_ppv"], patient_recall=m["patient_recall"],
                                n_episodes=m["n_episodes"],
                                episodes_per_patient_day=m["episodes_per_patient_day"])
    single = ec.evaluate_horizon(calib, test, h_ref)
    out["single_horizon_reference"] = dict(
        horizon=h_ref, episode_ppv=single["episode"]["episode_ppv"],
        patient_recall=single["episode"]["patient_recall"],
        n_episodes=single["episode"]["n_episodes"],
        episodes_per_patient_day=single["episode"]["episodes_per_patient_day"])
    return out


# ══════════════════════════════════════════════════════════════════════════
def apply_persistence(df: pd.DataFrame, col: str, thr: float, k: int, m: int) -> np.ndarray:
    """Persistent-alert indicator: score was above `thr` in >= k of the last `m`
    HOURS (a trailing time window, not a row window -- so a charting gap cannot
    silently satisfy the rule with stale observations).

    pandas' offset window `(t-m, t]` contains exactly m points on an hourly grid.
    """
    d = df[["stay_id", "anchor_time"]].copy()
    d["above"] = (df[col].values >= thr).astype(float)
    d["anchor_time"] = pd.to_datetime(d["anchor_time"])
    d = d.sort_values(["stay_id", "anchor_time"])
    cnt = (d.set_index("anchor_time").groupby("stay_id")["above"]
             .rolling(f"{int(m)}h").sum().reset_index(level=0, drop=True))
    d["cnt"] = cnt.values
    return d["cnt"].reindex(d.index).ge(k).reindex(df.index).fillna(False).to_numpy()


def _persistence_metrics(sub, col, thr, y, k, m):
    d = sub.copy()
    d = d.sort_values(["stay_id", "anchor_time"])
    order = d.index
    yy = pd.Series(y, index=sub.index).loc[order].to_numpy()
    d["_alert"] = apply_persistence(d, col, thr, k, m).astype(float)
    return ec.episode_metrics(d, "_alert", 0.5, yy)


def sweep_persistence(calib, test, h, sens_target=0.80, recall_floor=RECALL_FLOOR) -> dict:
    col = f"p_calibrated_{h}h"
    csub, cy = known_subset(calib, h)
    tsub, ty = known_subset(test, h)
    thr = ec.select_threshold(csub[col].values, cy, sens_target)

    base_cal = ec.episode_metrics(csub, col, thr, cy)
    base_te = ec.episode_metrics(tsub, col, thr, ty)

    rows = []
    for (k, m) in GRID:
        mc = _persistence_metrics(csub, col, thr, cy, k, m)
        rows.append(dict(k=k, m=m, episode_ppv=mc["episode_ppv"],
                         patient_recall=mc["patient_recall"],
                         n_episodes=mc["n_episodes"],
                         episodes_per_patient_day=mc["episodes_per_patient_day"],
                         median_lead_time_h=mc["median_lead_time_h"]))
    cal_tbl = pd.DataFrame(rows)

    eligible = cal_tbl[cal_tbl["patient_recall"] >= recall_floor]
    if len(eligible) == 0:
        return dict(horizon=h, threshold=thr, selected=None,
                    calib_sweep=cal_tbl.to_dict("records"),
                    baseline_calib=base_cal, baseline_test=base_te,
                    verdict=f"NULL RESULT: no (k,m) kept patient recall >= {recall_floor}")
    best = eligible.sort_values("episode_ppv", ascending=False).iloc[0]
    k, m = int(best["k"]), int(best["m"])
    te = _persistence_metrics(tsub, col, thr, ty, k, m)

    gained = te["episode_ppv"] - base_te["episode_ppv"]
    lost = base_te["patient_recall"] - te["patient_recall"]
    delay = base_te["median_lead_time_h"] - te["median_lead_time_h"]
    return dict(
        horizon=h, threshold=thr, recall_floor=recall_floor,
        selected=dict(k=k, m=m, selected_on="calibration split"),
        calib_sweep=cal_tbl.to_dict("records"),
        baseline_test=base_te, persistent_test=te,
        ppv_gained=float(gained), recall_lost=float(lost), lead_time_lost_h=float(delay),
        verdict=("ADOPT" if gained > 0.01 and lost <= (base_te["patient_recall"] - recall_floor)
                 else "NULL RESULT: gain too small or recall cost too high"),
    )


def main(preds_stem: str, horizons=None, sens_target=0.80, recall_floor=RECALL_FLOOR):
    p = pd.read_parquet(config.tpath(f"{preds_stem}.parquet"))
    calib, test = p[p.split == "calib"].copy(), p[p.split == "test"].copy()
    horizons = horizons or config.HORIZONS_H
    out = {"preds": preds_stem, "sens_target": sens_target, "recall_floor": recall_floor}

    log.info("PART 1 — proving interval voting is redundant…")
    out["interval_voting_redundancy_proof"] = prove_interval_voting_is_redundant(test)
    log.info("  OR-vote == 24h horizon: agreement %.4f (proved)",
             out["interval_voting_redundancy_proof"]["or_vote_equals_24h_horizon"])
    out["interval_voting_own_thresholds"] = interval_vote_with_own_thresholds(calib, test, sens_target)

    log.info("PART 2 — temporal persistence sweep…")
    out["persistence"] = {}
    for h in horizons:
        r = sweep_persistence(calib, test, h, sens_target, recall_floor)
        out["persistence"][str(h)] = r
        if r.get("selected"):
            log.info("  h=%2gh  best (k=%d of m=%dh)  ep-PPV %.4f -> %.4f (+%.4f)  "
                     "recall %.4f -> %.4f (-%.4f)  lead %.1fh -> %.1fh  [%s]",
                     h, r["selected"]["k"], r["selected"]["m"],
                     r["baseline_test"]["episode_ppv"], r["persistent_test"]["episode_ppv"],
                     r["ppv_gained"], r["baseline_test"]["patient_recall"],
                     r["persistent_test"]["patient_recall"], r["recall_lost"],
                     r["baseline_test"]["median_lead_time_h"],
                     r["persistent_test"]["median_lead_time_h"], r["verdict"])
        else:
            log.info("  h=%2gh  %s", h, r["verdict"])

    path = config.tpath(f"persistence_voting_{preds_stem}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=float)
    log.info("wrote %s", path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--preds", default="preds_ordinal",
                    help="parquet stem under the current EWS_TAG, e.g. preds_ordinal, "
                         "preds_pooled_xgb, preds_mlp_ordinal")
    ap.add_argument("--sens-target", type=float, default=0.80)
    ap.add_argument("--recall-floor", type=float, default=RECALL_FLOOR)
    a = ap.parse_args()
    main(a.preds, sens_target=a.sens_target, recall_floor=a.recall_floor)
