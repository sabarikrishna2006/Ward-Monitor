"""
Task 2 (Phase 2) -- Test whether feeding the model's own Day-0 prediction
forward as an input feature for later days actually helps, and how sensitive
that benefit is to the Day-0 anchor being imperfect (as it realistically
always is -- Day-0 MAPE is already known to be ~76-106%).

Three variants, all same XGBoost params as train_baseline_and_xgboost.py:
  A (baseline)     -- no day0_estimate feature (already trained: xgb_point.joblib)
  B (with estimate)-- + day0_estimate column, broadcast per admission
  C (noisy estimate)-- same as B, but day0_estimate has noise injected first

day0_estimate is generated via a dedicated Day-0-only sub-model, using
OUT-OF-FOLD predictions for training admissions (5-fold, by subject_id) so
the feature isn't a leaked, overfit proxy for the true label on training rows.

Input:  cost_ml_model/data/dcm_model_ready_data.csv
        cost_ml_model/data/train_test_split_hadm_ids.csv
        cost_ml_model/data/dcm_admissions_static.csv
Output: cost_ml_model/models/{day0_subB, day0_subC, xgb_variantB, xgb_variantC}.joblib
        cost_ml_model/data/eval_day0_estimate_variants_by_day.csv
        cost_ml_model/eval_charts/day0_estimate_variants_mape.png
"""
import os
import numpy as np
import pandas as pd
import joblib
from sklearn.model_selection import train_test_split, KFold
from sklearn.metrics import mean_absolute_error
from xgboost import XGBRegressor
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
CHART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_charts")

TARGET = "total_bill_at_discharge"
TARGET_LOG = f"{TARGET}_log"
KEY_COLS = ["hadm_id", TARGET, TARGET_LOG]

XGB_PARAMS = dict(
    n_estimators=300, max_depth=6, learning_rate=0.05,
    subsample=0.8, colsample_bytree=0.8, random_state=42, n_jobs=-1,
)
EARLY_STOPPING_ROUNDS = 20
NOISE_STD = 0.30  # relative noise injected for Variant C -- still gentler than
                   # real Day-0 error (Day-0 MAPE is ~76-106%), a controlled test


def fit_day0_model(day0_rows, feature_cols, seed=42):
    model = XGBRegressor(objective="reg:squarederror", random_state=seed, **{
        k: v for k, v in XGB_PARAMS.items() if k != "random_state"})
    model.fit(day0_rows[feature_cols], day0_rows[TARGET_LOG], verbose=False)
    return model


def generate_day0_estimates(df, day0_feature_cols, train_subject_ids, other_subject_ids, subj_map):
    """Returns a Series indexed by hadm_id: day0_estimate (Rs) for every admission
    in train_subject_ids (out-of-fold) and other_subject_ids (val+test, single model)."""
    day0 = df[df["hospital_day"] == 0].copy()
    day0["subject_id"] = day0["hadm_id"].map(subj_map)

    train_day0 = day0[day0["subject_id"].isin(train_subject_ids)]
    other_day0 = day0[day0["subject_id"].isin(other_subject_ids)]

    # --- Out-of-fold for training admissions (5-fold by subject_id) ---
    train_subjects_arr = np.array(sorted(train_subject_ids))
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    oof_estimates = pd.Series(index=train_day0["hadm_id"], dtype=float)

    for fold_i, (fit_idx, hold_idx) in enumerate(kf.split(train_subjects_arr)):
        fit_subjects = set(train_subjects_arr[fit_idx])
        hold_subjects = set(train_subjects_arr[hold_idx])
        fit_rows = train_day0[train_day0["subject_id"].isin(fit_subjects)]
        hold_rows = train_day0[train_day0["subject_id"].isin(hold_subjects)]
        if len(hold_rows) == 0:
            continue
        fold_model = fit_day0_model(fit_rows, day0_feature_cols, seed=42 + fold_i)
        preds = np.expm1(fold_model.predict(hold_rows[day0_feature_cols]))
        oof_estimates.loc[hold_rows["hadm_id"]] = preds

    print(f"Out-of-fold day0_estimate generated for {oof_estimates.notna().sum()} / {len(train_day0)} train admissions")

    # --- Single model on ALL training admissions, applied to val+test (no leakage there) ---
    full_train_model = fit_day0_model(train_day0, day0_feature_cols, seed=42)
    other_preds = np.expm1(full_train_model.predict(other_day0[day0_feature_cols]))
    other_estimates = pd.Series(other_preds, index=other_day0["hadm_id"])

    joblib.dump({"model": full_train_model, "features": day0_feature_cols},
                os.path.join(MODEL_DIR, "day0_estimator_full_train.joblib"))

    all_estimates = pd.concat([oof_estimates, other_estimates])
    return all_estimates


def train_variant(df, feature_cols, train_mask, val_mask, label):
    X_train, y_train = df.loc[train_mask, feature_cols], df.loc[train_mask, TARGET_LOG]
    X_val, y_val = df.loc[val_mask, feature_cols], df.loc[val_mask, TARGET_LOG]
    model = XGBRegressor(objective="reg:squarederror", eval_metric="mae",
                          early_stopping_rounds=EARLY_STOPPING_ROUNDS, **XGB_PARAMS)
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    print(f"{label}: best_iteration = {model.best_iteration} / {XGB_PARAMS['n_estimators']}")
    return model


DAY_BINS = [-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 40, 1000]
DAY_LABELS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11-20", "21-40", "41+"]


def mape_by_day(y_true, y_pred, day, label):
    err = (y_true - y_pred).abs()
    pct = err / y_true.replace(0, np.nan) * 100
    day_bin = pd.cut(day, DAY_BINS, labels=DAY_LABELS)
    out = pd.DataFrame({"day_bin": day_bin, "abs_err": err, "pct_err": pct}).groupby(
        "day_bin", observed=True).agg(n=("abs_err", "size"), mae=("abs_err", "mean"),
                                       mape=("pct_err", "mean")).reset_index()
    out.columns = ["day_bin", "n", f"mae_{label}", f"mape_{label}"]
    return out


def main():
    os.makedirs(MODEL_DIR, exist_ok=True)
    os.makedirs(CHART_DIR, exist_ok=True)

    df = pd.read_csv(os.path.join(DATA_DIR, "dcm_model_ready_data.csv"))
    split = pd.read_csv(os.path.join(DATA_DIR, "train_test_split_hadm_ids.csv"))
    static = pd.read_csv(os.path.join(DATA_DIR, "dcm_admissions_static.csv"))
    subj_map = static.set_index("hadm_id")["subject_id"]
    df["subject_id"] = df["hadm_id"].map(subj_map)

    train_ids = set(split[split["split"] == "train"]["hadm_id"])
    val_ids = set(split[split["split"] == "val"]["hadm_id"])
    test_ids = set(split[split["split"] == "test"]["hadm_id"])
    train_subjects = set(static[static["hadm_id"].isin(train_ids)]["subject_id"])
    val_subjects = set(static[static["hadm_id"].isin(val_ids)]["subject_id"])
    test_subjects = set(static[static["hadm_id"].isin(test_ids)]["subject_id"])

    train_mask = df["hadm_id"].isin(train_ids)
    val_mask = df["hadm_id"].isin(val_ids)
    test_mask = df["hadm_id"].isin(test_ids)

    xgb_feature_cols = [c for c in df.columns if c not in KEY_COLS and not c.endswith("_scaled")
                         and c != "subject_id"]

    print("=" * 70)
    print("STEP 1: Generate day0_estimate (out-of-fold for train, single model for val+test)")
    print("=" * 70)
    day0_estimates = generate_day0_estimates(
        df, xgb_feature_cols, train_subjects, val_subjects | test_subjects, subj_map)
    df["day0_estimate"] = df["hadm_id"].map(day0_estimates)
    missing = df["day0_estimate"].isna().sum()
    print(f"Rows with day0_estimate assigned: {(~df['day0_estimate'].isna()).sum()} / {len(df)} (missing: {missing})")
    df["day0_estimate"] = df["day0_estimate"].fillna(df["day0_estimate"].median())

    rng = np.random.RandomState(42)
    df["day0_estimate_noisy"] = df["day0_estimate"] * (1 + rng.normal(0, NOISE_STD, size=len(df)))
    df["day0_estimate_noisy"] = df["day0_estimate_noisy"].clip(lower=0)

    df[["hadm_id", "hospital_day", "day0_estimate", "day0_estimate_noisy"]].to_csv(
        os.path.join(DATA_DIR, "dcm_day0_estimates.csv"), index=False)

    print("\n" + "=" * 70)
    print("STEP 2: Train Variant B (with clean day0_estimate) and Variant C (noisy)")
    print("=" * 70)
    feature_cols_B = xgb_feature_cols + ["day0_estimate"]
    feature_cols_C = xgb_feature_cols + ["day0_estimate_noisy"]

    model_B = train_variant(df, feature_cols_B, train_mask, val_mask, "Variant B (clean estimate)")
    model_C = train_variant(df, feature_cols_C, train_mask, val_mask, "Variant C (noisy estimate)")

    joblib.dump({"model": model_B, "features": feature_cols_B}, os.path.join(MODEL_DIR, "xgb_variantB.joblib"))
    joblib.dump({"model": model_C, "features": feature_cols_C}, os.path.join(MODEL_DIR, "xgb_variantC.joblib"))

    print("\n" + "=" * 70)
    print("STEP 3: Compare Variant A (baseline) vs. B vs. C on the TEST set")
    print("=" * 70)
    bundle_A = joblib.load(os.path.join(MODEL_DIR, "xgb_point.joblib"))
    model_A, feature_cols_A = bundle_A["model"], bundle_A["features"]

    test_df = df.loc[test_mask].copy()
    y_true = test_df[TARGET]
    pred_A = np.expm1(model_A.predict(test_df[feature_cols_A]))
    pred_B = np.expm1(model_B.predict(test_df[feature_cols_B]))
    pred_C = np.expm1(model_C.predict(test_df[feature_cols_C]))

    for label, pred in [("A (baseline, no estimate)", pred_A),
                         ("B (with clean estimate)", pred_B),
                         ("C (with noisy estimate)", pred_C)]:
        mae = mean_absolute_error(y_true, pred)
        mape = ((y_true - pred).abs() / y_true.replace(0, np.nan) * 100).mean()
        print(f"{label:32s}  MAE = Rs {mae:>12,.0f}   MAPE = {mape:.1f}%")

    by_day_A = mape_by_day(y_true, pred_A, test_df["hospital_day"], "A")
    by_day_B = mape_by_day(y_true, pred_B, test_df["hospital_day"], "B")
    by_day_C = mape_by_day(y_true, pred_C, test_df["hospital_day"], "C")
    merged = by_day_A.merge(by_day_B[["day_bin", "mae_B", "mape_B"]], on="day_bin") \
                      .merge(by_day_C[["day_bin", "mae_C", "mape_C"]], on="day_bin")
    print("\nBy hospital_day (MAPE %):")
    print(merged[["day_bin", "n", "mape_A", "mape_B", "mape_C"]].to_string(
        index=False, formatters={c: "{:.1f}%".format for c in ["mape_A", "mape_B", "mape_C"]}))
    merged.to_csv(os.path.join(DATA_DIR, "eval_day0_estimate_variants_by_day.csv"), index=False)

    fig, ax = plt.subplots(figsize=(9, 5))
    x = range(len(merged))
    ax.plot(x, merged["mape_A"], color="#7F8C8D", linewidth=2, marker="o", markersize=5, label="A: baseline (no estimate)")
    ax.plot(x, merged["mape_B"], color="#27AE60", linewidth=2, marker="o", markersize=5, label="B: with clean estimate")
    ax.plot(x, merged["mape_C"], color="#C0392B", linewidth=2, marker="o", markersize=5, label="C: with noisy estimate")
    ax.set_xticks(list(x))
    ax.set_xticklabels(merged["day_bin"])
    ax.set_xlabel("Hospital Day")
    ax.set_ylabel("MAPE (%)")
    ax.set_title("Does Feeding the Model's Day-0 Estimate Forward Help? (A vs B vs C)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper right")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "day0_estimate_variants_mape.png"), dpi=130)
    plt.close(fig)
    print(f"\nSaved chart -> {os.path.join(CHART_DIR, 'day0_estimate_variants_mape.png')}")


if __name__ == "__main__":
    main()
