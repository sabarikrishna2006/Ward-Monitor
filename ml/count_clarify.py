import pandas as pd, sys, os
sys.path.insert(0, os.path.dirname(__file__))
import config
from known_status import known_subset

preds = pd.read_parquet(config.dpath("preds_ordinal_esc.parquet"))

print("=== TOTAL PATIENTS (unique stays) per split ===")
for split in ["train", "calib", "test"]:
    s = preds[preds.split == split]
    print(f"  {split:6s}: {s['stay_id'].nunique():>5,} unique stays  ({len(s):>7,} patient-hours)")

total_stays = preds["stay_id"].nunique()
total_hrs   = len(preds)
train_calib = preds[preds.split.isin(["train","calib"])]
print(f"  TOTAL : {total_stays:>5,} unique stays  ({total_hrs:>7,} patient-hours)")
print(f"\n  Train+Calib (model trained+calibrated on): {train_calib['stay_id'].nunique():,} unique stays")

print()
print("=== NEWS2 < 7 CASES (non-vacuous patient-hours and stays) ===")
for split in ["train", "calib", "test", "ALL"]:
    s = preds if split == "ALL" else preds[preds.split == split]
    nv = s[s["news2_at_anchor"] < 7]
    print(f"  {split:6s}: {nv['stay_id'].nunique():>5,} stays with >=1 NEWS2<7 hour  "
          f"({len(nv):>7,} NV hrs out of {len(s):>7,} total hrs = {100*len(nv)/len(s):.1f}%)")

print()
print("=== TEST SPLIT DETAIL (known outcome at 24h) ===")
test  = preds[preds.split == "test"]
tsub, ty = known_subset(test, 24)
nv_mask = tsub["news2_at_anchor"].values < 7
nv_stays_test = tsub.loc[nv_mask, "stay_id"].nunique()
print(f"  Test stays total:                      {test['stay_id'].nunique():,}")
print(f"  Test stays with known outcome at 24h:  {tsub['stay_id'].nunique():,}")
print(f"  Of those, stays with >=1 NEWS2<7 hour: {nv_stays_test:,}")
print(f"  Non-vacuous patient-hours in test:     {nv_mask.sum():,}  (out of {len(tsub):,} known-status hours = {100*nv_mask.sum()/len(tsub):.1f}%)")
print()
print("  The 903 figure from previous run was stays with known outcome at 24h.")
print(f"  Of those 903 stays, {nv_stays_test} had at least one hour where NEWS2 was still <7.")
