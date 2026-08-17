"""
Stage 07 — Show example per-patient predictions from the held-out test set.

For a handful of representative anchors, print what the model outputs:
  NEWS2 now, risk percentile, predicted median time, calibrated 5-95% band,
  and the ACTUAL outcome (did they deteriorate, and when).
Run: py -3 07_examples.py
"""
from __future__ import annotations
import numpy as np, pandas as pd
import config

df = pd.read_parquet(config.dpath("preds_test.parquet")).copy()
df["risk"] = 1.0 / np.clip(df["pred_median"], 1e-3, None)      # higher = sooner
df["risk_pct"] = df["risk"].rank(pct=True) * 100               # 0-100 percentile

def show(rows, title):
    print(f"\n=== {title} ===")
    print(f"{'pt':>4}{'NEWS2':>7}{'risk %ile':>10}{'pred median':>13}"
          f"{'calib 5-95% band':>20}{'ACTUAL outcome':>26}")
    for i, (_, r) in enumerate(rows.iterrows(), 1):
        band = f"{r['conf_lo']:.1f}-{r['conf_hi']:.1f} h"
        if r["event"] == 1:
            actual = f"deteriorated at {r['T_hours']:.1f} h"
            inside = "in-band" if r["conf_lo"] <= r["T_hours"] <= r["conf_hi"] else "OUT"
            actual += f"  [{inside}]"
        else:
            actual = f"no event ({r['cause']})"
        dcm = "*" if r["dcm_flag"] else " "
        print(f"{i:>3}{dcm}{r['news2_at_anchor']:>7.0f}{r['risk_pct']:>9.0f}%"
              f"{r['pred_median']:>11.0f} h {band:>20}{actual:>26}")

events = df[df.event == 1].sort_values("risk", ascending=False)
cens = df[df.event == 0]

# high-risk patients who genuinely deteriorated soon
show(events.head(4), "HIGH-RISK anchors that truly deteriorated (model flagged them)")
# a DCM event example
dcm_ev = events[events.dcm_flag]
if len(dcm_ev):
    show(dcm_ev.head(2), "DCM patients who deteriorated")
# low-risk patients who stayed stable (true negatives)
show(cens.sort_values("risk").head(3), "LOW-RISK anchors that stayed stable (correctly quiet)")
# high-risk but censored (the false-alarm tendency, shown honestly)
show(cens.sort_values("risk", ascending=False).head(3), "HIGH-RISK anchors that did NOT deteriorate (false alarms)")

print(f"\n* = DCM patient.  'pred median' is the raw point estimate (runs long under censoring);")
print(f"the calibrated band + risk percentile are the trustworthy outputs.")
print(f"\nHeadline: among the top-10% highest-risk test anchors, "
      f"{df[df.risk_pct>=90].event.mean()*100:.0f}% went on to deteriorate "
      f"vs {df[df.risk_pct<90].event.mean()*100:.0f}% of the rest.")
