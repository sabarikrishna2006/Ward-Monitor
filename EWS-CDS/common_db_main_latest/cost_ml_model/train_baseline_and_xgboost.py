"""
Task 6 -- Train the Day-0 Linear Regression baseline, then XGBoost point
regression, then XGBoost quantile regression (P10/P50/P90) -- all predicting
total_bill_at_discharge (end-of-day-t framing, see plan's "Prediction timing"
decision).

Split is by subject_id (patient), never by hadm_id or by row -- DCM is a
chronic condition, so ~25% of patients in this cohort have multiple
admissions; splitting by hadm_id alone would let one admission of a patient
land in train and another admission of the SAME patient land in test,
leaking patient-specific characteristics across the split (Ashmit's catch).

Input:  cost_ml_model/data/dcm_model_ready_data.csv
Output: cost_ml_model/models/{baseline_lr, xgb_point, xgb_quantile}.joblib
        cost_ml_model/data/train_test_split_hadm_ids.csv (for Task 7 reuse)
"""
import os
import numpy as np
import pandas as pd
import joblib
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from xgboost import XGBRegressor

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
os.makedirs(MODEL_DIR, exist_ok=True)

TARGET = "total_bill_at_discharge"
TARGET_LOG = f"{TARGET}_log"
KEY_COLS = ["hadm_id", TARGET, TARGET_LOG]
ONEHOT_PREFIXES = ("admission_type_", "insurance_", "primary_diagnosis_grouped_", "treating_specialty_")

# XGBoost params -- reviewed before running per Ashmit's request. ~46k rows x
# ~63 features is small for XGBoost; with early stopping this trains in
# seconds, not minutes.
XGB_PARAMS = dict(
    n_estimators=300,       # ceiling; early stopping will cut this short
    max_depth=6,            # standard depth for tabular data, not deep enough to be slow
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=42,
    n_jobs=-1,
)
EARLY_STOPPING_ROUNDS = 20


def report(name, y_true, y_pred):
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    r2 = r2_score(y_true, y_pred)
    print(f"{name:28s}  MAE = Rs {mae:>12,.0f}   RMSE = Rs {rmse:>12,.0f}   R2 = {r2:.3f}")
    return {"model": name, "mae": mae, "rmse": rmse, "r2": r2}


def main():
    df = pd.read_csv(os.path.join(DATA_DIR, "dcm_model_ready_data.csv"))
    print(f"Loaded {df.shape[0]} rows x {df.shape[1]} cols")

    onehot_cols = [c for c in df.columns if c.startswith(ONEHOT_PREFIXES)]
    lr_feature_cols = ["gender_is_male", "icu_flag", "age_at_admission_scaled"] + onehot_cols
    xgb_feature_cols = [c for c in df.columns if c not in KEY_COLS and not c.endswith("_scaled")]
    print(f"\nLinear Regression (Day-0 baseline) features: {len(lr_feature_cols)}")
    print(f"XGBoost features: {len(xgb_feature_cols)}")

    # --- Split by subject_id (patient), not hadm_id: 60% train / 20% val / 20% test.
    # Every admission belonging to a patient stays entirely within one split
    # (see module docstring -- ~25% of patients here have multiple admissions).
    # val is used ONLY for early stopping; test is never seen until final reporting
    # (using test for early stopping would bias the reported test metrics). ---
    static = pd.read_csv(os.path.join(DATA_DIR, "dcm_admissions_static.csv"))
    hadm_to_subject = static.set_index("hadm_id")["subject_id"]
    df["subject_id"] = df["hadm_id"].map(hadm_to_subject)

    subject_ids = df["subject_id"].unique()
    subj_train, subj_temp = train_test_split(subject_ids, test_size=0.4, random_state=42)
    subj_val, subj_test = train_test_split(subj_temp, test_size=0.5, random_state=42)

    train_mask = df["subject_id"].isin(subj_train)
    val_mask = df["subject_id"].isin(subj_val)
    test_mask = df["subject_id"].isin(subj_test)
    train_ids = df.loc[train_mask, "hadm_id"].unique()
    val_ids = df.loc[val_mask, "hadm_id"].unique()
    test_ids = df.loc[test_mask, "hadm_id"].unique()

    print(f"\nPatients: {len(subject_ids)} total -> {len(subj_train)} train / {len(subj_val)} val / {len(subj_test)} test")
    print(f"Admissions: {df['hadm_id'].nunique()} total -> {len(train_ids)} train / {len(val_ids)} val / {len(test_ids)} test")
    print(f"Rows:       {train_mask.sum()} train / {val_mask.sum()} val / {test_mask.sum()} test")

    leak_check = df.groupby("subject_id")["hadm_id"].apply(
        lambda h: len(set(["train" if x in set(train_ids) else "val" if x in set(val_ids) else "test" for x in h])))
    print(f"Patients whose admissions span multiple splits: {(leak_check > 1).sum()} (should be 0)")
    assert (leak_check > 1).sum() == 0, "Patient-level leakage across splits -- split logic is broken."

    pd.DataFrame({
        "hadm_id": list(train_ids) + list(val_ids) + list(test_ids),
        "split": ["train"] * len(train_ids) + ["val"] * len(val_ids) + ["test"] * len(test_ids),
    }).to_csv(os.path.join(DATA_DIR, "train_test_split_hadm_ids.csv"), index=False)

    results = []

    # ═══════════════════════════════════════════════════════════════
    # 1) Baseline -- Linear Regression, Day-0 only, static features only
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("1) BASELINE -- Linear Regression, Day-0 only, static features only")
    print("=" * 70)
    day0 = df[df["hospital_day"] == 0]
    day0_train = day0[day0["hadm_id"].isin(train_ids)]
    day0_test = day0[day0["hadm_id"].isin(test_ids)]
    print(f"Day-0 rows: {len(day0_train)} train / {len(day0_test)} test")

    lr = LinearRegression()
    lr.fit(day0_train[lr_feature_cols], day0_train[TARGET_LOG])
    pred = np.expm1(lr.predict(day0_test[lr_feature_cols]))
    results.append(report("Linear Regression (Day-0)", day0_test[TARGET], pred))
    joblib.dump({"model": lr, "features": lr_feature_cols}, os.path.join(MODEL_DIR, "baseline_lr.joblib"))

    # ═══════════════════════════════════════════════════════════════
    # 2) XGBoost point regression -- full day-wise table
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("2) XGBoost point regression -- full day-wise table")
    print("=" * 70)
    X_train, y_train = df.loc[train_mask, xgb_feature_cols], df.loc[train_mask, TARGET_LOG]
    X_val, y_val = df.loc[val_mask, xgb_feature_cols], df.loc[val_mask, TARGET_LOG]
    X_test, y_test = df.loc[test_mask, xgb_feature_cols], df.loc[test_mask, TARGET_LOG]

    xgb_point = XGBRegressor(
        objective="reg:squarederror",
        eval_metric="mae",
        early_stopping_rounds=EARLY_STOPPING_ROUNDS,
        **XGB_PARAMS,
    )
    # Early stopping watches the VALIDATION set, never the test set -- using
    # test here would let model-selection (best_iteration) see the test data,
    # biasing the metrics reported below (Ashmit's catch).
    xgb_point.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    print(f"Best iteration: {xgb_point.best_iteration} / {XGB_PARAMS['n_estimators']} (early stopping)")
    pred = np.expm1(xgb_point.predict(X_test))
    results.append(report("XGBoost point (all days)", df.loc[test_mask, TARGET], pred))
    joblib.dump({"model": xgb_point, "features": xgb_feature_cols}, os.path.join(MODEL_DIR, "xgb_point.joblib"))

    # ═══════════════════════════════════════════════════════════════
    # 3) XGBoost quantile regression -- P10 / P50 / P90
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("3) XGBoost quantile regression -- P10 / P50 / P90")
    print("=" * 70)
    xgb_quantile = XGBRegressor(
        objective="reg:quantileerror",
        quantile_alpha=[0.1, 0.5, 0.9],
        early_stopping_rounds=EARLY_STOPPING_ROUNDS,
        **XGB_PARAMS,
    )
    xgb_quantile.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    print(f"Best iteration: {xgb_quantile.best_iteration} / {XGB_PARAMS['n_estimators']} (early stopping)")
    pred_q_log = xgb_quantile.predict(X_test)  # shape (n, 3): [P10, P50, P90]
    pred_q = np.expm1(pred_q_log)
    results.append(report("XGBoost quantile (P50, median)", df.loc[test_mask, TARGET], pred_q[:, 1]))

    y_true = df.loc[test_mask, TARGET].values
    inside = ((y_true >= pred_q[:, 0]) & (y_true <= pred_q[:, 2])).mean()
    print(f"Quick calibration check: {inside*100:.1f}% of true bills fall inside [P10, P90] (target: ~80%)")
    joblib.dump({"model": xgb_quantile, "features": xgb_feature_cols}, os.path.join(MODEL_DIR, "xgb_quantile.joblib"))

    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    summary = pd.DataFrame(results)
    print(summary.to_string(index=False))
    print(f"\nModels saved to {MODEL_DIR}")
    print("Full evaluation (per-day MAE, pinball loss, calibration, convergence chart) is Task 7.")


if __name__ == "__main__":
    main()
