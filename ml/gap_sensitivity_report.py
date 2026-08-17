"""
gap_sensitivity_report.py
=========================
Computes episode-gap stats at 6h, 8h, 12h gaps × all sensitivity targets
for ALL horizons (6, 9, 12, 18, 24h) and non-vacuous subset.

Run:
    cd common_db_main_latest/ml
    PYTHONUTF8=1 py -3 gap_sensitivity_report.py
"""
from __future__ import annotations
import sys, os, json
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(__file__))
import config
import eval_core as ec
from known_status import known_subset

# ── load ─────────────────────────────────────────────────────────────────────
preds = pd.read_parquet(config.dpath("preds_ordinal_esc.parquet"))
calib = preds[preds.split == "calib"].copy()
test  = preds[preds.split == "test"].copy()

HORIZONS      = [6, 9, 12, 18, 24]
SENS_TARGETS  = [0.70, 0.75, 0.80, 0.85, 0.90]
EPISODE_GAPS  = [6.0, 8.0, 12.0]          # <-- the three requested gaps

with open(os.path.join(os.path.dirname(__file__),
          "..", "sabari_project", "backend", "model", "serving_meta.json")) as f:
    SMETA = json.load(f)
TAU_HIGH = SMETA["tau_high"]
TAU_LOW  = SMETA["tau_low"]

SEP = "=" * 92

# ─────────────────────────────────────────────────────────────────────────────
# SECTION A  — ALL ANCHORS: horizon × sensitivity × gap
# ─────────────────────────────────────────────────────────────────────────────
print(SEP)
print("SECTION A — ALL ANCHORS: Episode-gap (6h / 8h / 12h) × Sensitivity × Horizon")
print(SEP)

all_rows = []
for h in HORIZONS:
    col = f"p_calibrated_{h}h"
    csub, cy = known_subset(calib, h)
    tsub, ty = known_subset(test,  h)
    if len(ty) == 0 or ty.sum() == 0:
        continue
    base = float(ty.mean())

    for st in SENS_TARGETS:
        thr = ec.select_threshold(csub[col].values, cy, st)
        row_c = ec.row_confusion(ty, tsub[col].values, thr)

        for gap in EPISODE_GAPS:
            epm = ec.episode_metrics(tsub, col, thr, ty, gap_h=gap)
            ep_lift = ec.lift(epm["episode_ppv"], base)
            row_c_fpr = 1.0 - row_c["specificity"]

            rec = dict(
                horizon=h, sens_target=int(st * 100),
                gap_h=int(gap), threshold=round(thr, 5),
                # row-level
                row_sensitivity=round(row_c["sensitivity"], 4),
                row_specificity=round(row_c["specificity"], 4),
                row_ppv=round(row_c["ppv"], 4),
                row_fpr=round(row_c_fpr, 4),
                # episode-level
                n_episodes=epm["n_episodes"],
                n_true_ep=epm["n_true_episodes"],
                n_false_ep=epm["n_false_episodes"],
                episode_ppv=round(epm["episode_ppv"], 4),
                episode_fpr=round(1 - epm["episode_ppv"], 4),
                episode_lift=round(ep_lift, 3),
                patient_recall=round(epm["patient_recall"], 4),
                alarms_d100=round(epm["episodes_per_patient_day"] * 100, 1),
                median_lead_h=round(epm["median_lead_time_h"], 1),
                base_rate=round(base, 4),
            )
            all_rows.append(rec)

df_all = pd.DataFrame(all_rows)

# print grouped by gap
for gap in EPISODE_GAPS:
    print(f"\n{'─'*92}")
    print(f"  EPISODE GAP = {int(gap)}h  (two alerting bursts ≤ {int(gap)}h apart → counted as ONE alarm episode)")
    print(f"{'─'*92}")
    sub = df_all[df_all.gap_h == gap].copy()
    print(f"  {'Horizon':>7}  {'Sens%':>6}  {'Thr':>7}  {'RowSens':>8}  {'RowSpec':>8}  "
          f"{'RowPPV':>8}  {'EpPPV':>8}  {'EpFPR':>8}  {'EpLIFT':>8}  {'PatRec':>8}  "
          f"{'Alrms/d/100':>12}  {'LeadH':>6}")
    for _, r in sub.iterrows():
        print(f"  {r.horizon:>6}h  {r.sens_target:>5}%  {r.threshold:>7.5f}  "
              f"{r.row_sensitivity:>8.4f}  {r.row_specificity:>8.4f}  "
              f"{r.row_ppv:>8.4f}  {r.episode_ppv:>8.4f}  {r.episode_fpr:>8.4f}  "
              f"{r.episode_lift:>8.3f}x  {r.patient_recall:>8.4f}  "
              f"{r.alarms_d100:>12.1f}  {r.median_lead_h:>6.1f}")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION B — NON-VACUOUS: gap × sensitivity (24h horizon)
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("SECTION B — NON-VACUOUS (NEWS2 < 7 at anchor): Gap (6h/8h/12h) × Sensitivity @ 24h")
print("  Hysteresis computed over FULL known set FIRST to preserve latch state.")
print(SEP)

col_24 = "p_calibrated_24h"
csub_24, cy_24 = known_subset(calib, 24)
tsub_24, ty_24 = known_subset(test,  24)
nv_base = float(ty_24[tsub_24["news2_at_anchor"].values < 7].mean())

nv_rows = []
for st in SENS_TARGETS:
    thr_st = ec.select_threshold(csub_24[col_24].values, cy_24, st)
    tau_l  = thr_st / 2.0   # symmetric deadband: tau_low = half of tau_high

    # hysteresis over full known set → then restrict to news2 < 7
    hyst_full = ec.hysteresis_alert(tsub_24, col_24, thr_high=thr_st, thr_low=tau_l)
    tsub_nv = tsub_24.copy()
    tsub_nv["_h"] = hyst_full.astype(float)

    nv_mask = tsub_nv["news2_at_anchor"].values < 7
    nv_df   = tsub_nv.loc[nv_mask]
    nv_y    = ty_24[nv_mask]
    if len(nv_y) == 0: continue

    for gap in EPISODE_GAPS:
        epm = ec.episode_metrics(nv_df, "_h", 0.5, nv_y, gap_h=gap)
        ep_lift = ec.lift(epm["episode_ppv"], nv_base)

        nv_rows.append(dict(
            sens_target=int(st * 100), gap_h=int(gap),
            threshold=round(thr_st, 5),
            n_episodes=epm["n_episodes"],
            n_true_ep=epm["n_true_episodes"],
            n_false_ep=epm["n_false_episodes"],
            episode_ppv=round(epm["episode_ppv"], 4),
            episode_fpr=round(1 - epm["episode_ppv"], 4),
            episode_lift=round(ep_lift, 3),
            patient_recall=round(epm["patient_recall"], 4),
            alarms_d100=round(epm["episodes_per_patient_day"] * 100, 1),
            median_lead_h=round(epm["median_lead_time_h"], 1),
        ))

df_nv = pd.DataFrame(nv_rows)

for gap in EPISODE_GAPS:
    print(f"\n{'─'*92}")
    print(f"  NON-VACUOUS  |  EPISODE GAP = {int(gap)}h  |  24h horizon  "
          f"|  Base rate = {nv_base:.4f} ({100*nv_base:.2f}%)")
    print(f"{'─'*92}")
    sub = df_nv[df_nv.gap_h == gap]
    print(f"  {'Sens%':>6}  {'Thr':>7}  {'Episodes':>9}  {'TrueEp':>7}  {'FalseEp':>8}  "
          f"{'EpPPV':>8}  {'EpFPR':>8}  {'EpLIFT':>8}  {'PatRec':>8}  "
          f"{'Alrms/d/100':>12}  {'LeadH':>6}")
    for _, r in sub.iterrows():
        print(f"  {r.sens_target:>5}%  {r.threshold:>7.5f}  {r.n_episodes:>9,}  "
              f"{r.n_true_ep:>7,}  {r.n_false_ep:>8,}  "
              f"{r.episode_ppv:>8.4f}  {r.episode_fpr:>8.4f}  {r.episode_lift:>8.3f}x  "
              f"{r.patient_recall:>8.4f}  {r.alarms_d100:>12.1f}  {r.median_lead_h:>6.1f}")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION C — NON-VACUOUS for ALL horizons, deployed sensitivity (80%)
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("SECTION C — NON-VACUOUS @ 80% Sensitivity: Gap × Horizon (all horizons)")
print(SEP)

nv_all_rows = []
for h in HORIZONS:
    col = f"p_calibrated_{h}h"
    csub_h, cy_h = known_subset(calib, h)
    tsub_h, ty_h = known_subset(test,  h)
    if len(ty_h) == 0 or "news2_at_anchor" not in tsub_h.columns: continue
    thr = ec.select_threshold(csub_h[col].values, cy_h, 0.80)
    tau_l = thr / 2.0
    nv_base_h = float(ty_h[tsub_h["news2_at_anchor"].values < 7].mean())

    hyst_h = ec.hysteresis_alert(tsub_h, col, thr_high=thr, thr_low=tau_l)
    tsub_nv_h = tsub_h.copy()
    tsub_nv_h["_h"] = hyst_h.astype(float)
    nv_mask_h = tsub_nv_h["news2_at_anchor"].values < 7
    nv_h   = tsub_nv_h.loc[nv_mask_h]
    nv_y_h = ty_h[nv_mask_h]

    for gap in EPISODE_GAPS:
        epm = ec.episode_metrics(nv_h, "_h", 0.5, nv_y_h, gap_h=gap)
        ep_lift = ec.lift(epm["episode_ppv"], nv_base_h)
        nv_all_rows.append(dict(
            horizon=h, gap_h=int(gap),
            n_nv_anchors=len(nv_h), base_rate=round(nv_base_h, 4),
            n_episodes=epm["n_episodes"],
            n_true_ep=epm["n_true_episodes"],
            episode_ppv=round(epm["episode_ppv"], 4),
            episode_fpr=round(1 - epm["episode_ppv"], 4),
            episode_lift=round(ep_lift, 3),
            patient_recall=round(epm["patient_recall"], 4),
            alarms_d100=round(epm["episodes_per_patient_day"] * 100, 1),
            median_lead_h=round(epm["median_lead_time_h"], 1),
        ))

df_nv_all = pd.DataFrame(nv_all_rows)
for gap in EPISODE_GAPS:
    print(f"\n  {'─'*88}")
    print(f"  NON-VACUOUS  |  EPISODE GAP = {int(gap)}h  |  80% sensitivity")
    print(f"  {'─'*88}")
    sub = df_nv_all[df_nv_all.gap_h == gap]
    print(f"  {'Horizon':>8}  {'NV_anchors':>10}  {'BaseRate':>9}  {'Episodes':>9}  "
          f"{'TrueEp':>7}  {'EpPPV':>8}  {'EpFPR':>8}  {'EpLIFT':>8}  "
          f"{'PatRec':>8}  {'Alrms/d/100':>12}  {'LeadH':>6}")
    for _, r in sub.iterrows():
        print(f"  {r.horizon:>7}h  {r.n_nv_anchors:>10,}  {r.base_rate:>9.4f}  "
              f"{r.n_episodes:>9,}  {r.n_true_ep:>7,}  {r.episode_ppv:>8.4f}  "
              f"{r.episode_fpr:>8.4f}  {r.episode_lift:>8.3f}x  "
              f"{r.patient_recall:>8.4f}  {r.alarms_d100:>12.1f}  {r.median_lead_h:>6.1f}")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION D — BEST CONFIG FINDER
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("SECTION D — BEST CONFIGURATION FINDER (across gap × sensitivity × horizon)")
print(SEP)

# best PPV where patient recall >= 80%
cand = df_all[df_all.patient_recall >= 0.80].sort_values("episode_ppv", ascending=False)
b = cand.iloc[0]
print(f"\n  Best Episode PPV (recall ≥ 80%):  horizon={b.horizon}h  gap={b.gap_h}h  "
      f"sens={b.sens_target}%  PPV={100*b.episode_ppv:.2f}%  LIFT={b.episode_lift}x  "
      f"recall={100*b.patient_recall:.2f}%  alarms={b.alarms_d100}/d/100  lead={b.median_lead_h}h")

# best recall
b2 = df_all.sort_values("patient_recall", ascending=False).iloc[0]
print(f"  Best Patient Recall:              horizon={b2.horizon}h  gap={b2.gap_h}h  "
      f"sens={b2.sens_target}%  recall={100*b2.patient_recall:.2f}%  PPV={100*b2.episode_ppv:.2f}%  "
      f"alarms={b2.alarms_d100}/d/100")

# best balance: highest PPV × Recall product (F1-episode proxy)
df_all["f1_ep"] = 2 * df_all["episode_ppv"] * df_all["patient_recall"] / (df_all["episode_ppv"] + df_all["patient_recall"])
b3 = df_all.sort_values("f1_ep", ascending=False).iloc[0]
print(f"  Best F1-episode (PPV×Recall):     horizon={b3.horizon}h  gap={b3.gap_h}h  "
      f"sens={b3.sens_target}%  PPV={100*b3.episode_ppv:.2f}%  recall={100*b3.patient_recall:.2f}%  "
      f"F1={b3.f1_ep:.4f}  alarms={b3.alarms_d100}/d/100")

# fewest alarms with recall >= 90%
cand2 = df_all[df_all.patient_recall >= 0.90].sort_values("alarms_d100")
b4 = cand2.iloc[0]
print(f"  Fewest alarms (recall ≥ 90%):     horizon={b4.horizon}h  gap={b4.gap_h}h  "
      f"sens={b4.sens_target}%  alarms={b4.alarms_d100}/d/100  PPV={100*b4.episode_ppv:.2f}%  "
      f"recall={100*b4.patient_recall:.2f}%  lead={b4.median_lead_h}h")

# best non-vacuous PPV
b5 = df_nv.sort_values("episode_ppv", ascending=False).iloc[0]
print(f"  Best Non-Vacuous Episode PPV:     gap={b5.gap_h}h  sens={b5.sens_target}%  "
      f"PPV={100*b5.episode_ppv:.2f}%  FPR={100*b5.episode_fpr:.2f}%  "
      f"recall={100*b5.patient_recall:.2f}%  lead={b5.median_lead_h}h")

print(f"\n{SEP}")
print("DONE — gap_sensitivity_report.py")
print(SEP)
