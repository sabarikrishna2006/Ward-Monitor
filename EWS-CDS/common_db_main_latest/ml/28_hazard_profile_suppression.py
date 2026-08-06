"""
Stage 28 — The three uses of the hazard curve, plus the corrected suppression rules.

WHERE THE HAZARD VALUES CAN BE USED. The model's seven per-interval hazards are
currently collapsed to a survival curve and thrown away. They carry information the
cumulative probability does not, and this file tests all three uses:

  1. PROFILE SHAPE as a TRIAGE RE-RANKER (not an alert gate).
     Measured earlier on the NEWS2 model: episode-PPV 0.1477 in the flattest decile
     vs 0.4779 in the most-peaked -- a 3.2x spread. The correlation with being
     correct is POSITIVE (+0.2142), so it is a RISK signal, not an uncertainty
     signal; gating on it would suppress the best alerts. The correct use is to
     order the worklist, which changes priority without changing what fires.
     This signal exists ONLY because the seven boosters are independent -- a
     shared-trunk model would smooth it away.

  2. CUMULATIVE LOG-HAZARD as the SEVERITY SCALE.
     Lambda(t) = -log S(t) is the standard cumulative hazard. Unlike a probability it
     is unbounded and additive, so DIFFERENCES are meaningful -- a better scale for
     ranking a worklist than probabilities squashed near zero.

  3. INTER-INTERVAL HAZARD RATIOS as RISK ACCELERATION.
     h_j / h_{j-1} is a time-series dynamic derived from the model's own output
     rather than from the inputs -- the same "acceleration" idea as
     mean_2h - mean_12h, but on the risk trajectory.

THE SUPPRESSION RULES, both reworked after failing in stage 27:
  (a) "no alert within 2h of admission" was untestable because hours_since_adm is not
      carried into the predictions file. Joined back from the feature file here.
  (b) "no re-alert unless risk increased" was implemented WRONG in stage 27: masking
      alert ROWS where risk did not rise FRAGMENTS a continuous run into many
      episodes (measured 1,801 -> 3,752, the exact opposite of suppression). The
      correct rule acts on EPISODE BOUNDARIES on top of the hysteresis latch: while
      latched, emit no NEW episode unless risk exceeds the previous episode's peak.

Run: PYTHONUTF8=1 EWS_TAG=esc py -3 28_hazard_profile_suppression.py
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pandas as pd
import xgboost as xgb
from scipy.stats import spearmanr

import config
import eval_core as ec
from known_status import known_subset

H = config.HORIZONS_H


# ══════════════════════════════════════════════════════════════════════════
# 1-3. hazard-curve derived quantities
# ══════════════════════════════════════════════════════════════════════════
def hazard_matrix(model_dir: str, X: np.ndarray) -> np.ndarray:
    out = []
    for h in H:
        b = xgb.Booster()
        b.load_model(os.path.join(model_dir, f"hazard_interval_{h}h.json"))
        out.append(b.predict(xgb.DMatrix(X), iteration_range=(0, b.best_iteration + 1)))
    return np.column_stack(out)


def hazard_descriptors(hz: np.ndarray, ref_mean: np.ndarray) -> pd.DataFrame:
    """Shape + severity + acceleration, from the raw per-interval hazards.

    `ref_mean` is the per-interval population mean hazard from TRAIN, used to
    normalise away the fact that interval base rates differ (2.4%-4.4%) -- without
    it, "roughness" would just measure which intervals are intrinsically riskier.
    """
    Z = hz / np.clip(ref_mean, 1e-9, None)[None, :]
    d2 = np.abs(Z[:, :-2] - 2 * Z[:, 1:-1] + Z[:, 2:])          # discrete 2nd difference
    S = np.cumprod(1.0 - np.clip(hz, 0, 1 - 1e-12), axis=1)      # survival at each cutpoint
    lam = -np.log(np.clip(S, 1e-12, None))                       # cumulative log-hazard
    with np.errstate(divide="ignore", invalid="ignore"):
        ratios = hz[:, 1:] / np.clip(hz[:, :-1], 1e-9, None)
    return pd.DataFrame({
        # 1. shape
        "hz_roughness": d2.mean(axis=1),
        "hz_peak_to_mean": Z.max(axis=1) / np.clip(Z.mean(axis=1), 1e-9, None),
        "hz_argmax_interval": Z.argmax(axis=1).astype(float),
        # 2. severity -- unbounded, additive, differences are meaningful
        "hz_cum_loghazard_24h": lam[:, -1],
        "hz_cum_loghazard_12h": lam[:, 4] if lam.shape[1] > 4 else lam[:, -1],
        # 3. acceleration -- a dynamic derived from the model's OWN output
        "hz_max_accel": np.nanmax(ratios, axis=1),
        "hz_mean_accel": np.nanmean(ratios, axis=1),
    })


# ══════════════════════════════════════════════════════════════════════════
# suppression rules, reworked
# ══════════════════════════════════════════════════════════════════════════
def episodes_with_peak_rule(d: pd.DataFrame, latched: np.ndarray, score: np.ndarray,
                            gap_h: float, require_rise: bool) -> np.ndarray:
    """Return a 0/1 alert array whose EPISODE STRUCTURE honours the peak rule.

    Walk each patient in time order. A new episode may start only when the latch
    turns on. If `require_rise`, a new episode that begins within `gap_h` of the
    previous one is suppressed unless its score exceeds the previous episode's peak
    -- i.e. a re-alert must carry NEW information, not merely re-cross the line.

    Acting on episode boundaries is the fix for stage 27, which masked alert ROWS and
    thereby fragmented runs instead of merging them.
    """
    out = np.zeros(len(d), dtype=float)
    t = pd.to_datetime(d["anchor_time"]).to_numpy()
    pid = d["stay_id"].to_numpy()
    prev_pid = None
    in_ep = False
    ep_peak = -np.inf
    last_end_t = None
    last_peak = -np.inf
    for i in range(len(d)):
        if pid[i] != prev_pid:
            prev_pid, in_ep, ep_peak, last_end_t, last_peak = pid[i], False, -np.inf, None, -np.inf
        on = bool(latched[i])
        if on and not in_ep:
            gap_ok = True
            if require_rise and last_end_t is not None:
                dt = (t[i] - last_end_t) / np.timedelta64(1, "h")
                if dt <= gap_h and score[i] <= last_peak:
                    gap_ok = False          # re-alert carries no new information
            if gap_ok:
                in_ep, ep_peak = True, score[i]
            else:
                continue
        if in_ep:
            if on:
                out[i] = 1.0
                ep_peak = max(ep_peak, score[i])
            else:
                in_ep, last_end_t, last_peak = False, t[i], ep_peak
    return out


# ══════════════════════════════════════════════════════════════════════════
def main(preds_stem, model_dir_name, feature_file, h, gap_h, sens):
    p = pd.read_parquet(config.tpath(f"{preds_stem}.parquet"))
    feats_df = pd.read_parquet(config.tpath(feature_file))
    meta = json.load(open(os.path.join(config.tpath(model_dir_name), "meta.json")))
    feat_cols = meta["features"]
    mdir = config.tpath(model_dir_name)

    col = f"p_calibrated_{int(h)}h"
    cal, te = p[p.split == "calib"].copy(), p[p.split == "test"].copy()
    csub, cy = known_subset(cal, h)
    tsub, ty = known_subset(te, h)
    thr = ec.select_threshold(csub[col].values, cy, sens)
    br = float(np.mean(ty))
    out = {"preds": preds_stem, "horizon": h, "base_rate": br, "threshold": thr}

    print("=" * 104)
    print(f"HAZARD-CURVE USES + SUPPRESSION — {preds_stem}, {h:g}h, "
          f"sens {sens:.0%}, base rate {br:.4f}")
    print("=" * 104)

    # ---- rebuild hazards for the test anchors --------------------------------
    key = ["stay_id", "anchor_time"]
    fx = feats_df[key + [c for c in feat_cols if c in feats_df.columns]]
    j = tsub[key].merge(fx, on=key, how="left")
    X = j[feat_cols].astype(float).values
    ftr = feats_df.sample(min(50000, len(feats_df)), random_state=0)
    ref = hazard_matrix(mdir, ftr[feat_cols].astype(float).values).mean(axis=0)
    hz = hazard_matrix(mdir, X)
    desc = hazard_descriptors(hz, ref)
    desc.index = tsub.index

    # ---- 1. profile shape as a TRIAGE RE-RANKER -----------------------------
    print("\n1. HAZARD-PROFILE SHAPE AS A TRIAGE RE-RANKER")
    print("   (does not change WHICH alerts fire -- only their order on the worklist)")
    ep = ec.alert_episodes(tsub, col, thr, ty)
    alerting = tsub[col].values >= thr
    print(f"   {'descriptor':24} {'spearman':>10} {'p':>10} "
          f"{'PPV lowest decile':>18} {'PPV highest decile':>19}")
    rank_rows = []
    yy = np.asarray(ty)[alerting]
    for c in desc.columns:
        u = desc.loc[alerting, c].to_numpy()
        ok = np.isfinite(u)
        if ok.sum() < 200:
            continue
        rho, pv = spearmanr(u[ok], yy[ok])
        r = pd.Series(u[ok]).rank(pct=True).to_numpy()
        b = np.clip((r * 10).astype(int), 0, 9)
        lo, hi = yy[ok][b == 0].mean(), yy[ok][b == 9].mean()
        rank_rows.append(dict(descriptor=c, spearman=float(rho), p=float(pv),
                             ppv_low_decile=float(lo), ppv_high_decile=float(hi)))
        print(f"   {c:24} {rho:>+10.4f} {pv:>10.1e} {lo:>18.4f} {hi:>19.4f}")
    out["profile_reranker"] = rank_rows

    # precision@K among alerting episodes, ranked by the best descriptor
    best = max(rank_rows, key=lambda r: abs(r["spearman"]))["descriptor"]
    print(f"\n   PRECISION@K over the {len(ep):,} alert episodes, ranked by {best}")
    epd = ep.merge(
        tsub.assign(**{best: desc[best]})[["stay_id", "anchor_time", best]]
            .rename(columns={"anchor_time": "t_start"}),
        on=["stay_id", "t_start"], how="left")
    epd = epd.dropna(subset=[best]).sort_values(best, ascending=False)
    print(f"   {'top K%':>8} {'episodes':>9} {'precision':>10} {'vs all-episode PPV':>20}")
    allppv = float(ep["y_any"].mean())
    prec_rows = []
    for k in (0.10, 0.25, 0.50, 1.00):
        n = max(int(len(epd) * k), 1)
        pk = float(epd.head(n)["y_any"].mean())
        prec_rows.append(dict(top_k=k, n=n, precision=pk))
        print(f"   {k:>7.0%} {n:>9,} {pk:>10.4f} {pk/max(allppv,1e-9):>19.2f}x")
    out["precision_at_k"] = prec_rows

    # ---- 2/3. severity + acceleration ---------------------------------------
    print("\n2/3. CUMULATIVE LOG-HAZARD (severity) AND HAZARD RATIOS (acceleration)")
    ev = tsub[np.asarray(ty) == 1].copy()
    ev["lam"] = desc.loc[ev.index, "hz_cum_loghazard_24h"].to_numpy()
    ev["accel"] = desc.loc[ev.index, "hz_max_accel"].to_numpy()
    for name, cc in (("cumulative log-hazard", "lam"), ("max hazard ratio", "accel")):
        q = pd.qcut(ev[cc], 5, labels=False, duplicates="drop")
        g = ev.groupby(q)["T_hours"].agg(["size", "median"])
        rho, pv = spearmanr(ev[cc], ev["T_hours"])
        mono = bool(g["median"].is_monotonic_decreasing)
        print(f"   {name:24} spearman vs actual T_hours = {rho:+.4f} (p={pv:.1e})  "
              f"median-T monotonically DECREASING across quintiles: {mono}")
        print(f"      quintile medians (hours to event): "
              f"{[round(float(x),1) for x in g['median'].tolist()]}")
        out[f"severity_{cc}"] = dict(spearman=float(rho), monotonic=mono,
                                     quintile_medians=[float(x) for x in g["median"]])

    # ---- 4. suppression rules, reworked -------------------------------------
    print("\n4. SUPPRESSION RULES (reworked after both failed in stage 27)")
    d = tsub.sort_values(["stay_id", "anchor_time"]).copy()
    yd = pd.Series(ty, index=tsub.index).loc[d.index].to_numpy()
    sc = d[col].to_numpy()
    latch = ec.hysteresis_alert(d, col, thr, thr * 0.5)
    # join hours_since_adm back -- absent from preds, which is why (a) was untestable
    hsa = feats_df[key + ["hours_since_adm"]] if "hours_since_adm" in feats_df.columns else None
    if hsa is not None:
        d = d.merge(hsa, on=key, how="left", suffixes=("", "_f"))
        hcol = "hours_since_adm" if "hours_since_adm" in d.columns else "hours_since_adm_f"
    rules = []
    rules.append(("baseline (single threshold)", (sc >= thr).astype(float)))
    rules.append(("hysteresis latch", latch.astype(float)))
    if hsa is not None:
        rules.append(("+ no alert <2h after admission",
                      (latch & (d[hcol].fillna(99).to_numpy() >= 2.0)).astype(float)))
    rules.append(("+ re-alert only if above previous peak",
                  episodes_with_peak_rule(d, latch, sc, gap_h, require_rise=True)))
    if hsa is not None:
        both = latch & (d[hcol].fillna(99).to_numpy() >= 2.0)
        rules.append(("+ BOTH suppression rules",
                      episodes_with_peak_rule(d, both, sc, gap_h, require_rise=True)))
    print(f"   {'rule':42} {'episodes':>9} {'ep-PPV':>8} {'lift':>7} {'recall':>8} "
          f"{'per100':>7} {'lead':>6}")
    supp = []
    for name, arr in rules:
        dd = d.copy(); dd["_a"] = arr
        m = ec.episode_metrics(dd, "_a", 0.5, yd, gap_h=gap_h)
        supp.append(dict(rule=name, episodes=m["n_episodes"], ep_ppv=m["episode_ppv"],
                         lift=ec.lift(m["episode_ppv"], br), recall=m["patient_recall"],
                         per100=m["episodes_per_patient_day"] * 100,
                         lead=m["median_lead_time_h"]))
        print(f"   {name:42} {m['n_episodes']:>9,} {m['episode_ppv']:>8.4f} "
              f"{ec.lift(m['episode_ppv'], br):>7.3f} {m['patient_recall']:>8.4f} "
              f"{m['episodes_per_patient_day']*100:>7.0f} {m['median_lead_time_h']:>6.1f}")
    out["suppression"] = supp

    path = config.tpath(f"hazard_suppression_{preds_stem}.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2, default=float)
    print("=" * 104)
    print(f"wrote {path}\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--preds", default="preds_ordinal_mwp")
    ap.add_argument("--model-dir", default="models_ordinal_mwp")
    ap.add_argument("--features", default="features_mw.parquet")
    ap.add_argument("--horizon", type=float, default=24)
    ap.add_argument("--gap", type=float, default=ec.EPISODE_GAP_H)
    ap.add_argument("--sens", type=float, default=0.80)
    a = ap.parse_args()
    main(a.preds, a.model_dir, a.features, a.horizon, a.gap, a.sens)
