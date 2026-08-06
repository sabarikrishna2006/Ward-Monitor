"""
Stage 27 — Raising PPV: fixed conformal + two-stage cascade + suppression rules.

WHY PPV IS LOW, stated as arithmetic rather than opinion:

    PPV = sens*base / (sens*base + FPR*(1-base))

At 12h the base rate is 0.0465. To reach PPV = 0.30 at 80% sensitivity you would need
specificity 0.909; the model delivers 0.610. That is a demand to remove 77% of current
false positives while losing no true positives -- a bigger discrimination jump than
anything achieved in this project or reported in the field. **PPV at high sensitivity
is a prevalence constraint, not a model defect.**

The levers that actually move it, in order of measured effect:
  1. lower the sensitivity target                    (guaranteed, costs recall AND lead time)
  2. use a longer horizon                            (24h has ~2x the base rate of 12h)
  3. TWO-STAGE CASCADE -- raise the base rate of the SCORED population   <- untested
  4. suppression rules from the literature           <- untested here

THREE FIXES TO THE CONFORMAL IMPLEMENTATION IN STAGE 26:

  (1) SPLIT-CALIB. Stage 26 computed conformal quantiles on the same split the
      isotonic calibrator was FIT on. Those probabilities are optimistically
      calibrated there, so the nonconformity scores are too small and the quantiles
      too tight -- which breaks exchangeability and voids the coverage guarantee that
      is the entire reason to use conformal. Here the calibration split is halved by
      PATIENT (never by row): half fits nothing new but supplies the conformal
      quantiles, and the guarantee holds again.

  (2) ASYMMETRIC ALPHA. Missing an escalation is far worse than a false page, so the
      two labels do not deserve equal coverage. alpha_pos tight (few missed events),
      alpha_neg loose (accept more confident-negatives). This shrinks the abstention
      band where it is cheapest to shrink it.

  (3) SEPARATE THE TWO KINDS OF ABSTENTION. {0,1} = both labels plausible (genuine
      uncertainty -> WATCH). {} = NEITHER plausible, i.e. the score is unlike anything
      in calibration (out-of-distribution -> the model does not apply to this patient).
      Stage 26 merged them; they need different clinical handling.

Run: PYTHONUTF8=1 EWS_TAG=esc py -3 27_ppv_levers.py --preds preds_ordinal_mwp
"""
from __future__ import annotations

import argparse
import hashlib
import json

import numpy as np
import pandas as pd

import config
import eval_core as ec
from known_status import known_subset


# ══════════════════════════════════════════════════════════════════════════
def split_calib_by_patient(sub: pd.DataFrame, frac=0.5, seed=config.RANDOM_SEED):
    """Halve the calibration split BY PATIENT (never by row -- rows from one patient
    are correlated, so a row split would leak). Deterministic md5 bucketing, the same
    mechanism as 03_train.three_way_split."""
    subj = sub["subject_id"].to_numpy()
    lut = {s: int.from_bytes(hashlib.md5(f"conf|{int(s)}|{seed}".encode()).digest()[:8],
                             "big") / float(1 << 64) for s in np.unique(subj)}
    b = np.array([lut[s] for s in subj])
    return b < frac, b >= frac          # (mask_A, mask_B)


def conformal_quantiles(p: np.ndarray, y: np.ndarray, alpha_pos: float, alpha_neg: float):
    """Label-conditional (Mondrian) conformal quantiles with the finite-sample
    correction ceil((n+1)(1-alpha)) that yields the distribution-free guarantee."""
    p = np.asarray(p, float); y = np.asarray(y).astype(int)
    def q(scores, a):
        n = len(scores)
        if n == 0:
            return 1.0
        k = min(int(np.ceil((n + 1) * (1.0 - a))), n)
        return float(np.sort(scores)[k - 1])
    return q(1.0 - p[y == 1], alpha_pos), q(p[y == 0], alpha_neg)


def conformal_tiers(p: np.ndarray, q_pos: float, q_neg: float) -> np.ndarray:
    """PAGE {1} | CLEAR {0} | WATCH {0,1} | OOD {} -- four tiers, not three."""
    p = np.asarray(p, float)
    inc1 = (1.0 - p) <= q_pos
    inc0 = p <= q_neg
    t = np.empty(len(p), dtype=object)
    t[inc1 & ~inc0] = "PAGE"
    t[inc0 & ~inc1] = "CLEAR"
    t[inc1 & inc0] = "WATCH"
    t[~inc1 & ~inc0] = "OOD"
    return t


# ══════════════════════════════════════════════════════════════════════════
def main(preds_stem, h, gap_h):
    p = pd.read_parquet(config.tpath(f"{preds_stem}.parquet"))
    cal, te = p[p.split == "calib"].copy(), p[p.split == "test"].copy()
    col = f"p_calibrated_{int(h)}h"
    csub, cy = known_subset(cal, h)
    tsub, ty = known_subset(te, h)
    br = float(np.mean(ty))
    out = {"preds": preds_stem, "horizon": h, "base_rate": br}

    mA, mB = split_calib_by_patient(csub)
    print("=" * 100)
    print(f"PPV LEVERS — {preds_stem}, horizon {h:g}h, base rate {br:.4f}")
    print("=" * 100)
    print(f"\nconformal calibration half: {int(mB.sum()):,} rows / "
          f"{csub.loc[mB,'subject_id'].nunique():,} patients "
          f"(split by PATIENT; the other half was used to fit isotonic)")

    # ---- A. fixed conformal, symmetric vs asymmetric alpha -------------------
    print("\nA. CONFORMAL — split-calib, four tiers, symmetric vs asymmetric alpha")
    print(f"   {'a_pos':>6} {'a_neg':>6} {'%PAGE':>7} {'%WATCH':>7} {'%CLEAR':>7} {'%OOD':>6} "
          f"{'PAGE ep-PPV':>12} {'PAGE lift':>10} {'PAGE recall':>12} {'per100':>7} {'evts in WATCH':>14}")
    conf = []
    grids = [(a, a) for a in (0.05, 0.10, 0.20)] + [(0.05, 0.30), (0.05, 0.50), (0.02, 0.50)]
    for ap_, an_ in grids:
        qp, qn = conformal_quantiles(csub.loc[mB, col].values, np.asarray(cy)[mB], ap_, an_)
        t = conformal_tiers(tsub[col].values, qp, qn)
        d = tsub.copy(); d["_page"] = (t == "PAGE").astype(float)
        pm = ec.episode_metrics(d, "_page", 0.5, ty, gap_h=gap_h)
        yy = np.asarray(ty)
        ev_watch = float(np.sum((t == "WATCH") & (yy == 1)) / max(np.sum(yy == 1), 1))
        rec = dict(alpha_pos=ap_, alpha_neg=an_, q_pos=qp, q_neg=qn,
                   pct_PAGE=float((t == "PAGE").mean()), pct_WATCH=float((t == "WATCH").mean()),
                   pct_CLEAR=float((t == "CLEAR").mean()), pct_OOD=float((t == "OOD").mean()),
                   page_ep_ppv=pm["episode_ppv"], page_lift=ec.lift(pm["episode_ppv"], br),
                   page_recall=pm["patient_recall"],
                   page_per100=pm["episodes_per_patient_day"] * 100,
                   page_lead=pm["median_lead_time_h"], events_in_watch=ev_watch)
        conf.append(rec)
        print(f"   {ap_:>6.2f} {an_:>6.2f} {rec['pct_PAGE']:>7.1%} {rec['pct_WATCH']:>7.1%} "
              f"{rec['pct_CLEAR']:>7.1%} {rec['pct_OOD']:>6.1%} {rec['page_ep_ppv']:>12.4f} "
              f"{rec['page_lift']:>10.3f} {rec['page_recall']:>12.4f} "
              f"{rec['page_per100']:>7.0f} {ev_watch:>14.1%}")
    out["conformal_fixed"] = conf

    # ---- B. two-stage cascade -------------------------------------------------
    # Stage 1: a cheap, interpretable pre-filter that removes obviously-stable
    # patient-hours from the SCORED population, which raises the base rate among
    # those that remain -- the only lever that attacks the PPV ceiling itself rather
    # than trading along the existing curve. This is AI-TEW's Stage1/Stage2 design
    # and the "tiered" pattern in the JAMIA review.
    print("\nB. TWO-STAGE CASCADE — does pre-filtering raise the base rate of the scored set?")
    cands = {}
    if "news2_at_anchor" in tsub.columns:
        cands["NEWS2 >= 3"] = tsub["news2_at_anchor"].fillna(0).values >= 3
        cands["NEWS2 >= 5"] = tsub["news2_at_anchor"].fillna(0).values >= 5
    # risk-based prefilter: keep the top X% by predicted risk at the SHORTEST horizon,
    # which is cheap and independent of the decision-horizon score
    if "p_calibrated_2h" in tsub.columns:
        for keep in (0.75, 0.50):
            thr2 = np.quantile(tsub["p_calibrated_2h"].values, 1 - keep)
            cands[f"top {keep:.0%} by 2h risk"] = tsub["p_calibrated_2h"].values >= thr2
    print(f"   {'stage-1 filter':24} {'kept':>7} {'%kept':>7} {'base rate':>10} "
          f"{'events kept':>12} {'ep-PPV@80%sens':>15} {'lift':>7} {'recall':>8} {'per100':>7}")
    base_row = None
    casc = []
    for name, keep_mask in [("(none — all anchors)", np.ones(len(tsub), bool))] + list(cands.items()):
        sk = tsub[keep_mask]; yk = np.asarray(ty)[keep_mask]
        if len(sk) < 500 or yk.sum() < 30:
            continue
        brk = float(np.mean(yk))
        # threshold re-fit on the calibration half, restricted the same way
        ck = csub
        if name.startswith("NEWS2"):
            lim = int(name.split(">=")[1])
            ck = csub[csub["news2_at_anchor"].fillna(0) >= lim]
        elif name.startswith("top"):
            frac = float(name.split()[1].strip("%")) / 100
            t2 = np.quantile(csub["p_calibrated_2h"].values, 1 - frac)
            ck = csub[csub["p_calibrated_2h"].values >= t2]
        cyk = np.asarray(cy)[csub.index.isin(ck.index)]
        thrk = ec.select_threshold(ck[col].values, cyk, 0.80)
        m = ec.episode_metrics(sk, col, thrk, yk, gap_h=gap_h)
        ev_kept = float(yk.sum() / max(np.asarray(ty).sum(), 1))
        rec = dict(filter=name, kept=int(len(sk)), pct_kept=len(sk) / len(tsub),
                   base_rate=brk, events_kept=ev_kept, ep_ppv=m["episode_ppv"],
                   lift=ec.lift(m["episode_ppv"], brk), recall=m["patient_recall"],
                   per100=m["episodes_per_patient_day"] * 100, lead=m["median_lead_time_h"])
        casc.append(rec)
        if base_row is None:
            base_row = rec
        print(f"   {name:24} {len(sk):>7,} {len(sk)/len(tsub):>7.1%} {brk:>10.4f} "
              f"{ev_kept:>12.1%} {m['episode_ppv']:>15.4f} {rec['lift']:>7.3f} "
              f"{m['patient_recall']:>8.4f} {rec['per100']:>7.0f}")
    out["cascade"] = casc
    print("   NOTE base rate rising is the point -- it lifts the PPV CEILING rather than")
    print("        trading along the existing curve. The cost is `events kept`: any event")
    print("        excluded by stage 1 is unrecoverable, so that column is the safety metric.")

    # ---- C. suppression rules from the literature -----------------------------
    print("\nC. LITERATURE SUPPRESSION RULES (JAMIA 2024 review mitigation table)")
    thr = ec.select_threshold(csub[col].values, cy, 0.80)
    d = tsub.sort_values(["stay_id", "anchor_time"]).copy()
    yy = pd.Series(ty, index=tsub.index).loc[d.index].to_numpy()
    d["_raw"] = (d[col].values >= thr).astype(float)
    rows = [("baseline", d["_raw"].copy())]
    # (i) no alert within 2h of admission
    if "hours_since_adm" in d.columns:
        rows.append(("+ no alert <2h after admission",
                     (d["_raw"].values * (d["hours_since_adm"].fillna(99).values >= 2)).astype(float)))
    # (ii) no re-alert unless risk increased since the last alerting hour
    g = d.groupby("stay_id")[col]
    rose = (d[col].values - g.shift(1).fillna(-np.inf).values) > 0
    first_of_run = d["_raw"].values.astype(bool) & ~(
        d.groupby("stay_id")["_raw"].shift(1).fillna(0).values.astype(bool))
    rows.append(("+ re-alert only if risk rose",
                 (d["_raw"].values * (first_of_run | rose)).astype(float)))
    print(f"   {'rule':34} {'episodes':>9} {'ep-PPV':>8} {'lift':>7} {'recall':>8} "
          f"{'per100':>7} {'lead':>6}")
    supp = []
    for name, arr in rows:
        dd = d.copy(); dd["_a"] = arr
        m = ec.episode_metrics(dd, "_a", 0.5, yy, gap_h=gap_h)
        supp.append(dict(rule=name, episodes=m["n_episodes"], ep_ppv=m["episode_ppv"],
                         lift=ec.lift(m["episode_ppv"], br), recall=m["patient_recall"],
                         per100=m["episodes_per_patient_day"] * 100,
                         lead=m["median_lead_time_h"]))
        print(f"   {name:34} {m['n_episodes']:>9,} {m['episode_ppv']:>8.4f} "
              f"{ec.lift(m['episode_ppv'], br):>7.3f} {m['patient_recall']:>8.4f} "
              f"{m['episodes_per_patient_day']*100:>7.0f} {m['median_lead_time_h']:>6.1f}")
    out["suppression"] = supp

    path = config.tpath(f"ppv_levers_{preds_stem}.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print("=" * 100)
    print(f"wrote {path}\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--preds", default="preds_ordinal_mwp")
    ap.add_argument("--horizon", type=float, default=12)
    ap.add_argument("--gap", type=float, default=ec.EPISODE_GAP_H)
    a = ap.parse_args()
    main(a.preds, a.horizon, a.gap)
