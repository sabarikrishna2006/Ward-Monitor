"""
Stage 06 — Verify train vs test are statistically similar (covariate balance).

Reproduces the exact 03_train split, then for key columns reports:
  - train vs test mean
  - Standardised Mean Difference (SMD): |SMD| < 0.1 = negligible difference
  - Kolmogorov-Smirnov p-value: high p = distributions indistinguishable
  - missingness rate (for labs)
Run: py -3 06_split_check.py
"""
from __future__ import annotations
import numpy as np, pandas as pd
from sklearn.model_selection import GroupShuffleSplit
from scipy.stats import ks_2samp
import config

df = pd.read_parquet(config.dpath("features.parquet"))

# ---- reproduce the identical 70/15/15 group split from 03_train.py ----
g = df["subject_id"].values; idx = np.arange(len(df))
rest_i, test_i = next(GroupShuffleSplit(1, test_size=0.15, random_state=config.RANDOM_SEED).split(idx, groups=g))
tr_i, cal_i = next(GroupShuffleSplit(1, test_size=0.1765, random_state=config.RANDOM_SEED).split(rest_i, groups=g[rest_i]))
tr, te = df.iloc[rest_i[tr_i]], df.iloc[test_i]

print(f"train: {len(tr):>7} rows / {tr.subject_id.nunique():>5} patients | "
      f"event {tr.event.mean():.3f} | DCM {tr.dcm_flag.mean():.3f}")
print(f"test : {len(te):>7} rows / {te.subject_id.nunique():>5} patients | "
      f"event {te.event.mean():.3f} | DCM {te.dcm_flag.mean():.3f}")
print(f"overlap of patients between train & test: "
      f"{len(set(tr.subject_id) & set(te.subject_id))}  (must be 0)\n")

def smd(a, b):
    a, b = a.astype(float), b.astype(float)
    ma, mb = a.mean(), b.mean()
    sd = np.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
    return 0.0 if sd == 0 else (ma - mb) / sd

cols = ["T_hours", "event", "dcm_flag", "age", "is_female", "charlson", "hours_since_adm",
        "news2_last", "news2_rate", "heart_rate_last", "resp_rate_last", "spo2_last",
        "sbp_last", "egfr", "nt_probnp_last", "lactate_last", "urine_rate_24h", "creatinine_last"]

print(f"{'feature':<18}{'train_mean':>12}{'test_mean':>12}{'SMD':>8}{'KS p':>9}{'flag':>6}")
print("-" * 65)
worst = 0.0
for c in cols:
    if c not in df: continue
    a, b = tr[c].dropna(), te[c].dropna()
    s = smd(a, b)
    worst = max(worst, abs(s))
    try:
        p = ks_2samp(a, b).pvalue
    except Exception:
        p = float("nan")
    flag = "  <-- " if abs(s) >= 0.1 else ""
    print(f"{c:<18}{a.mean():>12.3f}{b.mean():>12.3f}{s:>8.3f}{p:>9.3f}{flag:>6}")

print("\nlab missingness (train vs test):")
for c in [x for x in df.columns if x.endswith("_missing")]:
    print(f"  {c:<22} train {tr[c].mean():.3f}  test {te[c].mean():.3f}")

print(f"\nLargest |SMD| across all checked features: {worst:.3f}  "
      f"({'BALANCED (all < 0.1)' if worst < 0.1 else 'some imbalance >= 0.1'})")
