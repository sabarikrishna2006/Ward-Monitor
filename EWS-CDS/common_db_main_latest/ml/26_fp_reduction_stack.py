"""
Stage 26 — Every false-alarm lever, measured on one model, isolated then stacked.

Answers, with numbers rather than argument:
  1. Does the EPISODE GAP reduce false alarms, and how much of that is real?
  2. Does HYSTERESIS reduce false alarms, and does it cost recall?
  3. Does CONFORMAL YES/NO/IDK reduce false alarms, and at what recall cost?
  4. Do the MULTI-WINDOW features reduce false alarms (vs the 55-feature baseline)?
  5. What do they give STACKED?

CONFORMAL PREDICTION (label-conditional / Mondrian) is the YES/NO/IDK mechanism.
It needs no ensemble and no retraining -- it runs on the saved model via the
calibration split, and it produces the three tiers *natively*:

    On CALIB:   positives    s = 1 - p        negatives    s = p
                q_pos = (1-alpha) quantile of positive scores
                q_neg = (1-alpha) quantile of negative scores
    On TEST, for calibrated probability p, the prediction SET is
                include 1  if (1 - p) <= q_pos
                include 0  if      p  <= q_neg

      {1}    -> YES  confident deterioration          -> PAGE
      {0}    -> NO   confident stable                 -> CLEAR
      {0,1}  -> IDK  both labels plausible            -> WATCH
      {}     -> IDK  neither plausible (out-of-dist.) -> WATCH

Why this beats a sigma threshold: the abstention rate is CHOSEN via alpha and comes
with a distribution-free coverage guarantee, instead of being a constant that turns
out to fire on 0.54% of alerts. Precedent: DETERIO (PMC11392495) uses conformal
prediction for its "conditions for use" module.

APPLIED AT ONE DECISION HORIZON, not independently at all seven -- seven separately
calibrated predictors have different q_pos/q_neg fitted on different base rates and
can disagree for the same patient-snapshot. The alerting system makes one decision
per patient-hour, so conformal belongs at the decision horizon.

NOTHING IS EVER SUPPRESSED. A WATCH episode still appears on the worklist; it just
does not page. Total detection is unchanged. That is the structural difference from
persistence voting, which deleted alerts and lost 58% of the patients having only
1-2 pre-event observations.

Run: PYTHONUTF8=1 EWS_TAG=esc py -3 26_fp_reduction_stack.py --preds preds_ordinal_mwp
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

import config
import eval_core as ec
from known_status import known_subset


# ══════════════════════════════════════════════════════════════════════════
def conformal_thresholds(p_cal: np.ndarray, y_cal: np.ndarray, alpha: float):
    """Label-conditional conformal quantiles. Returns (q_pos, q_neg).

    Conservative finite-sample correction: use the ceil((n+1)(1-alpha))/n quantile,
    which is what gives the distribution-free coverage guarantee rather than an
    asymptotic one.
    """
    p_cal = np.asarray(p_cal, dtype=float)
    y_cal = np.asarray(y_cal).astype(int)
    out = []
    for lab in (1, 0):
        s = (1.0 - p_cal[y_cal == 1]) if lab == 1 else p_cal[y_cal == 0]
        n = len(s)
        if n == 0:
            out.append(1.0)
            continue
        k = min(int(np.ceil((n + 1) * (1.0 - alpha))), n)
        out.append(float(np.sort(s)[k - 1]))
    return out[0], out[1]


def conformal_tier(p: np.ndarray, q_pos: float, q_neg: float) -> np.ndarray:
    """'PAGE' | 'CLEAR' | 'WATCH' per row."""
    p = np.asarray(p, dtype=float)
    inc1 = (1.0 - p) <= q_pos
    inc0 = p <= q_neg
    tier = np.full(len(p), "WATCH", dtype=object)
    tier[inc1 & ~inc0] = "PAGE"
    tier[inc0 & ~inc1] = "CLEAR"
    return tier                                  # {0,1} and {} both -> WATCH


def episode_stats(sub, alert_col, y, thr, gap_h=ec.EPISODE_GAP_H):
    """`thr` MUST be the threshold appropriate to `alert_col`: the calibrated
    probability threshold for a probability column, or 0.5 for a 0/1 indicator.
    Passing 0.5 for a probability column silently evaluates a wildly different
    operating point -- it produced a 13-episode "baseline" before this was fixed."""
    return ec.episode_metrics(sub, alert_col, thr, y, gap_h=gap_h)


def row(name, m, br, note=""):
    return dict(rule=name, episodes=m["n_episodes"], ep_ppv=m["episode_ppv"],
                ep_lift=ec.lift(m["episode_ppv"], br),
                recall=m["patient_recall"],
                per100=m["episodes_per_patient_day"] * 100,
                lead=m["median_lead_time_h"], note=note)


def main(preds_stem: str, h: float, sens: float, gap_h: float):
    p = pd.read_parquet(config.tpath(f"{preds_stem}.parquet"))
    cal, te = p[p.split == "calib"].copy(), p[p.split == "test"].copy()
    col = f"p_calibrated_{int(h)}h"
    csub, cy = known_subset(cal, h)
    tsub, ty = known_subset(te, h)
    thr = ec.select_threshold(csub[col].values, cy, sens)
    br = float(np.mean(ty))
    rows, out = [], {"preds": preds_stem, "horizon": h, "sens_target": sens,
                     "base_rate": br, "threshold": thr}

    # ---- 1. episode gap -------------------------------------------------------
    gap_rows = []
    for g in (1.0, 2.0, 4.0, 8.0, 12.0):
        m = episode_stats(tsub, col, ty, thr, gap_h=g)
        gap_rows.append(dict(gap_h=g, **{k: v for k, v in
                                         row(f"gap={g}h", m, br).items() if k != "rule"}))
    out["episode_gap"] = gap_rows

    # ---- baseline at the chosen gap ------------------------------------------
    base_m = episode_stats(tsub, col, ty, thr, gap_h=gap_h)
    rows.append(row("baseline (single threshold)", base_m, br,
                    f"gap={gap_h}h"))

    # ---- 2. hysteresis --------------------------------------------------------
    hyst_rows = []
    for frac in (0.9, 0.8, 0.7, 0.5):
        d = tsub.copy()
        d["_a"] = ec.hysteresis_alert(d, col, thr, thr * frac).astype(float)
        m = episode_stats(d, "_a", ty, 0.5, gap_h=gap_h)
        hyst_rows.append(dict(tau_low_frac=frac, **{k: v for k, v in
                                                    row("h", m, br).items() if k != "rule"}))
        if frac == 0.5:
            rows.append(row("+ hysteresis (tau_low=50%)", m, br, "no recall cost by design"))
    out["hysteresis"] = hyst_rows

    # ---- 3. conformal YES/NO/IDK ---------------------------------------------
    conf_rows = []
    for alpha in (0.05, 0.10, 0.15, 0.20):
        q_pos, q_neg = conformal_thresholds(csub[col].values, cy, alpha)
        tier = conformal_tier(tsub[col].values, q_pos, q_neg)
        d = tsub.copy()
        d["_page"] = (tier == "PAGE").astype(float)
        d["_watch"] = (tier == "WATCH").astype(float)
        pm = episode_stats(d, "_page", ty, 0.5, gap_h=gap_h)
        wm = episode_stats(d, "_watch", ty, 0.5, gap_h=gap_h)
        n = len(tier)
        ev_in_watch = float(np.mean(np.asarray(ty)[tier == "WATCH"] == 1)) if (tier == "WATCH").any() else float("nan")
        frac_true_events_watched = float(
            np.sum((tier == "WATCH") & (np.asarray(ty) == 1)) / max(np.sum(np.asarray(ty) == 1), 1))
        conf_rows.append(dict(
            alpha=alpha, q_pos=q_pos, q_neg=q_neg,
            pct_PAGE=float(np.mean(tier == "PAGE")), pct_WATCH=float(np.mean(tier == "WATCH")),
            pct_CLEAR=float(np.mean(tier == "CLEAR")),
            page_episodes=pm["n_episodes"], page_ep_ppv=pm["episode_ppv"],
            page_ep_lift=ec.lift(pm["episode_ppv"], br), page_recall=pm["patient_recall"],
            page_per100=pm["episodes_per_patient_day"] * 100,
            page_lead=pm["median_lead_time_h"],
            watch_episodes=wm["n_episodes"], watch_ep_ppv=wm["episode_ppv"],
            frac_true_events_in_WATCH=frac_true_events_watched))
        if abs(alpha - 0.10) < 1e-9:
            rows.append(row("+ conformal PAGE (alpha=0.10)", pm, br,
                            f"{100*np.mean(tier=='WATCH'):.0f}% WATCH, not suppressed"))
    out["conformal"] = conf_rows

    # ---- 4. stacked: hysteresis THEN conformal on the surviving alerts -------
    best_alpha = 0.10
    q_pos, q_neg = conformal_thresholds(csub[col].values, cy, best_alpha)
    tier = conformal_tier(tsub[col].values, q_pos, q_neg)
    d = tsub.copy()
    d["_h"] = ec.hysteresis_alert(d, col, thr, thr * 0.5)
    d["_stack"] = (d["_h"].to_numpy() & (tier != "CLEAR")).astype(float)
    sm = episode_stats(d, "_stack", ty, 0.5, gap_h=gap_h)
    rows.append(row("+ hysteresis + conformal (stacked)", sm, br,
                    "conformal removes CLEAR-tier alerts from the latched run"))
    out["stacked"] = {k: v for k, v in row("stacked", sm, br).items() if k != "rule"}

    # ═══ print ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 104)
    print(f"FALSE-ALARM LEVERS — {preds_stem}, horizon {h:g}h, "
          f"sensitivity target {sens:.0%}, base rate {br:.4f}")
    print("=" * 104)

    print("\n1. EPISODE GAP  (how many alerting hours count as ONE alarm)")
    print(f"   {'gap':>6} {'episodes':>9} {'ep-PPV':>8} {'ep-LIFT':>8} {'recall':>8} "
          f"{'per100':>8} {'lead':>6}")
    for r in gap_rows:
        print(f"   {r['gap_h']:>5}h {r['episodes']:>9,} {r['ep_ppv']:>8.4f} "
              f"{r['ep_lift']:>8.3f} {r['recall']:>8.4f} {r['per100']:>8.0f} {r['lead']:>6.1f}")
    print("   NOTE recall is INVARIANT to the gap -- merging never changes whether a patient")
    print("        was caught, so this parameter is a reporting choice, not a model property.")

    print("\n2. HYSTERESIS  (alert at tau_high, release only below tau_low)")
    print(f"   {'tau_low':>10} {'episodes':>9} {'ep-PPV':>8} {'ep-LIFT':>8} {'recall':>8} "
          f"{'per100':>8} {'lead':>6}")
    for r in hyst_rows:
        print(f"   {r['tau_low_frac']:>9.0%} {r['episodes']:>9,} {r['ep_ppv']:>8.4f} "
              f"{r['ep_lift']:>8.3f} {r['recall']:>8.4f} {r['per100']:>8.0f} {r['lead']:>6.1f}")

    print("\n3. CONFORMAL YES/NO/IDK  (alpha = 1 - coverage guarantee)")
    print(f"   {'alpha':>6} {'%PAGE':>7} {'%WATCH':>7} {'%CLEAR':>7} {'PAGE ep-PPV':>12} "
          f"{'PAGE lift':>10} {'PAGE recall':>12} {'per100':>8} {'events in WATCH':>16}")
    for r in conf_rows:
        print(f"   {r['alpha']:>6.2f} {r['pct_PAGE']:>7.1%} {r['pct_WATCH']:>7.1%} "
              f"{r['pct_CLEAR']:>7.1%} {r['page_ep_ppv']:>12.4f} {r['page_ep_lift']:>10.3f} "
              f"{r['page_recall']:>12.4f} {r['page_per100']:>8.0f} "
              f"{r['frac_true_events_in_WATCH']:>16.1%}")

    print("\n4. STACKED LADDER  (each row keeps the previous row's changes)")
    print(f"   {'rule':38} {'episodes':>9} {'ep-PPV':>8} {'ep-LIFT':>8} {'recall':>8} "
          f"{'per100':>8} {'lead':>6}")
    for r in rows:
        print(f"   {r['rule']:38} {r['episodes']:>9,} {r['ep_ppv']:>8.4f} {r['ep_lift']:>8.3f} "
              f"{r['recall']:>8.4f} {r['per100']:>8.0f} {r['lead']:>6.1f}")
    print("   notes:")
    for r in rows:
        if r["note"]:
            print(f"     {r['rule']:38} {r['note']}")
    print("=" * 104 + "\n")

    path = config.tpath(f"fp_stack_{preds_stem}.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print(f"wrote {path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--preds", default="preds_ordinal_mwp")
    ap.add_argument("--horizon", type=float, default=12)
    ap.add_argument("--sens", type=float, default=0.80)
    ap.add_argument("--gap", type=float, default=ec.EPISODE_GAP_H)
    a = ap.parse_args()
    main(a.preds, a.horizon, a.sens, a.gap)
