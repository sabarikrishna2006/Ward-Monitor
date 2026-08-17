"""
Stage 21 — The comparison tables. Reads whatever model artefacts exist and
produces two things:

  A. ARCHITECTURE ABLATION (2x2, isolating what the professor's suggestion
     actually changes):

                    | independent per interval | shared / pooled
        XGBoost     | A  12_ordinal_train      | B  16_pooled_xgb_train
        MLP         | --                       | C  17_mlp_ordinal_train
                    |                          | D  18_mlp_cumulative_train

     His proposal moves from A to C, changing BOTH the sharing and the base
     learner. B changes only the sharing; D changes only the target
     parameterisation relative to C. With all four, any difference is
     attributable to one axis instead of a bundle.

  B. THE LABEL 2x2 — "is v2 a better training signal, or just a harder target?"

     Lower lift under label v2 is ambiguous on its own: a looser label adds
     harder events, so the task itself got harder, and lift can fall even if the
     label is an improvement. The disambiguating experiment is to cross
     TRAIN-label with EVAL-label on THE SAME PATIENTS:

                          evaluated on v1 labels | evaluated on v2 labels
        trained on v1     |        (i)           |        (ii)
        trained on v2     |       (iii)          |        (iv)

     If (iii) > (i)  -> the v2-trained model is better at the ORIGINAL task too,
                        so v2 is a genuinely better training signal and the lower
                        headline lift is just the harder target.
     If (iii) <= (i) -> v2 bought nothing; it is only a harder target. Say so.

     This comparison is only valid because 03_train.three_way_split is now
     deterministic per subject_id — under the old GroupShuffleSplit the two builds
     agreed on just 53% of split assignments, so the two models were being scored
     on different people.

Run: PYTHONUTF8=1 py -3 21_ablation_report.py
"""
from __future__ import annotations

import importlib
import json
import logging
import os

import numpy as np
import pandas as pd

import eval_core as ec
from known_status import known_subset

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ablation")

PRIMARY_H = 12

CELLS = {
    "A_xgb_independent": ("preds_ordinal", "models_ordinal", "7 independent XGBoost boosters"),
    "B_xgb_pooled": ("preds_pooled_xgb", "models_pooled_xgb", "1 XGBoost, interval_j as feature"),
    "C_mlp_hazard": ("preds_mlp_ordinal", "models_mlp_ordinal", "shared trunk + 7 hazard heads"),
    "D_mlp_cumulative": ("preds_mlp_cumulative", "models_mlp_cumulative",
                         "shared trunk + 7 monotone cumulative heads (paper Eq 2)"),
}
LABELS = {"v1": "news2", "v2": "news2_v2lab"}


def _cfg(tag):
    os.environ["EWS_TAG"] = tag
    import config
    importlib.reload(config)
    return config


def load_cell(tag, stem, model_dir):
    cfg = _cfg(tag)
    ppath = cfg.tpath(f"{stem}.parquet")
    if not os.path.exists(ppath):
        return None, None
    preds = pd.read_parquet(ppath)
    mpath = os.path.join(cfg.tpath(model_dir), "meta.json")
    meta = json.load(open(mpath)) if os.path.exists(mpath) else {}
    return preds, meta


def c_index_from_meta(meta):
    for k in ("c_index_hazard_test", "c_index_test"):
        if k in meta:
            ci = meta.get("c_index_hazard_test_ci") or meta.get("c_index_test_ci")
            return meta[k], ci
    return None, None


# ══════════════════════════════════════════════════════════════════════════
def architecture_table(horizons=(6, 12, 24)):
    rows = []
    for lab, tag in LABELS.items():
        for cell, (stem, mdir, desc) in CELLS.items():
            preds, meta = load_cell(tag, stem, mdir)
            if preds is None:
                continue
            cal, te = preds[preds.split == "calib"].copy(), preds[preds.split == "test"].copy()
            c, ci = c_index_from_meta(meta)
            from sklearn.metrics import roc_auc_score, average_precision_score
            for h in horizons:
                r = ec.evaluate_horizon(cal, te, h)
                col = f"p_calibrated_{int(h)}h"
                tsub, ty = known_subset(te, h)
                try:
                    auc = float(roc_auc_score(ty, tsub[col].values))
                    auprc = float(average_precision_score(ty, tsub[col].values))
                except Exception:
                    auc = auprc = float("nan")
                rows.append(dict(
                    label=lab, cell=cell, description=desc, horizon=h,
                    c_index=c, c_index_ci=ci,
                    base_rate=r["base_rate"], n_events=r["n_events"], n_known=r["n_known"],
                    auc=auc, auprc=auprc,
                    # AUPRC's no-skill floor IS the base rate (not 0.5) -- quoting AUPRC
                    # without it is meaningless, so carry the ratio explicitly.
                    auprc_over_baserate=auprc / r["base_rate"] if r["base_rate"] else float("nan"),
                    row_ppv=r["row"]["ppv"], row_sens=r["row"]["sensitivity"],
                    row_spec=r["row"]["specificity"], row_lift=r["row_lift"],
                    episode_ppv=r["episode"]["episode_ppv"], episode_lift=r["episode_lift"],
                    patient_recall=r["episode"]["patient_recall"],
                    episodes_per_patient_day=r["episode"]["episodes_per_patient_day"],
                    median_lead_time_h=r["episode"]["median_lead_time_h"],
                ))
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════
def label_2x2(h=PRIMARY_H, stem="preds_ordinal", mdir="models_ordinal"):
    """Cross TRAIN-label with EVAL-label on the SAME test anchors."""
    p1, _ = load_cell(LABELS["v1"], stem, mdir)
    p2, _ = load_cell(LABELS["v2"], stem, mdir)
    if p1 is None or p2 is None:
        return None

    key = ["stay_id", "anchor_time"]
    score_cols = [c for c in p1.columns if c.startswith("p_calibrated_")]

    # sanity: with the stable split the same patient must be in the same split
    s1 = p1.groupby("subject_id")["split"].first()
    s2 = p2.groupby("subject_id")["split"].first()
    common_subj = s1.index.intersection(s2.index)
    agreement = float((s1.loc[common_subj] == s2.loc[common_subj]).mean())
    assert agreement == 1.0, (
        f"split assignment agrees on only {agreement:.2%} of subjects — the label "
        f"comparison would be confounded. Retrain with the stable three_way_split.")

    a = p1[key + ["split", "T_hours", "event", "subject_id"] + score_cols]
    b = p2[key + ["split", "T_hours", "event"] + score_cols]
    j = a.merge(b, on=key, suffixes=("_m1", "_m2"))

    out = {"split_agreement": agreement, "n_common_anchors": int(len(j)), "horizon": h}
    col = f"p_calibrated_{h}h"
    for eval_lab, tsuf in (("v1", "_m1"), ("v2", "_m2")):
        # ground truth comes from the EVAL label's own T_hours/event
        base = j.rename(columns={f"T_hours{tsuf}": "T_hours", f"event{tsuf}": "event",
                                 f"split{tsuf}": "split"})
        cal_all = base[base["split"] == "calib"]
        te_all = base[base["split"] == "test"]
        for train_lab, msuf in (("v1", "_m1"), ("v2", "_m2")):
            cal = cal_all.rename(columns={f"{col}{msuf}": col})
            te = te_all.rename(columns={f"{col}{msuf}": col})
            csub, cy = known_subset(cal, h)
            tsub, ty = known_subset(te, h)
            thr = ec.select_threshold(csub[col].values, cy, 0.80)
            m = ec.episode_metrics(tsub, col, thr, ty)
            br = float(np.mean(ty))
            try:
                from sklearn.metrics import roc_auc_score, average_precision_score
                auc = float(roc_auc_score(ty, tsub[col].values))
                auprc = float(average_precision_score(ty, tsub[col].values))
            except Exception:
                auc = auprc = float("nan")
            out[f"train_{train_lab}__eval_{eval_lab}"] = dict(
                base_rate=br, auc=auc, auprc=auprc,
                episode_ppv=m["episode_ppv"], episode_lift=ec.lift(m["episode_ppv"], br),
                patient_recall=m["patient_recall"],
                episodes_per_patient_day=m["episodes_per_patient_day"],
                n_events=int(np.sum(ty)), n_known=len(tsub))
    return out


# ══════════════════════════════════════════════════════════════════════════
def main():
    tbl = architecture_table()
    if len(tbl) == 0:
        log.error("no model artefacts found — train at least cell A first")
        return
    _cfg("news2")
    tbl.to_csv(os.path.join("data", "ablation_table.csv"), index=False)

    print("\n" + "=" * 108)
    print("A. ARCHITECTURE ABLATION — test set, threshold fit on CALIBRATION split")
    print("=" * 108)
    for lab in tbl["label"].unique():
        sub = tbl[tbl.label == lab]
        print(f"\n  LABEL {lab}")
        cidx = sub.drop_duplicates("cell")[["cell", "c_index", "c_index_ci"]]
        print(f"    {'cell':22} {'C-index':>9}  95% CI")
        for r in cidx.itertuples():
            ci = f"[{r.c_index_ci[0]:.4f}, {r.c_index_ci[1]:.4f}]" if r.c_index_ci else ""
            c = f"{r.c_index:.4f}" if r.c_index is not None else "n/a"
            print(f"    {r.cell:22} {c:>9}  {ci}")
        for h in sorted(sub.horizon.unique()):
            s = sub[sub.horizon == h]
            print(f"\n    horizon {h}h  (base rate {s.base_rate.iloc[0]:.4f} = AUPRC no-skill floor, "
                  f"{s.n_events.iloc[0]:,} events of {s.n_known.iloc[0]:,} known anchors)")
            print(f"      {'cell':22} {'AUC':>7} {'AUPRC':>7} {'AUPRC/base':>10} {'sens':>7} "
                  f"{'spec':>7} {'row-PPV':>8} {'ep-PPV':>8} {'ep-LIFT':>8} {'recall':>8} "
                  f"{'ep/day':>7} {'lead':>5}")
            for r in s.itertuples():
                print(f"      {r.cell:22} {r.auc:>7.4f} {r.auprc:>7.4f} {r.auprc_over_baserate:>10.2f} "
                      f"{r.row_sens:>7.4f} {r.row_spec:>7.4f} {r.row_ppv:>8.4f} "
                      f"{r.episode_ppv:>8.4f} {r.episode_lift:>8.3f} {r.patient_recall:>8.4f} "
                      f"{r.episodes_per_patient_day:>7.3f} {r.median_lead_time_h:>5.1f}")

    x = label_2x2()
    if x:
        print("\n" + "=" * 108)
        print(f"B. LABEL 2x2 — same {x['n_common_anchors']:,} common anchors, "
              f"split agreement {x['split_agreement']:.1%}")
        print("   'is v2 a better TRAINING SIGNAL, or just a harder TARGET?'")
        print("=" * 108)
        print(f"   {'':>28} {'base':>7} {'AUC':>7} {'AUPRC':>7} {'ep-PPV':>8} "
              f"{'ep-LIFT':>8} {'recall':>8}")
        for ev in ("v1", "v2"):
            for tr in ("v1", "v2"):
                k = f"train_{tr}__eval_{ev}"
                d = x[k]
                print(f"   {k:>28} {d['base_rate']:>7.4f} {d['auc']:>7.4f} {d['auprc']:>7.4f} "
                      f"{d['episode_ppv']:>8.4f} {d['episode_lift']:>8.3f} "
                      f"{d['patient_recall']:>8.4f}")
        i = x["train_v1__eval_v1"]; iii = x["train_v2__eval_v1"]
        d_auc = iii["auc"] - i["auc"]
        d_lift = iii["episode_lift"] - i["episode_lift"]
        print(f"\n   DECIDING COMPARISON (both graded on the ORIGINAL v1 label):")
        print(f"     trained on v1 -> AUC {i['auc']:.4f}, ep-lift {i['episode_lift']:.3f}")
        print(f"     trained on v2 -> AUC {iii['auc']:.4f}, ep-lift {iii['episode_lift']:.3f}")
        print(f"     delta          AUC {d_auc:+.4f}, ep-lift {d_lift:+.3f}")
        verdict = ("v2 is a better TRAINING SIGNAL (it improves the ORIGINAL task too)"
                   if d_auc > 0.002 else
                   "v2 is only a HARDER TARGET -- it does not improve the original task")
        print(f"     VERDICT: {verdict}")
        x["verdict"] = verdict
        x["delta_auc_trainv2_minus_trainv1_on_v1_labels"] = float(d_auc)
        x["delta_lift_trainv2_minus_trainv1_on_v1_labels"] = float(d_lift)
        with open(os.path.join("data", "label_2x2.json"), "w") as f:
            json.dump(x, f, indent=2, default=float)
    print("=" * 108 + "\n")
    log.info("wrote data/ablation_table.csv and data/label_2x2.json")


if __name__ == "__main__":
    main()
