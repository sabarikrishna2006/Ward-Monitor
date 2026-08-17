"""
make_feature_allowlist.py — prune a trained model's feature set by summed gain.

WHY. Cell D trained on 371 features against only 1,475 event-stays and produced a
train/test C-index gap of 0.0686 (train 0.8466, test 0.7780), up from 0.0505 with 55
features. The reported AUC is therefore optimistic. The JAMIA 2024 review of 14
deployed deterioration systems is the prior: every system that reduced in-hospital
mortality used **fewer than 39 variables**, and the two largest (CHARTwatch 526,
HBI 349) degraded worst when actually deployed.

Gain is summed ACROSS THE SEVEN INTERVAL BOOSTERS, not taken from one, because a
feature can matter only at long horizons (e.g. a 12h trend) and would be discarded by
looking at a single booster.

FAMILY-AWARE PRUNING. A pure top-N-by-gain cut is biased against variables that are
spread over many features: heart rate has 19 features averaging ~124 gain each, while
anion gap concentrates 3,874 gain into 12. Top-N would keep all the anion gap and drop
the heart rate, even though the heart-rate FAMILY carries 4.6% of total gain. So each
family keeps at least `min_per_family` of its own best features before the global
top-N is applied.

Run: PYTHONUTF8=1 EWS_TAG=esc py -3 make_feature_allowlist.py \
         --model-dir models_ordinal_mw --top 80 --out feature_allowlist_esc.json
"""
from __future__ import annotations

import argparse
import json
import os
import re

import pandas as pd
import xgboost as xgb

import config

FAMILY_PATTERNS = [
    (r"anion_gap", "anion_gap"), (r"hco3", "hco3"), (r"lactate", "lactate"),
    (r"base_excess", "base_excess"), (r"ph_art|ph_l|\bph_", "ph"),
    (r"shock_index", "shock_index"), (r"^map|map_", "map"),
    (r"sbp", "sbp"), (r"dbp", "dbp"), (r"heart_rate", "heart_rate"),
    (r"resp_rate", "resp_rate"), (r"spo2", "spo2"), (r"temperature", "temperature"),
    (r"news2", "news2"), (r"creatinine|bun_|egfr", "renal"), (r"urine", "urine"),
    (r"troponin", "troponin"), (r"on_|_rate|n_infusions|any_rate", "infusion"),
    (r"alarm|params_checked", "nurse_concern"), (r"hrs_since", "staleness"),
    (r"braden", "frailty"), (r"gcs|mental", "neuro"),
    (r"potassium|sodium|chloride|magnesium|calcium|phosph", "electrolytes"),
    (r"wbc|platelet|hemoglob|hematocr|inr|\bpt\b", "haem_coag"),
    (r"fio2|o2_flow|on_oxygen", "oxygen"), (r"weight", "weight"),
    (r"age|is_female|hours_|already_high|dcm", "context"),
]


def family(f: str) -> str:
    for pat, name in FAMILY_PATTERNS:
        if re.search(pat, f):
            return name
    return "other"


def summed_gain(model_dir: str, feats: list[str]) -> pd.Series:
    agg: dict[str, float] = {}
    for h in config.HORIZONS_H:
        p = os.path.join(model_dir, f"hazard_interval_{h}h.json")
        b = xgb.Booster()
        b.load_model(p)
        for k, v in b.get_score(importance_type="gain").items():
            name = feats[int(k[1:])]
            agg[name] = agg.get(name, 0.0) + float(v)
    return pd.Series(agg).sort_values(ascending=False)


def main(model_dir_name: str, top: int, min_per_family: int, out_name: str):
    mdir = config.tpath(model_dir_name)
    meta = json.load(open(os.path.join(mdir, "meta.json")))
    feats = meta["features"]
    S = summed_gain(mdir, feats)
    tot = S.sum()

    fam = S.index.map(family)
    keep: set[str] = set()
    # 1) protect each family's best few, so a family spread thin is not wiped out
    for f in sorted(set(fam)):
        keep.update(S[fam == f].head(min_per_family).index)
    # 2) then fill up to `top` with the globally strongest remaining features
    for name in S.index:
        if len(keep) >= top:
            break
        keep.add(name)
    keep = sorted(keep)

    kept_gain = S[S.index.isin(keep)].sum()
    print(f"features with nonzero gain : {len(S)}")
    print(f"kept                       : {len(keep)}")
    print(f"gain retained              : {kept_gain/tot:.1%}")
    print()
    kf = pd.Series(keep).map(family).value_counts()
    af = pd.Series(S.index).map(family).value_counts()
    print(f"  {'family':16} {'kept':>5} {'of':>5} {'family gain retained':>22}")
    for f in af.index:
        g_all = S[fam == f].sum()
        g_keep = S[(fam == f) & S.index.isin(keep)].sum()
        print(f"  {f:16} {int(kf.get(f,0)):>5} {int(af[f]):>5} {g_keep/max(g_all,1e-9):>21.1%}")

    path = config.dpath(out_name)
    with open(path, "w") as fh:
        json.dump(dict(source_model=model_dir_name, n_source_features=len(feats),
                       n_nonzero_gain=len(S), n_kept=len(keep),
                       gain_retained=float(kept_gain / tot),
                       top=top, min_per_family=min_per_family,
                       features=keep), fh, indent=2)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default="models_ordinal_mw")
    ap.add_argument("--top", type=int, default=80)
    ap.add_argument("--min-per-family", type=int, default=2)
    ap.add_argument("--out", default="feature_allowlist.json")
    a = ap.parse_args()
    main(a.model_dir, a.top, a.min_per_family, a.out)
