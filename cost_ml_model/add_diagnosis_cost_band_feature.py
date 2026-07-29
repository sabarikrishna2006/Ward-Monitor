"""
Adds `primary_diagnosis_cost_band_*` one-hot columns to dcm_model_ready_data.csv,
supplementing (not replacing) the existing primary_diagnosis_grouped_* (top-15 +
Other) columns already in there.

Why: only ~15 of 1,317 distinct primary diagnoses get their own feature today;
the other ~1,302 all collapse into "Other" with zero cost signal. This adds a
4-tier shrinkage-adjusted cost band (Low/Mid-Low/Mid-High/High, k=3) so every
diagnosis -- including the ones that fall into "Other" -- carries real cost
information. See cost_ml_model/data/diagnosis_cost_bucketing_ppt_notes.md for
the full methodology + leave-one-out validation.

Input:  data/dcm_model_ready_data.csv (existing, from eda_and_preprocessing.py)
        data/dcm_admissions_static.csv (hadm_id -> primary_diagnosis)
Output: data/dcm_model_ready_data.csv (overwritten, 4 new columns added)
        data/dcm_model_ready_data_pre_diagnosis_band_backup.csv (safety copy of the old version)
        data/diagnosis_cost_bands_shrunk.csv (recomputed, should match the earlier k=3 table)
"""
import os
import pandas as pd
import numpy as np

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
K = 3

def main():
    model_ready = pd.read_csv(os.path.join(DATA_DIR, "dcm_model_ready_data.csv"))
    static = pd.read_csv(os.path.join(DATA_DIR, "dcm_admissions_static.csv"))[["hadm_id", "primary_diagnosis"]]

    if any(c.startswith("primary_diagnosis_cost_band_") for c in model_ready.columns):
        print("diagnosis_cost_band columns already present -- nothing to do.")
        return

    backup_path = os.path.join(DATA_DIR, "dcm_model_ready_data_pre_diagnosis_band_backup.csv")
    if not os.path.exists(backup_path):
        model_ready.to_csv(backup_path, index=False)
        print(f"Backed up pre-band dataset to {backup_path}")

    # ── Recompute shrinkage bands (k=3) from admission-level data, one row per hadm_id ──
    per_admission = static.merge(
        model_ready[["hadm_id", "total_bill_at_discharge"]].drop_duplicates("hadm_id"),
        on="hadm_id",
    ).dropna(subset=["primary_diagnosis", "total_bill_at_discharge"])

    pop_avg = per_admission["total_bill_at_discharge"].mean()
    grp = per_admission.groupby("primary_diagnosis")["total_bill_at_discharge"]
    stats = grp.agg(n="count", avg_cost="mean").reset_index()
    stats["shrunk_avg"] = (stats["n"] * stats["avg_cost"] + K * pop_avg) / (stats["n"] + K)
    stats["band"] = pd.qcut(stats["shrunk_avg"], 4, labels=["Low", "Mid-Low", "Mid-High", "High"])
    _bands_path = os.path.join(DATA_DIR, "diagnosis_cost_bands_shrunk.csv")
    try:
        stats.to_csv(_bands_path, index=False)
    except PermissionError:
        print(f"WARNING: {_bands_path} is locked (open in Excel?) -- skipping this write, "
              f"using freshly computed bands in-memory for the rest of this run anyway.")
    print(f"Population avg: Rs {pop_avg:,.0f}  |  {len(stats)} distinct diagnoses banded (k={K})")
    print(stats["band"].value_counts())

    # ── Map every row's diagnosis -> band, one-hot encode, attach to model_ready ──
    diag_to_band = stats.set_index("primary_diagnosis")["band"]
    hadm_to_diag = static.set_index("hadm_id")["primary_diagnosis"]
    hadm_to_band = hadm_to_diag.map(diag_to_band)

    band_series = model_ready["hadm_id"].map(hadm_to_band)
    missing = band_series.isna().sum()
    if missing:
        # Unseen hadm_id/diagnosis (shouldn't happen in this closed dataset) -> Mid-Low (near population avg)
        print(f"WARNING: {missing} rows had no diagnosis/band match -- defaulting to Mid-Low")
        band_series = band_series.fillna("Mid-Low")

    band_onehot = pd.get_dummies(band_series, prefix="primary_diagnosis_cost_band", dtype=int)
    for col in ["primary_diagnosis_cost_band_Low", "primary_diagnosis_cost_band_Mid-Low",
                "primary_diagnosis_cost_band_Mid-High", "primary_diagnosis_cost_band_High"]:
        if col not in band_onehot.columns:
            band_onehot[col] = 0

    model_ready_new = pd.concat([model_ready, band_onehot], axis=1)
    out_path = os.path.join(DATA_DIR, "dcm_model_ready_data.csv")
    model_ready_new.to_csv(out_path, index=False)
    print(f"\nAdded {band_onehot.shape[1]} columns: {list(band_onehot.columns)}")
    print(f"dcm_model_ready_data.csv: {model_ready.shape} -> {model_ready_new.shape}")

if __name__ == "__main__":
    main()
