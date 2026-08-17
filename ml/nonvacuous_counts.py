"""
nonvacuous_counts.py
====================
Answers Prof. Shroff's exact question:
  "Calculate the number of cases where there is a non-vacuous prediction
   (news2 not reached yet and alarm predicted) and the false-positives
   and recall for these cases."

Unit of a "case" = one distinct PATIENT STAY (not a patient-hour).
We also report patient-hour counts for completeness.

Run:
    cd common_db_main_latest/ml
    PYTHONUTF8=1 py -3 nonvacuous_counts.py
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

# ── load test split only ────────────────────────────────────────────────────
preds = pd.read_parquet(config.dpath("preds_ordinal_esc.parquet"))
test  = preds[preds.split == "test"].copy()
calib = preds[preds.split == "calib"].copy()

# We report at 24h horizon (the deployed horizon)
H     = 24
COL   = f"p_calibrated_{H}h"

# ── get deployed thresholds ─────────────────────────────────────────────────
with open(os.path.join(os.path.dirname(__file__),
          "..", "sabari_project", "backend", "model", "serving_meta.json")) as f:
    meta = json.load(f)
TAU_HIGH = meta["tau_high"]  # alarm fires when score >= this
TAU_LOW  = meta["tau_low"]   # hysteresis release

# Also compute the threshold calibration-split-derived at 80% sensitivity
csub, cy = known_subset(calib, H)
THR_80 = ec.select_threshold(csub[COL].values, cy, 0.80)

print("=" * 72)
print("NON-VACUOUS PREDICTION COUNTS — for Prof. Shroff")
print("=" * 72)
print(f"\nHorizon:              {H}h")
print(f"Deployed τ_high:      {TAU_HIGH:.5f}  (alarm fires when predicted risk ≥ this)")
print(f"Deployed τ_low:       {TAU_LOW:.5f}  (hysteresis release)")
print(f"80%-sensitivity thr:  {THR_80:.5f}  (calibration-derived, for comparison)")

# ── Step 1: restrict to known-status rows at 24h ────────────────────────────
tsub, ty = known_subset(test, H)
N_KNOWN  = len(tsub)
N_STAYS  = tsub["stay_id"].nunique()

print(f"\n{'─'*72}")
print("STEP 1 — FULL KNOWN-STATUS TEST SET (24h horizon)")
print(f"{'─'*72}")
print(f"  Total known-status patient-hours:    {N_KNOWN:>8,}")
print(f"  Unique test stays (patients):        {N_STAYS:>8,}")
print(f"  Patient-hours that ARE events:       {int(ty.sum()):>8,}  ({100*ty.mean():.2f}% base rate)")
print(f"  Patient-hours that are NOT events:   {int((ty==0).sum()):>8,}")

# ── Step 2: split into vacuous vs non-vacuous ────────────────────────────────
nv_mask = tsub["news2_at_anchor"].values < 7    # non-vacuous: NEWS2 not yet reached
v_mask  = ~nv_mask                              # vacuous: NEWS2 already >= 7

nv_df   = tsub.loc[nv_mask].copy()
nv_y    = ty[nv_mask]
v_df    = tsub.loc[v_mask].copy()
v_y     = ty[v_mask]

print(f"\n{'─'*72}")
print("STEP 2 — VACUOUS vs NON-VACUOUS SPLIT")
print(f"  Definition: NON-VACUOUS = NEWS2 < 7 at the moment of the alarm")
print(f"              VACUOUS     = NEWS2 ≥ 7 already (model not relevant)")
print(f"{'─'*72}")
print(f"  NON-VACUOUS patient-hours (NEWS2 < 7):  {len(nv_df):>7,}  ({100*len(nv_df)/N_KNOWN:.1f}%)")
print(f"  VACUOUS patient-hours   (NEWS2 ≥ 7):   {len(v_df):>7,}  ({100*len(v_df)/N_KNOWN:.1f}%)")

# stays that have AT LEAST ONE non-vacuous anchor
nv_stays = nv_df["stay_id"].nunique()
v_stays  = v_df["stay_id"].nunique()
print(f"\n  Unique stays with ≥1 non-vacuous hour: {nv_stays:>7,}  (out of {N_STAYS:,} total)")
print(f"  Unique stays with ≥1 vacuous hour:     {v_stays:>7,}")

# ── Step 3: compute hysteresis alarm over FULL known set (latch preservation) ─
hyst_full = ec.hysteresis_alert(tsub, COL, thr_high=TAU_HIGH, thr_low=TAU_LOW)
tsub_full = tsub.copy()
tsub_full["_alarm"] = hyst_full.astype(int)

# now split
nv_alm_df = tsub_full.loc[nv_mask]
v_alm_df  = tsub_full.loc[v_mask]

# ── PATIENT-HOUR level counts ────────────────────────────────────────────────
print(f"\n{'─'*72}")
print("STEP 3 — PATIENT-HOUR COUNTS (alarm = hysteresis latch active)")
print(f"{'─'*72}")

# Non-vacuous
nv_alarm_hrs   = int(nv_alm_df["_alarm"].sum())
nv_event_hrs   = int(nv_y.sum())
nv_tp_hrs      = int(((nv_alm_df["_alarm"].values == 1) & (nv_y == 1)).sum())
nv_fp_hrs      = int(((nv_alm_df["_alarm"].values == 1) & (nv_y == 0)).sum())
nv_fn_hrs      = int(((nv_alm_df["_alarm"].values == 0) & (nv_y == 1)).sum())
nv_tn_hrs      = int(((nv_alm_df["_alarm"].values == 0) & (nv_y == 0)).sum())
nv_precision   = nv_tp_hrs / (nv_tp_hrs + nv_fp_hrs) if (nv_tp_hrs + nv_fp_hrs) else float("nan")
nv_recall_hrs  = nv_tp_hrs / (nv_tp_hrs + nv_fn_hrs) if (nv_tp_hrs + nv_fn_hrs) else float("nan")
nv_fpr_hrs     = nv_fp_hrs / (nv_fp_hrs + nv_tn_hrs) if (nv_fp_hrs + nv_tn_hrs) else float("nan")

print(f"\n  NON-VACUOUS (NEWS2 < 7) — patient-hour level:")
print(f"    Total non-vacuous hours:             {len(nv_alm_df):>8,}")
print(f"    Hours with ALARM active:             {nv_alarm_hrs:>8,}  ({100*nv_alarm_hrs/len(nv_alm_df):.1f}% of NV hours)")
print(f"    True-event hours (label=1):          {nv_event_hrs:>8,}  ({100*nv_event_hrs/len(nv_alm_df):.2f}% base rate)")
print(f"    TP hours (alarm=1, event=1):         {nv_tp_hrs:>8,}")
print(f"    FP hours (alarm=1, event=0):         {nv_fp_hrs:>8,}  ← the false positives")
print(f"    FN hours (alarm=0, event=1):         {nv_fn_hrs:>8,}")
print(f"    TN hours (alarm=0, event=0):         {nv_tn_hrs:>8,}")
print(f"    Row-level PPV (precision):           {nv_precision:.4f}  ({100*nv_precision:.2f}%)")
print(f"    Row-level FPR  (FP/all negatives):   {nv_fpr_hrs:.4f}  ({100*nv_fpr_hrs:.2f}%)")
print(f"    Row-level Recall (TP/all events):    {nv_recall_hrs:.4f}  ({100*nv_recall_hrs:.2f}%)")

# ── PATIENT-STAY level counts (what the prof is really asking) ───────────────
print(f"\n{'─'*72}")
print("STEP 4 — PATIENT COUNTS (the clinical unit — one stay = one patient)")
print(f"{'─'*72}")

# stays that had at least one non-vacuous hour
nv_stay_df = nv_alm_df.groupby("stay_id").agg(
    has_alarm   = ("_alarm", "max"),
    has_event   = ("event",  "max"),
    nv_event_hrs = ("event", "sum"),   # using ty would be cleaner but need merge
).reset_index()

# join with ty-based event label (label_at: event AND T<=24h)
# build per-stay event label from nv_y
nv_alm_df2 = nv_alm_df.copy()
nv_alm_df2["_nv_label"] = nv_y
stay_labels = nv_alm_df2.groupby("stay_id")["_nv_label"].max().reset_index()
stay_labels.columns = ["stay_id", "event_at_24h"]
nv_stay_df = nv_stay_df.merge(stay_labels, on="stay_id", how="left")

# patient counts
n_nv_stays          = len(nv_stay_df)                                     # all stays with ≥1 NV hour
n_event_stays       = int(nv_stay_df["event_at_24h"].sum())               # will deteriorate within 24h
n_nonevent_stays    = n_nv_stays - n_event_stays

# cases that fired an alarm
n_alarm_stays       = int(nv_stay_df["has_alarm"].sum())
n_no_alarm_stays    = n_nv_stays - n_alarm_stays

# TP/FP/FN/TN at stay level
n_tp_stays = int(((nv_stay_df["has_alarm"]==1) & (nv_stay_df["event_at_24h"]==1)).sum())
n_fp_stays = int(((nv_stay_df["has_alarm"]==1) & (nv_stay_df["event_at_24h"]==0)).sum())
n_fn_stays = int(((nv_stay_df["has_alarm"]==0) & (nv_stay_df["event_at_24h"]==1)).sum())
n_tn_stays = int(((nv_stay_df["has_alarm"]==0) & (nv_stay_df["event_at_24h"]==0)).sum())

stay_ppv    = n_tp_stays / (n_tp_stays + n_fp_stays) if (n_tp_stays + n_fp_stays) else float("nan")
stay_recall = n_tp_stays / (n_tp_stays + n_fn_stays) if (n_tp_stays + n_fn_stays) else float("nan")
stay_spec   = n_tn_stays / (n_tn_stays + n_fp_stays) if (n_tn_stays + n_fp_stays) else float("nan")
stay_fpr    = 1.0 - stay_spec

print(f"\n  POPULATION: stays that had ≥1 non-vacuous hour (NEWS2<7 at some point)")
print(f"    Total such patient stays:                    {n_nv_stays:>6,}")
print(f"    Of these, will deteriorate within 24h:       {n_event_stays:>6,}  ({100*n_event_stays/n_nv_stays:.1f}%)")
print(f"    Of these, will NOT deteriorate within 24h:   {n_nonevent_stays:>6,}  ({100*n_nonevent_stays/n_nv_stays:.1f}%)")
print()
print(f"  ALARM COUNTS (at patient-stay level):")
print(f"    Stays that received ≥1 non-vacuous alarm:    {n_alarm_stays:>6,}  ({100*n_alarm_stays/n_nv_stays:.1f}%)")
print(f"    Stays that received NO alarm:                {n_no_alarm_stays:>6,}  ({100*n_no_alarm_stays/n_nv_stays:.1f}%)")
print()
print(f"  CONFUSION MATRIX (patient stays):")
print(f"    TP — alarmed AND will deteriorate:           {n_tp_stays:>6,}  (correctly warned)")
print(f"    FP — alarmed AND will NOT deteriorate:       {n_fp_stays:>6,}  ← FALSE POSITIVES (alarm was wrong)")
print(f"    FN — NOT alarmed AND will deteriorate:       {n_fn_stays:>6,}  (missed patients)")
print(f"    TN — NOT alarmed AND will NOT deteriorate:   {n_tn_stays:>6,}  (correctly silent)")
print()
print(f"  METRICS:")
print(f"    Recall  (TP / all deteriorating):  {stay_recall:.4f}  = {n_tp_stays}/{n_tp_stays+n_fn_stays}  = {100*stay_recall:.2f}%")
print(f"    PPV     (TP / all alarmed):        {stay_ppv:.4f}  = {n_tp_stays}/{n_tp_stays+n_fp_stays}  = {100*stay_ppv:.2f}%")
print(f"    Spec    (TN / all non-event):      {stay_spec:.4f}  = {n_tn_stays}/{n_tn_stays+n_fp_stays}  = {100*stay_spec:.2f}%")
print(f"    FPR     (FP / all non-event):      {stay_fpr:.4f}  = {n_fp_stays}/{n_tn_stays+n_fp_stays}  = {100*stay_fpr:.2f}%")
print(f"    False alarm ratio:                 {n_fp_stays/(n_tp_stays+n_fp_stays):.4f}  = {n_fp_stays}/{n_tp_stays+n_fp_stays}  = {100*n_fp_stays/(n_tp_stays+n_fp_stays):.2f}%  (1-PPV)")

# ── One-line summary for slack ────────────────────────────────────────────────
print(f"\n{'─'*72}")
print("SLACK-READY SUMMARY")
print(f"{'─'*72}")
print(f"""
Non-vacuous cases (NEWS2 < 7 at alarm time, 24h prediction horizon):

  Total non-vacuous patient-hours analysed: {len(nv_alm_df):,}
  Stays with ≥1 non-vacuous alarm:          {n_alarm_stays:,}  (out of {n_nv_stays:,} stays with NEWS2<7 observed)

  Of those alarmed stays:
    → TRUE positives  (alarm correct):      {n_tp_stays:,}  patients who actually deteriorated
    → FALSE positives (alarm wrong):        {n_fp_stays:,}  patients who did NOT deteriorate

  Recall   (how many deteriorating patients were warned): {n_tp_stays}/{n_tp_stays+n_fn_stays} = {100*stay_recall:.1f}%
  PPV      (how many alarms were correct):                {n_tp_stays}/{n_tp_stays+n_fp_stays}  = {100*stay_ppv:.1f}%
  FP rate  (false alarms / all non-event stays):          {n_fp_stays}/{n_tn_stays+n_fp_stays} = {100*stay_fpr:.1f}%
""")

print("=" * 72)
print("DONE")
print("=" * 72)
