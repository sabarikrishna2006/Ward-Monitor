"""
Retrains the production quantile model (remaining-cost target, see
backend/app/cost_predictor.py's _MODEL_PATH comment for why remaining-cost
instead of total-bill) TWICE on the identical train/val/test split:

  - "baseline"   -- exact current production feature set (no diagnosis band)
  - "with_band"  -- same features + primary_diagnosis_cost_band_* (4 cols)

Only difference between the two runs is that one feature group, so any
accuracy delta is attributable to it. Evaluates both with the same day-wise
MAE/MAPE methodology (train AND test, so overfitting is visible too), and
only overwrites the live production model if with_band is actually better.

Input:  data/dcm_model_ready_data.csv (now includes diagnosis band cols)
        data/train_test_split_hadm_ids.csv (existing split, reused for a fair comparison)
Output: models/xgb_quantile_remaining_based_baseline.joblib
        models/xgb_quantile_remaining_based_with_band.joblib
        models/xgb_quantile_remaining_based.joblib  (overwritten with the winner)
        data/eval_diagnosis_band_comparison_by_day.csv
        eval_charts/diagnosis_band_before_after_mape.png
        eval_charts/diagnosis_band_feature_importance.png
"""
import os
import numpy as np
import pandas as pd
import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.metrics import mean_absolute_error
from xgboost import XGBRegressor

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
CHART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_charts")
os.makedirs(CHART_DIR, exist_ok=True)

TARGET = "total_bill_at_discharge"
KEY_COLS = ["hadm_id", TARGET, f"{TARGET}_log", "subject_id",
            "remaining_cost", "remaining_cost_log"]
BAND_PREFIX = "primary_diagnosis_cost_band_"

XGB_PARAMS = dict(
    n_estimators=300, max_depth=6, learning_rate=0.05,
    subsample=0.8, colsample_bytree=0.8, random_state=42, n_jobs=-1,
)
EARLY_STOPPING_ROUNDS = 20

DAY_BINS = [-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 40, 1000]
DAY_LABELS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11-20", "21-40", "41+"]


def train_one(df, feature_cols, train_ids, val_ids, name):
    train_mask = df["hadm_id"].isin(train_ids)
    val_mask = df["hadm_id"].isin(val_ids)
    X_train, y_train = df.loc[train_mask, feature_cols], df.loc[train_mask, "remaining_cost_log"]
    X_val, y_val = df.loc[val_mask, feature_cols], df.loc[val_mask, "remaining_cost_log"]

    model = XGBRegressor(
        objective="reg:quantileerror", quantile_alpha=[0.1, 0.5, 0.9],
        early_stopping_rounds=EARLY_STOPPING_ROUNDS, **XGB_PARAMS,
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    print(f"[{name}] {len(feature_cols)} features, best_iteration={model.best_iteration}")
    joblib.dump({"model": model, "features": feature_cols},
                os.path.join(MODEL_DIR, f"xgb_quantile_remaining_based_{name}.joblib"))
    return model


def predict_reconstructed(model, feature_cols, df):
    X = df[feature_cols]
    pred_log = model.predict(X)
    pred_remaining = np.clip(np.expm1(pred_log), 0, None)
    pred_remaining_sorted = np.sort(pred_remaining, axis=1)  # guard quantile crossing
    cumulative = df["cumulative_cost_so_far"].values.reshape(-1, 1)
    totals = cumulative + pred_remaining_sorted
    return totals[:, 0], totals[:, 1], totals[:, 2]  # p10, p50, p90


def eval_by_day(df, mask, model, feature_cols, split_name, run_name):
    sub = df.loc[mask].copy()
    p10, p50, p90 = predict_reconstructed(model, feature_cols, sub)
    sub["pred_p50"] = p50
    y_true = sub[TARGET]
    sub["abs_err"] = (y_true - sub["pred_p50"]).abs()
    sub["pct_err"] = (sub["abs_err"] / y_true.replace(0, np.nan)) * 100
    sub["day_bin"] = pd.cut(sub["hospital_day"], DAY_BINS, labels=DAY_LABELS)

    by_day = sub.groupby("day_bin", observed=True).agg(
        n=("abs_err", "size"), mae=("abs_err", "mean"), mape=("pct_err", "mean"),
    ).reset_index()
    by_day["split"] = split_name
    by_day["run"] = run_name

    overall_mae = mean_absolute_error(y_true, sub["pred_p50"])
    overall_mape = sub["pct_err"].mean()
    coverage = ((y_true >= p10) & (y_true <= p90)).mean()
    below_p10 = (y_true.values < p10 - 0.01).sum()  # expected ~10% of rows by design, not a structural violation
    print(f"  [{run_name}/{split_name}] overall MAE=Rs {overall_mae:,.0f}  MAPE={overall_mape:.1f}%  "
          f"[P10,P90] coverage={coverage*100:.1f}%  true_below_p10={below_p10} ({below_p10/len(sub)*100:.1f}%, target ~10%)")
    return by_day


def main():
    df = pd.read_csv(os.path.join(DATA_DIR, "dcm_model_ready_data.csv"))
    split = pd.read_csv(os.path.join(DATA_DIR, "train_test_split_hadm_ids.csv"))
    train_ids = set(split[split["split"] == "train"]["hadm_id"])
    val_ids = set(split[split["split"] == "val"]["hadm_id"])
    test_ids = set(split[split["split"] == "test"]["hadm_id"])
    print(f"Reusing existing split: {len(train_ids)} train / {len(val_ids)} val / {len(test_ids)} test admissions")

    # ── Build the remaining-cost target (same definition as the live production model) ──
    df["remaining_cost"] = (df[TARGET] - df["cumulative_cost_so_far"]).clip(lower=0)
    df["remaining_cost_log"] = np.log1p(df["remaining_cost"])

    band_cols = [c for c in df.columns if c.startswith(BAND_PREFIX)]
    assert len(band_cols) == 4, f"expected 4 diagnosis band columns, found {band_cols}"

    all_feature_cols = [c for c in df.columns if c not in KEY_COLS and not c.endswith("_scaled")]
    baseline_features = [c for c in all_feature_cols if c not in band_cols]
    with_band_features = all_feature_cols

    print(f"\nBaseline features: {len(baseline_features)}  |  With-band features: {len(with_band_features)}")

    print("\n" + "=" * 70)
    print("TRAINING")
    print("=" * 70)
    model_baseline = train_one(df, baseline_features, train_ids, val_ids, "baseline")
    model_with_band = train_one(df, with_band_features, train_ids, val_ids, "with_band")

    print("\n" + "=" * 70)
    print("EVALUATION -- train and test, both models")
    print("=" * 70)
    train_mask = df["hadm_id"].isin(train_ids)
    test_mask = df["hadm_id"].isin(test_ids)

    results = []
    results.append(eval_by_day(df, train_mask, model_baseline, baseline_features, "train", "baseline"))
    results.append(eval_by_day(df, test_mask, model_baseline, baseline_features, "test", "baseline"))
    results.append(eval_by_day(df, train_mask, model_with_band, with_band_features, "train", "with_band"))
    results.append(eval_by_day(df, test_mask, model_with_band, with_band_features, "test", "with_band"))
    all_results = pd.concat(results, ignore_index=True)
    all_results.to_csv(os.path.join(DATA_DIR, "eval_diagnosis_band_comparison_by_day.csv"), index=False)

    # ── Headline: Day-0 test MAPE, baseline vs with_band ──
    day0_base = all_results[(all_results.split == "test") & (all_results.run == "baseline") & (all_results.day_bin == "0")]
    day0_band = all_results[(all_results.split == "test") & (all_results.run == "with_band") & (all_results.day_bin == "0")]
    base_mape, band_mape = day0_base["mape"].iloc[0], day0_band["mape"].iloc[0]
    print("\n" + "=" * 70)
    print("HEADLINE: Day-0 test MAPE")
    print("=" * 70)
    print(f"  baseline (no diagnosis band):  {base_mape:.1f}%")
    print(f"  with_band (diagnosis band):    {band_mape:.1f}%")
    delta = base_mape - band_mape
    print(f"  {'IMPROVEMENT' if delta > 0 else 'REGRESSION'}: {abs(delta):.1f} percentage points")

    # ── Overall (all days) test MAPE, for the "did it hurt elsewhere" check ──
    overall_base = all_results[(all_results.split == "test") & (all_results.run == "baseline")]
    overall_band = all_results[(all_results.split == "test") & (all_results.run == "with_band")]
    w_base = np.average(overall_base["mape"], weights=overall_base["n"])
    w_band = np.average(overall_band["mape"], weights=overall_band["n"])
    print(f"\n  Overall test MAPE (all days, n-weighted): baseline={w_base:.1f}%  with_band={w_band:.1f}%")

    # ── Decide whether to promote with_band to production ──
    promote = band_mape <= base_mape and w_band <= w_base + 0.5  # allow tiny noise elsewhere, Day-0 must not regress
    if promote:
        joblib.dump({"model": model_with_band, "features": with_band_features},
                    os.path.join(MODEL_DIR, "xgb_quantile_remaining_based.joblib"))
        print("\n>>> with_band model PROMOTED to production (xgb_quantile_remaining_based.joblib)")
    else:
        joblib.dump({"model": model_baseline, "features": baseline_features},
                    os.path.join(MODEL_DIR, "xgb_quantile_remaining_based.joblib"))
        print("\n>>> baseline model KEPT in production -- with_band did not clearly improve Day-0 without hurting elsewhere")

    _chart_before_after(all_results)
    _chart_feature_importance(model_with_band, with_band_features)
    print(f"\nCharts saved to {CHART_DIR}")
    return promote, base_mape, band_mape, w_base, w_band


def _chart_before_after(all_results):
    test = all_results[all_results.split == "test"]
    base = test[test.run == "baseline"].set_index("day_bin").reindex(DAY_LABELS)
    band = test[test.run == "with_band"].set_index("day_bin").reindex(DAY_LABELS)

    fig, ax = plt.subplots(figsize=(9, 5))
    x = range(len(DAY_LABELS))
    ax.plot(x, base["mape"], color="#e07b54", linewidth=2, marker="o", markersize=5, label="Baseline (no diagnosis band)")
    ax.plot(x, band["mape"], color="#4c8bf5", linewidth=2, marker="o", markersize=5, label="With diagnosis_cost_band")
    ax.set_xticks(list(x)); ax.set_xticklabels(DAY_LABELS)
    ax.set_xlabel("Hospital Day"); ax.set_ylabel("MAPE (%)")
    ax.set_title("Test-Set MAPE by Hospital Day -- Before vs. After Diagnosis Cost-Band Feature")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "diagnosis_band_before_after_mape.png"), dpi=150)
    plt.close(fig)


def _chart_feature_importance(model, feature_cols):
    importances = pd.Series(model.feature_importances_, index=feature_cols).sort_values(ascending=False).head(20)
    colors = ["#4c8bf5" if c.startswith(BAND_PREFIX) else "#8899aa" for c in importances.index]
    fig, ax = plt.subplots(figsize=(8, 7))
    ax.barh(importances.index[::-1], importances.values[::-1], color=colors[::-1])
    ax.set_xlabel("Feature Importance (gain)")
    ax.set_title("Top 20 Features -- With Diagnosis Cost Band\n(blue = new diagnosis_cost_band features)")
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "diagnosis_band_feature_importance.png"), dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
