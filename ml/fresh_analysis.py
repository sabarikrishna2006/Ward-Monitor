"""
fresh_analysis.py
=================
Derives EVERYTHING from scratch from the actual parquet prediction files.
No pre-cached reports used. Computes:
  - Full test-split metrics at every horizon (6, 9, 12, 18, 24h)
  - Multiple sensitivity targets (70%, 75%, 80%, 85%, 90%)
  - Multiple episode gap values (1h, 2h, 4h, 6h, 8h, 12h)
  - Hysteresis (dual-threshold) results at each horizon
  - Non-vacuous analysis (NEWS2 < 7 at anchor time) — the stat Prof. Shroff asked for
  - Calibration: ECE and Brier score
  - AUC / AUPRC
  - Row-level and episode-level false-positive breakdown
  - Comparison table: single-threshold vs hysteresis vs different episode gaps

Model: models_ordinal_esc (the deployed escalation-target model)
Predictions: data/preds_ordinal_esc.parquet

Run:
    cd common_db_main_latest/ml
    PYTHONUTF8=1 py -3 fresh_analysis.py
"""

from __future__ import annotations
import json, sys, os
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

# ── project imports ──────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
import config
import eval_core as ec
from known_status import known_subset

# ── load predictions ─────────────────────────────────────────────────────────
PREDS_FILE = config.dpath("preds_ordinal_esc.parquet")
print(f"Loading predictions from {PREDS_FILE} ...")
preds = pd.read_parquet(PREDS_FILE)

# ── examine columns ──────────────────────────────────────────────────────────
print(f"\nShape: {preds.shape}")
print(f"Columns: {list(preds.columns[:30])}")
print(f"Split distribution:\n{preds['split'].value_counts()}")

calib = preds[preds.split == "calib"].copy()
test  = preds[preds.split == "test"].copy()

print(f"\nCalib rows: {len(calib):,}  |  Test rows: {len(test):,}")
print(f"Unique stays – calib: {calib['stay_id'].nunique():,}  |  test: {test['stay_id'].nunique():,}")

# check what calibrated probability columns exist
cal_cols = [c for c in preds.columns if c.startswith("p_calibrated_")]
print(f"\nCalibrated probability columns: {cal_cols}")

# ── configuration ─────────────────────────────────────────────────────────────
HORIZONS        = [6, 9, 12, 18, 24]
SENS_TARGETS    = [0.70, 0.75, 0.80, 0.85, 0.90]
EPISODE_GAPS    = [1.0, 2.0, 4.0, 6.0, 8.0, 12.0]

# ── SECTION 1 — AUROC / AUPRC / Brier at each horizon ────────────────────────
print("\n" + "="*70)
print("SECTION 1: AUROC / AUPRC / Brier Score — test split, all horizons")
print("="*70)

disc_results = {}
for h in HORIZONS:
    col = f"p_calibrated_{h}h"
    if col not in test.columns:
        print(f"  [SKIP] horizon {h}h — column {col} not found")
        continue
    tsub, ty = known_subset(test, h)
    if len(ty) == 0 or ty.sum() == 0:
        print(f"  [SKIP] horizon {h}h — no events in known subset")
        continue
    scores = tsub[col].values.astype(float)
    base   = float(ty.mean())

    auc   = roc_auc_score(ty, scores)
    auprc = average_precision_score(ty, scores)
    brier = brier_score_loss(ty, scores)

    disc_results[h] = dict(
        horizon=h, n_known=len(tsub), n_events=int(ty.sum()),
        base_rate=base, auroc=auc, auprc=auprc, brier=brier
    )
    print(f"  {h:2d}h  |  n={len(tsub):6,}  events={ty.sum():4,}  base={base:.3f}"
          f"  AUROC={auc:.4f}  AUPRC={auprc:.4f}  Brier={brier:.4f}")

# ── SECTION 2 — Calibration (ECE) ─────────────────────────────────────────────
print("\n" + "="*70)
print("SECTION 2: Calibration — Expected Calibration Error (ECE)")
print("="*70)
for h in HORIZONS:
    col = f"p_calibrated_{h}h"
    if col not in test.columns: continue
    tsub, ty = known_subset(test, h)
    if len(ty) == 0: continue
    scores = tsub[col].values.astype(float)
    # ECE: bin into deciles, |mean(pred) - mean(actual)| per bin, weighted
    bins = pd.qcut(scores, q=10, duplicates="drop")
    ece_df = pd.DataFrame({"pred": scores, "actual": ty.astype(float), "bin": bins})
    g = ece_df.groupby("bin")
    ece = float((g["actual"].mean() - g["pred"].mean()).abs().mul(g["pred"].count() / len(scores)).sum())
    # Calibration slope: logistic regression of actual on logit(pred)
    from scipy.special import logit as sp_logit
    lp = sp_logit(np.clip(scores, 1e-6, 1 - 1e-6))
    from sklearn.linear_model import LogisticRegression
    lr = LogisticRegression(fit_intercept=True).fit(lp.reshape(-1, 1), ty)
    slope = float(lr.coef_[0][0])
    intercept = float(lr.intercept_[0])
    print(f"  {h:2d}h  ECE={ece:.5f}  calibration slope={slope:.3f}  intercept={intercept:.3f}")

# ── SECTION 3 — Threshold sweep: multiple sensitivity targets (24h horizon) ──
print("\n" + "="*70)
print("SECTION 3: Threshold sweep at 24h — multiple sensitivity targets")
print("="*70)
print(f"  {'Sens_target':>12} {'Threshold':>10} {'Test_sens':>10} {'Test_spec':>10} "
      f"{'Row_PPV':>10} {'Row_FPR':>10} {'Ep_PPV':>10} {'Ep_LIFT':>9} {'Patient_rec':>12} {'Alarms/day/100':>15}")

h_sweep = 24
col_sweep = f"p_calibrated_{h_sweep}h"
if col_sweep in calib.columns:
    csub_sw, cy_sw = known_subset(calib, h_sweep)
    tsub_sw, ty_sw = known_subset(test,  h_sweep)
    base_24 = float(ty_sw.mean())

    sweep_results = []
    for st in SENS_TARGETS:
        thr = ec.select_threshold(csub_sw[col_sweep].values, cy_sw, st)
        row = ec.row_confusion(ty_sw, tsub_sw[col_sweep].values, thr)
        epm = ec.episode_metrics(tsub_sw, col_sweep, thr, ty_sw, gap_h=2.0)
        alarms_per_day_100 = epm["episodes_per_patient_day"] * 100
        ep_lift = ec.lift(epm["episode_ppv"], base_24)
        row_fpr = 1.0 - row["specificity"]
        sweep_results.append(dict(
            sens_target=st, threshold=thr,
            test_sensitivity=row["sensitivity"], test_specificity=row["specificity"],
            row_ppv=row["ppv"], row_fpr=row_fpr,
            episode_ppv=epm["episode_ppv"], episode_lift=ep_lift,
            patient_recall=epm["patient_recall"],
            alarms_per_day_100=alarms_per_day_100,
            median_lead_time=epm["median_lead_time_h"],
            n_episodes=epm["n_episodes"], n_true=epm["n_true_episodes"]
        ))
        print(f"  {st*100:>11.0f}%  {thr:>10.5f}  {row['sensitivity']:>10.4f}  "
              f"{row['specificity']:>10.4f}  {row['ppv']:>10.4f}  {row_fpr:>10.4f}  "
              f"{epm['episode_ppv']:>10.4f}  {ep_lift:>9.3f}x  "
              f"{epm['patient_recall']:>12.4f}  {alarms_per_day_100:>15.1f}")

# ── SECTION 4 — Episode Gap Sensitivity at 80% sens (multiple horizons) ──────
print("\n" + "="*70)
print("SECTION 4: Episode Gap Sensitivity — at 80% sensitivity, each horizon")
print("="*70)
print(f"  {'Horizon':>8} {'Gap':>6} {'Episodes':>10} {'Ep_PPV':>8} {'Ep_LIFT':>9} "
      f"{'Pat_Recall':>11} {'Alarms/d/100':>13} {'Lead_h':>7}")

gap_rows = []
for h in HORIZONS:
    col = f"p_calibrated_{h}h"
    if col not in calib.columns: continue
    csub_h, cy_h = known_subset(calib, h)
    tsub_h, ty_h = known_subset(test,  h)
    if len(ty_h) == 0 or ty_h.sum() == 0: continue
    thr = ec.select_threshold(csub_h[col].values, cy_h, 0.80)
    base_h = float(ty_h.mean())

    for gap in EPISODE_GAPS:
        epm = ec.episode_metrics(tsub_h, col, thr, ty_h, gap_h=gap)
        ep_lift = ec.lift(epm["episode_ppv"], base_h)
        alarms100 = epm["episodes_per_patient_day"] * 100
        gap_rows.append(dict(
            horizon=h, gap_h=gap,
            n_episodes=epm["n_episodes"], episode_ppv=epm["episode_ppv"],
            episode_lift=ep_lift, patient_recall=epm["patient_recall"],
            alarms_per_day_100=alarms100, median_lead_h=epm["median_lead_time_h"]
        ))
        print(f"  {h:>7}h  {gap:>5.0f}h  {epm['n_episodes']:>10,}  "
              f"{epm['episode_ppv']:>8.4f}  {ep_lift:>9.3f}x  "
              f"{epm['patient_recall']:>11.4f}  {alarms100:>13.1f}  "
              f"{epm['median_lead_time_h']:>7.1f}")

# ── SECTION 5 — Hysteresis vs Single-Threshold (24h, 12h, 6h) ────────────────
print("\n" + "="*70)
print("SECTION 5: Hysteresis (Schmitt trigger) vs Single-Threshold — 80% sens")
print("="*70)

# Using tau_high from serving_meta as the deployed threshold
import json as _json
SERVING_META_PATH = os.path.join(os.path.dirname(__file__),
    "..", "sabari_project", "backend", "model", "serving_meta.json")
with open(SERVING_META_PATH) as _f:
    SERVING_META = _json.load(_f)
tau_high = SERVING_META["tau_high"]
tau_low  = SERVING_META["tau_low"]
print(f"  Deployed thresholds:  tau_high={tau_high:.5f}  tau_low={tau_low:.5f}")
print(f"  Ratio tau_low/tau_high: {tau_low/tau_high:.3f} (hysteresis deadband)\n")

print(f"  {'Horizon':>8} {'Mode':>20} {'Episodes':>10} {'Ep_PPV':>8} {'Ep_LIFT':>9} "
      f"{'Pat_Recall':>11} {'Alarms/d/100':>13} {'Lead_h':>7}")

hyst_results = []
for h in [6, 12, 24]:
    col = f"p_calibrated_{h}h"
    if col not in calib.columns: continue
    csub_h, cy_h = known_subset(calib, h)
    tsub_h, ty_h = known_subset(test,  h)
    if len(ty_h) == 0: continue
    base_h = float(ty_h.mean())

    # — Single threshold at 80% sens —
    thr_80 = ec.select_threshold(csub_h[col].values, cy_h, 0.80)
    epm_single = ec.episode_metrics(tsub_h, col, thr_80, ty_h, gap_h=2.0)
    lift_single = ec.lift(epm_single["episode_ppv"], base_h)
    alarms_single = epm_single["episodes_per_patient_day"] * 100

    # — Hysteresis using deployed tau_high / tau_low —
    hyst_on = ec.hysteresis_alert(tsub_h, col, thr_high=tau_high, thr_low=tau_low)
    tsub_hc = tsub_h.copy()
    tsub_hc["_hyst"] = hyst_on.astype(float)
    epm_hyst = ec.episode_metrics(tsub_hc, "_hyst", 0.5, ty_h, gap_h=2.0)
    lift_hyst = ec.lift(epm_hyst["episode_ppv"], base_h)
    alarms_hyst = epm_hyst["episodes_per_patient_day"] * 100

    for mode, epm, ep_lift, alarms in [
        ("Single (80% sens)", epm_single, lift_single, alarms_single),
        ("Hysteresis (deployed)", epm_hyst, lift_hyst, alarms_hyst)
    ]:
        hyst_results.append(dict(horizon=h, mode=mode, **epm,
                                 episode_lift=ep_lift, alarms_per_day_100=alarms))
        print(f"  {h:>7}h  {mode:>20}  {epm['n_episodes']:>10,}  "
              f"{epm['episode_ppv']:>8.4f}  {ep_lift:>9.3f}x  "
              f"{epm['patient_recall']:>11.4f}  {alarms:>13.1f}  "
              f"{epm['median_lead_time_h']:>7.1f}")
    print()

# ── SECTION 6 — Non-Vacuous Analysis (the Prof. Shroff stat) ─────────────────
print("\n" + "="*70)
print("SECTION 6: Non-Vacuous Analysis — NEWS2 < 7 at anchor (Prof. Shroff's stat)")
print("="*70)
print("  Definition: anchor where (a) outcome known at 24h AND (b) news2_at_anchor < 7")
print("  Hysteresis computed over FULL known set first (to preserve latch state),")
print("  THEN restricted to news2<7 rows — filtering first would corrupt the latch.\n")

col_24 = "p_calibrated_24h"
if col_24 in test.columns and "news2_at_anchor" in test.columns:
    tsub_24, ty_24 = known_subset(test, 24)
    base_24v = float(ty_24.mean())

    # compute hysteresis over the FULL known set
    hyst_full = ec.hysteresis_alert(tsub_24, col_24, thr_high=tau_high, thr_low=tau_low)
    tsub_24_hc = tsub_24.copy()
    tsub_24_hc["_hyst"] = hyst_full.astype(float)

    n_total_known = len(tsub_24)

    # now restrict to non-vacuous: news2 < 7
    nv_mask = tsub_24_hc["news2_at_anchor"].values < 7
    nv_df = tsub_24_hc.loc[nv_mask].copy()
    nv_y  = ty_24[nv_mask]

    n_nv = len(nv_df)
    n_alert_nv = int(nv_df["_hyst"].sum())
    nv_base = float(nv_y.mean()) if len(nv_y) else float("nan")

    epm_nv = ec.episode_metrics(nv_df, "_hyst", 0.5, nv_y, gap_h=2.0)
    lift_nv = ec.lift(epm_nv["episode_ppv"], nv_base) if nv_base else float("nan")

    # vacuous: news2 >= 7
    v_mask = ~nv_mask
    v_df = tsub_24_hc.loc[v_mask].copy()
    v_y  = ty_24[v_mask]
    v_base = float(v_y.mean()) if len(v_y) else float("nan")
    epm_v = ec.episode_metrics(v_df, "_hyst", 0.5, v_y, gap_h=2.0)
    lift_v = ec.lift(epm_v["episode_ppv"], v_base) if v_base else float("nan")

    print(f"  Total known-status anchors at 24h:       {n_total_known:>8,}")
    print(f"  Non-vacuous anchors (NEWS2 < 7):         {n_nv:>8,}  ({100*n_nv/n_total_known:.1f}%)")
    print(f"  Vacuous anchors (NEWS2 >= 7):            {n_total_known-n_nv:>8,}  ({100*(n_total_known-n_nv)/n_total_known:.1f}%)")
    print(f"  Non-vacuous alerting person-hours:       {n_alert_nv:>8,}")
    print(f"  Non-vacuous base rate (event rate):      {nv_base:.4f}  ({100*nv_base:.2f}%)")
    print()

    print("  NON-VACUOUS episode metrics (NEWS2 < 7 at alarm time):")
    print(f"    Total alert episodes:                  {epm_nv['n_episodes']:>6,}")
    print(f"    True episodes (correctly caught):      {epm_nv['n_true_episodes']:>6,}")
    print(f"    False episodes (false alarms):         {epm_nv['n_false_episodes']:>6,}")
    print(f"    Episode PPV:                           {epm_nv['episode_ppv']:.4f}  ({100*epm_nv['episode_ppv']:.2f}%)")
    print(f"    False Positive Rate (episodes):        {1-epm_nv['episode_ppv']:.4f}  ({100*(1-epm_nv['episode_ppv']):.2f}%)")
    print(f"    Episode LIFT over base:                {lift_nv:.3f}x")
    print(f"    Event patients who were NEWS2<7:       {epm_nv['n_event_patients']:>6,}")
    print(f"    Event patients caught (recall):        {epm_nv['n_event_patients_caught']:>6,}  ({100*epm_nv['patient_recall']:.2f}%)")
    print(f"    Median lead time:                      {epm_nv['median_lead_time_h']:.1f}h")
    print(f"    Alarms per day per 100 patients:       {epm_nv['episodes_per_patient_day']*100:.1f}")
    print()

    print("  VACUOUS episode metrics (NEWS2 >= 7 at alarm time — for reference):")
    print(f"    Total alert episodes:                  {epm_v['n_episodes']:>6,}")
    print(f"    Episode PPV:                           {epm_v['episode_ppv']:.4f}  ({100*epm_v['episode_ppv']:.2f}%)")
    print(f"    Episode LIFT:                          {lift_v:.3f}x")
    print(f"    Patient recall:                        {epm_v['patient_recall']:.4f}  ({100*epm_v['patient_recall']:.2f}%)")
    print(f"    Median lead time:                      {epm_v['median_lead_time_h']:.1f}h")

    # episode gap sensitivity for non-vacuous
    print("\n  Non-vacuous EPISODE GAP sensitivity (how does PPV change with gap choice?):")
    print(f"  {'Gap':>6} {'Episodes':>10} {'Ep_PPV':>8} {'Ep_LIFT':>9} {'Pat_Recall':>11} {'Alarms/d/100':>13}")
    for gap in EPISODE_GAPS:
        epm_gap = ec.episode_metrics(nv_df, "_hyst", 0.5, nv_y, gap_h=gap)
        ep_lift_gap = ec.lift(epm_gap["episode_ppv"], nv_base) if nv_base else float("nan")
        print(f"  {gap:>5.0f}h  {epm_gap['n_episodes']:>10,}  "
              f"{epm_gap['episode_ppv']:>8.4f}  {ep_lift_gap:>9.3f}x  "
              f"{epm_gap['patient_recall']:>11.4f}  {epm_gap['episodes_per_patient_day']*100:>13.1f}")
else:
    print("  [SKIP] news2_at_anchor column not found or col_24 missing")
    # print available columns for debugging
    print(f"  Available columns with 'news2': {[c for c in test.columns if 'news2' in c.lower()]}")

# ── SECTION 7 — Non-vacuous at multiple sensitivity targets ──────────────────
print("\n" + "="*70)
print("SECTION 7: Non-vacuous at multiple sensitivity targets (24h horizon)")
print("="*70)
print(f"  {'Sens_target':>12} {'Threshold':>10} {'Ep_PPV':>8} {'Ep_LIFT':>9} "
      f"{'Pat_Recall':>11} {'Alarms/d/100':>13} {'Lead_h':>7}")

if col_24 in calib.columns and "news2_at_anchor" in test.columns:
    csub_24, cy_24 = known_subset(calib, 24)
    tsub_24_raw, ty_24_raw = known_subset(test, 24)

    for st in SENS_TARGETS:
        thr_st = ec.select_threshold(csub_24[col_24].values, cy_24, st)
        # hysteresis with tau_low = thr_st / 2
        tau_l_st = thr_st / 2.0
        hyst_st = ec.hysteresis_alert(tsub_24_raw, col_24, thr_high=thr_st, thr_low=tau_l_st)
        tsub_st = tsub_24_raw.copy()
        tsub_st["_h"] = hyst_st.astype(float)
        nv_m = tsub_st["news2_at_anchor"].values < 7
        nv_sub = tsub_st.loc[nv_m]
        nv_y_sub = ty_24_raw[nv_m]
        if len(nv_y_sub) == 0: continue
        nv_b = float(nv_y_sub.mean())
        epm_st = ec.episode_metrics(nv_sub, "_h", 0.5, nv_y_sub, gap_h=2.0)
        ep_lift_st = ec.lift(epm_st["episode_ppv"], nv_b)
        print(f"  {st*100:>11.0f}%  {thr_st:>10.5f}  {epm_st['episode_ppv']:>8.4f}  "
              f"{ep_lift_st:>9.3f}x  {epm_st['patient_recall']:>11.4f}  "
              f"{epm_st['episodes_per_patient_day']*100:>13.1f}  {epm_st['median_lead_time_h']:>7.1f}")

# ── SECTION 8 — Best-performing configuration summary ────────────────────────
print("\n" + "="*70)
print("SECTION 8: Best configurations (by different criteria)")
print("="*70)

# — Best PPV (highest precision) at >= 80% patient recall
if gap_rows:
    df_gap = pd.DataFrame(gap_rows)
    best_ppv = df_gap[df_gap.patient_recall >= 0.80].sort_values("episode_ppv", ascending=False)
    if len(best_ppv):
        best = best_ppv.iloc[0]
        print(f"  Best Episode PPV (recall >= 80%):  horizon={int(best.horizon)}h  gap={best.gap_h}h  "
              f"PPV={best.episode_ppv:.4f} ({100*best.episode_ppv:.1f}%)  lift={best.episode_lift:.3f}x  "
              f"recall={best.patient_recall:.4f}  alarms/d/100={best.alarms_per_day_100:.1f}")

# — Best lift
if gap_rows:
    best_lift = df_gap.sort_values("episode_lift", ascending=False).iloc[0]
    print(f"  Best Lift:                         horizon={int(best_lift.horizon)}h  gap={best_lift.gap_h}h  "
          f"PPV={best_lift.episode_ppv:.4f}  lift={best_lift.episode_lift:.3f}x  "
          f"recall={best_lift.patient_recall:.4f}")

# — Best alarm efficiency (fewest alarms, recall >= 85%)
if gap_rows:
    best_eff = df_gap[df_gap.patient_recall >= 0.85].sort_values("alarms_per_day_100").iloc[0]
    print(f"  Best Alarm Efficiency (recall>=85%)  horizon={int(best_eff.horizon)}h  gap={best_eff.gap_h}h  "
          f"alarms={best_eff.alarms_per_day_100:.1f}/d/100  PPV={best_eff.episode_ppv:.4f}  "
          f"recall={best_eff.patient_recall:.4f}")

# ── SECTION 9 — Row-level vs Episode-level PPV comparison table ───────────────
print("\n" + "="*70)
print("SECTION 9: Row-level vs Episode-level PPV (why they differ) — 80% sens, 2h gap")
print("="*70)
print(f"  {'Horizon':>8} {'BaseRate':>10} {'Row_PPV':>10} {'Ep_PPV':>10} {'Ep_Lift':>9} "
      f"{'Ep_Count':>10} {'Pat_Recall':>11} {'Lead_h':>7}")

for h in HORIZONS:
    col = f"p_calibrated_{h}h"
    if col not in calib.columns: continue
    csub_h, cy_h = known_subset(calib, h)
    tsub_h, ty_h = known_subset(test,  h)
    if len(ty_h) == 0: continue
    thr = ec.select_threshold(csub_h[col].values, cy_h, 0.80)
    base_h = float(ty_h.mean())
    row_c = ec.row_confusion(ty_h, tsub_h[col].values, thr)
    epm_h = ec.episode_metrics(tsub_h, col, thr, ty_h, gap_h=2.0)
    ep_l  = ec.lift(epm_h["episode_ppv"], base_h)
    print(f"  {h:>7}h  {base_h:>10.4f}  {row_c['ppv']:>10.4f}  {epm_h['episode_ppv']:>10.4f}  "
          f"{ep_l:>9.3f}x  {epm_h['n_episodes']:>10,}  {epm_h['patient_recall']:>11.4f}  "
          f"{epm_h['median_lead_time_h']:>7.1f}")

print("\n" + "="*70)
print("DONE — all results computed fresh from data/preds_ordinal_esc.parquet")
print("="*70)
