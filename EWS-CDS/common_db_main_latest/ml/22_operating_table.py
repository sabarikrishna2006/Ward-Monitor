"""
Stage 22 — The alerting SYSTEM, not just the model.

The professor's points 11 and 12 were that a model is not a system: what does the
clinician actually see, when does an alarm fire, how are repeated predictions
handled, and how is severity used to rank? This produces the two artefacts that
answer that.

  PART 1 — COMPOSITE OPERATING TABLE. Each lever applied cumulatively, with every
  column that matters shown together, INCLUDING the rows where a lever did
  nothing or cost something. A lever is never reported by its benefit alone.

  PART 2 — SEVERITY VALIDATION. "Shorter predicted time = higher severity" is a
  claim, not a fact. This tests it: bin patients by predicted conditional time to
  deterioration and check whether the ACTUAL time-to-event and event rate move
  monotonically across bins. If they do not, the severity ranking is decoration
  and must not be presented as triage.

Design commitments, stated so they can be defended:
  * NOTHING IS EVER SUPPRESSED. A hard alarm cap would hide a real deterioration
    to protect a metric — if the cap is 10 and the 11th patient is crashing, the
    system fails exactly when it matters. Alarm rate is a REPORTED AXIS here, never
    a control. The WATCH tier is a de-prioritisation, not a deletion.
  * Severity orders the worklist; the threshold decides what pages.

Run: PYTHONUTF8=1 EWS_TAG=news2 py -3 22_operating_table.py
"""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import os

import numpy as np
import pandas as pd

import eval_core as ec
from known_status import known_subset

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("operating")

PRIMARY_H = 12


def _cfg(tag):
    os.environ["EWS_TAG"] = tag
    import config
    importlib.reload(config)
    return config


def _row(name, m, base_rate, note=""):
    return dict(step=name, episode_ppv=m["episode_ppv"],
                episode_lift=ec.lift(m["episode_ppv"], base_rate),
                patient_recall=m["patient_recall"],
                episodes_per_patient_day=m["episodes_per_patient_day"],
                n_episodes=m["n_episodes"],
                median_lead_time_h=m.get("median_lead_time_h", float("nan")),
                note=note)


def composite_table(h=PRIMARY_H):
    """Levers applied cumulatively, each with its cost visible."""
    rows = []

    # --- step 0/1: label v1 vs v2, cell A -----------------------------------
    for lab, tag, name in (("v1", "news2", "baseline (label v1, cell A)"),
                           ("v2", "news2_v2lab", "+ label v2")):
        cfg = _cfg(tag)
        p = pd.read_parquet(cfg.tpath("preds_ordinal.parquet"))
        cal, te = p[p.split == "calib"].copy(), p[p.split == "test"].copy()
        r = ec.evaluate_horizon(cal, te, h)
        rows.append(_row(name, r["episode"], r["base_rate"],
                         note=f"base rate {r['base_rate']:.4f}"))

    # --- step 2: persistence, on v1 (measured, NOT adopted) -----------------
    cfg = _cfg("news2")
    t20 = importlib.import_module("20_persistence_voting")
    p = pd.read_parquet(cfg.tpath("preds_ordinal.parquet"))
    cal, te = p[p.split == "calib"].copy(), p[p.split == "test"].copy()
    col = f"p_calibrated_{h}h"
    csub, cy = known_subset(cal, h)
    tsub, ty = known_subset(te, h)
    thr = ec.select_threshold(csub[col].values, cy, 0.80)
    base_rate = float(np.mean(ty))
    d = tsub.sort_values(["stay_id", "anchor_time"]).copy()
    yy = pd.Series(ty, index=tsub.index).loc[d.index].to_numpy()
    d["_pers"] = t20.apply_persistence(d, col, thr, 2, 6).astype(float)
    rows.append(_row("+ persistence 2-of-6h  [REJECTED]",
                     ec.episode_metrics(d, "_pers", 0.5, yy), base_rate,
                     note="drops 58% of patients with only 1-2 pre-event observations"))

    # --- step 3: uncertainty gating on the m=6 MLP (adopted) ----------------
    mlp_path = cfg.tpath("preds_mlp_ordinal_m6.parquet")
    if os.path.exists(mlp_path):
        t19 = importlib.import_module("19_ensemble_uncertainty")
        pm = pd.read_parquet(mlp_path)
        calm, tem = pm[pm.split == "calib"].copy(), pm[pm.split == "test"].copy()
        cs, cyy = known_subset(calm, h)
        ts, tyy = known_subset(tem, h)
        thr_m = ec.select_threshold(cs[col].values, cyy, 0.80)
        br_m = float(np.mean(tyy))
        rows.append(_row("MLP m=6, no gating", ec.episode_metrics(ts, col, thr_m, tyy), br_m,
                         note="different model family — compare to itself, not to cell A"))
        cap = t19.fit_std_cap(cs, h, thr_m, cyy, 0.80)
        g = t19.gated_metrics(ts, h, thr_m, cap, tyy)
        for tier in ("page", "watch"):
            m = dict(g[tier]); m.setdefault("median_lead_time_h", float("nan"))
            rows.append(_row(f"  -> {tier.upper()} tier", m, br_m,
                             note=("pages a clinician" if tier == "page"
                                   else "worklist only — NOT suppressed")))
    return pd.DataFrame(rows)


def severity_validation(h=PRIMARY_H, n_bins=5):
    """Does a shorter PREDICTED time actually mean a sooner ACTUAL event?

    Restricted to patients who DO deteriorate within 24h, because `cond_time_24h`
    is by definition E[T | T<=24h] — asking it about patients who never
    deteriorate is asking it a question it was not built to answer.
    """
    cfg = _cfg("news2")
    p = pd.read_parquet(cfg.tpath("preds_ordinal.parquet"))
    te = p[p.split == "test"].copy()
    ev = te[(te.event == 1) & (te.T_hours <= 24)].copy()
    if len(ev) < 50:
        return None
    ev["sev_bin"] = pd.qcut(ev["cond_time_24h"], n_bins, labels=False, duplicates="drop")
    g = (ev.groupby("sev_bin")
           .agg(n=("T_hours", "size"),
                predicted_time_h=("cond_time_24h", "median"),
                actual_time_h=("T_hours", "median"),
                actual_mean_h=("T_hours", "mean"),
                risk_12h=(f"p_calibrated_{h}h", "median"))
           .reset_index())
    # Spearman across ALL event anchors, not just bin medians
    from scipy.stats import spearmanr
    rho, pv = spearmanr(ev["cond_time_24h"], ev["T_hours"])
    monotone = bool(g["actual_time_h"].is_monotonic_increasing)
    return dict(bins=g.to_dict("records"), spearman=float(rho), spearman_p=float(pv),
                bin_medians_monotonic=monotone, n_event_anchors=int(len(ev)),
                verdict=("USABLE as a triage ORDER: predicted-time bins rank actual time "
                         "correctly, even though the point estimate is compressed."
                         if monotone and rho > 0 else
                         "NOT usable as triage — predicted time does not order actual time."))


def main(h=PRIMARY_H):
    tbl = composite_table(h)
    cfg = _cfg("news2")
    tbl.to_csv(cfg.dpath("operating_table.csv"), index=False)

    print("\n" + "=" * 112)
    print(f"PART 1 — COMPOSITE OPERATING TABLE @ {h}h  (test set, threshold fit on calibration)")
    print("=" * 112)
    print(f"  {'step':36} {'ep-PPV':>8} {'ep-LIFT':>8} {'recall':>8} {'ep/pat-day':>11} "
          f"{'episodes':>9} {'lead(h)':>8}")
    for r in tbl.itertuples():
        print(f"  {r.step:36} {r.episode_ppv:>8.4f} {r.episode_lift:>8.3f} "
              f"{r.patient_recall:>8.4f} {r.episodes_per_patient_day:>11.3f} "
              f"{r.n_episodes:>9,} {r.median_lead_time_h:>8.1f}")
    print("\n  notes:")
    for r in tbl.itertuples():
        if r.note:
            print(f"    {r.step:36} {r.note}")

    sev = severity_validation(h)
    if sev:
        print("\n" + "=" * 112)
        print("PART 2 — SEVERITY VALIDATION  (patients who DO deteriorate within 24h)")
        print("  claim under test: 'shorter predicted time = more urgent'")
        print("=" * 112)
        print(f"  {'severity bin':>14} {'n':>6} {'median PREDICTED':>17} {'median ACTUAL':>15} "
              f"{'mean ACTUAL':>13} {'median risk@12h':>16}")
        for b in sev["bins"]:
            print(f"  {int(b['sev_bin']) + 1:>7} of 5 {b['n']:>6,} {b['predicted_time_h']:>17.2f} "
                  f"{b['actual_time_h']:>15.2f} {b['actual_mean_h']:>13.2f} {b['risk_12h']:>16.4f}")
        print(f"\n  Spearman(predicted, actual) over {sev['n_event_anchors']:,} event anchors: "
              f"{sev['spearman']:+.4f} (p={sev['spearman_p']:.2e})")
        print(f"  bin medians monotonically increasing: {sev['bin_medians_monotonic']}")
        print(f"  VERDICT: {sev['verdict']}")
        with open(cfg.dpath("severity_validation.json"), "w") as f:
            json.dump(sev, f, indent=2, default=float)
    print("=" * 112 + "\n")
    log.info("wrote data/operating_table.csv and data/severity_validation.json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=float, default=PRIMARY_H)
    a = ap.parse_args()
    main(a.horizon)
