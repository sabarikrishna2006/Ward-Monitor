"""
Task 4 (Phase 2, redesigned per Ashmit) -- Build a day-wise "remaining length
of stay" sub-model (re-predicted every day, not a static Day-0 guess), feed
its OUT-OF-FOLD prediction into the cost model as a new feature, and test
whether it actually improves cost estimation -- properly isolated via a
3-way ablation so we know WHICH change helped, not just a bundled number:

  A -- original baseline (already trained: xgb_point.joblib)
  E -- baseline features + new engineered features (no LOS prediction)
  F -- baseline features + new engineered features + predicted_remaining_days

New engineered features added (senior-ML-judgment call, not in the dataset
before): cumulative_icu_days_so_far, cumulative_procedures_so_far,
cumulative_medicines_so_far, cumulative_labs_so_far (running counts -- how
"active" the clinical course has been so far), and cost_trend_ratio
(today's spend vs. the running average -- a decelerating trend may signal
approaching discharge). These were named in the original plan's schema but
never actually built into the final dataset.

LOS sub-model target: remaining_days = los_days_total - hospital_day (the
residual, not total LOS -- same reasoning as the final-cost-vs-remaining-cost
debate: hospital_day is already known, so predicting the genuinely unknown
remaining part forces real learning instead of free credit from known info).
Generated out-of-fold for ALL training rows (5-fold by subject_id, across
every hospital_day, not just Day 0) to avoid the same leakage trap Variant D
fell into.

Input:  cost_ml_model/data/dcm_model_ready_data.csv, dcm_admissions_static.csv,
        train_test_split_hadm_ids.csv
Output: cost_ml_model/models/{los_predictor_full_train, xgb_variantE, xgb_variantF}.joblib
        cost_ml_model/data/eval_los_feature_variants_by_day.csv
        cost_ml_model/eval_charts/los_feature_variants_mape.png
"""
import os
import numpy as np
import pandas as pd
import joblib
from sklearn.model_selection import KFold
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

XGB_PARAMS = dict(n_estimators=300, max_depth=6, learning_rate=0.05,
                   subsample=0.8, colsample_bytree=0.8, random_state=42, n_jobs=-1)
EARLY_STOPPING_ROUNDS = 20

DAY_BINS = [-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 40, 1000]
DAY_LABELS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11-20", "21-40", "41+"]


def add_engineered_features(df):
    df = df.sort_values(["hadm_id", "hospital_day"]).copy()
    g = df.groupby("hadm_id")
    df["cumulative_icu_days_so_far"] = g["was_in_icu_today"].cumsum()
    df["cumulative_procedures_so_far"] = g["had_procedure_today"].cumsum()
    df["cumulative_medicines_so_far"] = g["had_medicine_today"].cumsum()
    df["cumulative_labs_so_far"] = g["had_lab_today"].cumsum()
    df["cost_trend_ratio"] = (df["day_total_cost"] / df["cost_per_day_so_far"].replace(0, np.nan)).fillna(1.0)
    return df


NEW_FEATURES = ["cumulative_icu_days_so_far", "cumulative_procedures_so_far",
                 "cumulative_medicines_so_far", "cumulative_labs_so_far", "cost_trend_ratio"]


def fit_xgb(train_rows, feature_cols, target_col, seed=42):
    model = XGBRegressor(objective="reg:squarederror", random_state=seed,
                          **{k: v for k, v in XGB_PARAMS.items() if k != "random_state"})
    model.fit(train_rows[feature_cols], train_rows[target_col], verbose=False)
    return model


def generate_oof_los_predictions(df, feature_cols, train_subjects, other_subjects):
    train_rows = df[df["subject_id"].isin(train_subjects)]
    other_rows = df[df["subject_id"].isin(other_subjects)]

    train_subjects_arr = np.array(sorted(train_subjects))
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    oof = pd.Series(index=train_rows.index, dtype=float)

    for fold_i, (fit_idx, hold_idx) in enumerate(kf.split(train_subjects_arr)):
        fit_subjects = set(train_subjects_arr[fit_idx])
        hold_subjects = set(train_subjects_arr[hold_idx])
        fit_rows = train_rows[train_rows["subject_id"].isin(fit_subjects)]
        hold_rows = train_rows[train_rows["subject_id"].isin(hold_subjects)]
        if len(hold_rows) == 0:
            continue
        fold_model = fit_xgb(fit_rows, feature_cols, "remaining_days_log", seed=42 + fold_i)
        preds = np.expm1(fold_model.predict(hold_rows[feature_cols]))
        oof.loc[hold_rows.index] = preds

    print(f"Out-of-fold remaining_days predicted for {oof.notna().sum()} / {len(train_rows)} training rows")

    full_train_model = fit_xgb(train_rows, feature_cols, "remaining_days_log", seed=42)
    other_preds = pd.Series(np.expm1(full_train_model.predict(other_rows[feature_cols])), index=other_rows.index)
    joblib.dump({"model": full_train_model, "features": feature_cols},
                os.path.join(MODEL_DIR, "los_predictor_full_train.joblib"))

    all_preds = pd.concat([oof, other_preds]).clip(lower=0)
    return all_preds


def train_variant(df, feature_cols, train_mask, val_mask, label):
    X_train, y_train = df.loc[train_mask, feature_cols], df.loc[train_mask, TARGET_LOG]
    X_val, y_val = df.loc[val_mask, feature_cols], df.loc[val_mask, TARGET_LOG]
    model = XGBRegressor(objective="reg:squarederror", eval_metric="mae",
                          early_stopping_rounds=EARLY_STOPPING_ROUNDS, **XGB_PARAMS)
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    print(f"{label}: best_iteration = {model.best_iteration} / {XGB_PARAMS['n_estimators']}")
    return model


def mape_by_day(y_true, y_pred, day):
    err = (y_true - y_pred).abs()
    pct = err / y_true.replace(0, np.nan) * 100
    day_bin = pd.cut(day, DAY_BINS, labels=DAY_LABELS)
    return pd.DataFrame({"day_bin": day_bin, "abs_err": err, "pct_err": pct}).groupby(
        "day_bin", observed=True).agg(mae=("abs_err", "mean"), mape=("pct_err", "mean")).reset_index()


def main():
    df = pd.read_csv(os.path.join(DATA_DIR, "dcm_model_ready_data.csv"))
    split = pd.read_csv(os.path.join(DATA_DIR, "train_test_split_hadm_ids.csv"))
    static = pd.read_csv(os.path.join(DATA_DIR, "dcm_admissions_static.csv"))
    subj_map = static.set_index("hadm_id")["subject_id"]
    los_map = static.set_index("hadm_id")["los_days_total"]

    df["subject_id"] = df["hadm_id"].map(subj_map)
    df = add_engineered_features(df)

    train_ids = set(split[split["split"] == "train"]["hadm_id"])
    val_ids = set(split[split["split"] == "val"]["hadm_id"])
    test_ids = set(split[split["split"] == "test"]["hadm_id"])
    train_subjects = set(static[static["hadm_id"].isin(train_ids)]["subject_id"])
    val_subjects = set(static[static["hadm_id"].isin(val_ids)]["subject_id"])
    test_subjects = set(static[static["hadm_id"].isin(test_ids)]["subject_id"])

    train_mask = df["hadm_id"].isin(train_ids)
    val_mask = df["hadm_id"].isin(val_ids)
    test_mask = df["hadm_id"].isin(test_ids)

    print("=" * 70)
    print("STEP 1: Build remaining_days target (residual, not total LOS)")
    print("=" * 70)
    df["los_days_total_tmp"] = df["hadm_id"].map(los_map)
    df["remaining_days"] = (df["los_days_total_tmp"] - df["hospital_day"]).clip(lower=0)
    df["remaining_days_log"] = np.log1p(df["remaining_days"])
    df = df.drop(columns=["los_days_total_tmp"])
    print(df.groupby(df["hospital_day"] == 0)["remaining_days"].describe().round(1))

    exclude_cols = set(KEY_COLS) | {"remaining_days", "remaining_days_log", "subject_id"}
    base_feature_cols = [c for c in df.columns if c not in exclude_cols and not c.endswith("_scaled")
                          and c not in NEW_FEATURES]
    los_feature_cols = base_feature_cols + NEW_FEATURES

    print("\n" + "=" * 70)
    print("STEP 2: Out-of-fold remaining-day predictions (day-wise, all rows)")
    print("=" * 70)
    predicted_remaining = generate_oof_los_predictions(
        df, los_feature_cols, train_subjects, val_subjects | test_subjects)
    df["predicted_remaining_days"] = predicted_remaining
    missing = df["predicted_remaining_days"].isna().sum()
    df["predicted_remaining_days"] = df["predicted_remaining_days"].fillna(df["remaining_days"].median())
    print(f"Rows missing a prediction (filled with median): {missing}")

    los_mae = mean_absolute_error(df.loc[test_mask, "remaining_days"], df.loc[test_mask, "predicted_remaining_days"])
    print(f"LOS sub-model itself: test MAE = {los_mae:.1f} days (context, not the main result)")

    print("\n" + "=" * 70)
    print("STEP 3: Train Variant E (+ new features, no LOS) and F (+ new features + LOS)")
    print("=" * 70)
    feature_cols_E = base_feature_cols + NEW_FEATURES
    feature_cols_F = base_feature_cols + NEW_FEATURES + ["predicted_remaining_days"]

    model_E = train_variant(df, feature_cols_E, train_mask, val_mask, "Variant E (+engineered features)")
    model_F = train_variant(df, feature_cols_F, train_mask, val_mask, "Variant F (+engineered features +LOS)")

    joblib.dump({"model": model_E, "features": feature_cols_E}, os.path.join(MODEL_DIR, "xgb_variantE.joblib"))
    joblib.dump({"model": model_F, "features": feature_cols_F}, os.path.join(MODEL_DIR, "xgb_variantF.joblib"))

    print("\n" + "=" * 70)
    print("STEP 4: Compare A (original) vs E vs F on the TEST set")
    print("=" * 70)
    bundle_A = joblib.load(os.path.join(MODEL_DIR, "xgb_point.joblib"))
    test_df = df.loc[test_mask].copy()
    y_true = test_df[TARGET]

    preds = {
        "A": np.expm1(bundle_A["model"].predict(test_df[bundle_A["features"]])),
        "E": np.expm1(model_E.predict(test_df[feature_cols_E])),
        "F": np.expm1(model_F.predict(test_df[feature_cols_F])),
    }
    for label, pred in preds.items():
        mae = mean_absolute_error(y_true, pred)
        mape = ((y_true - pred).abs() / y_true.replace(0, np.nan) * 100).mean()
        print(f"{label}: MAE = Rs {mae:>12,.0f}   MAPE = {mape:.1f}%")

    by_day = {label: mape_by_day(y_true, p, test_df["hospital_day"]) for label, p in preds.items()}
    merged = by_day["A"][["day_bin"]].copy()
    for label in ["A", "E", "F"]:
        merged[f"mape_{label}"] = by_day[label]["mape"].values
        merged[f"mae_{label}"] = by_day[label]["mae"].values
    print("\nBy hospital_day (MAPE %):")
    print(merged[["day_bin", "mape_A", "mape_E", "mape_F"]].to_string(
        index=False, formatters={c: "{:.1f}%".format for c in ["mape_A", "mape_E", "mape_F"]}))
    merged.to_csv(os.path.join(DATA_DIR, "eval_los_feature_variants_by_day.csv"), index=False)

    fig, ax = plt.subplots(figsize=(9, 5))
    x = range(len(merged))
    colors = {"A": "#7F8C8D", "E": "#2E86C1", "F": "#27AE60"}
    labels = {"A": "A: original baseline", "E": "E: + engineered features (no LOS)",
              "F": "F: + engineered features + predicted remaining LOS"}
    for label in ["A", "E", "F"]:
        ax.plot(x, merged[f"mape_{label}"], color=colors[label], linewidth=2, marker="o", markersize=5, label=labels[label])
    ax.set_xticks(list(x))
    ax.set_xticklabels(merged["day_bin"])
    ax.set_xlabel("Hospital Day")
    ax.set_ylabel("MAPE (%)")
    ax.set_title("Does a Day-Wise Predicted Remaining-LOS Feature Improve Cost Estimation?")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper right")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "los_feature_variants_mape.png"), dpi=130)
    plt.close(fig)
    print(f"\nSaved chart -> {os.path.join(CHART_DIR, 'los_feature_variants_mape.png')}")


if __name__ == "__main__":
    main()
