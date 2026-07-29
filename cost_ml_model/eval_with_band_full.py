"""
Full evaluation charts for the new production model (xgb_quantile_remaining_based
with diagnosis_cost_band): train-vs-test overfitting check, and quantile
calibration by day. Reuses the models + split already produced by
retrain_with_diagnosis_band.py -- just loads and re-evaluates, no retraining.

Output: eval_charts/with_band_train_vs_test_mape.png (overfitting check)
        eval_charts/with_band_calibration_by_day.png
        data/eval_with_band_calibration_by_day.csv
"""
import os
import numpy as np
import pandas as pd
import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
CHART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_charts")

TARGET = "total_bill_at_discharge"
DAY_BINS = [-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 40, 1000]
DAY_LABELS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11-20", "21-40", "41+"]


def predict_reconstructed(model, feature_cols, df):
    pred_log = model.predict(df[feature_cols])
    pred_remaining = np.clip(np.expm1(pred_log), 0, None)
    pred_sorted = np.sort(pred_remaining, axis=1)
    cumulative = df["cumulative_cost_so_far"].values.reshape(-1, 1)
    totals = cumulative + pred_sorted
    return totals[:, 0], totals[:, 1], totals[:, 2]


def main():
    df = pd.read_csv(os.path.join(DATA_DIR, "dcm_model_ready_data.csv"))
    split = pd.read_csv(os.path.join(DATA_DIR, "train_test_split_hadm_ids.csv"))
    train_ids = set(split[split["split"] == "train"]["hadm_id"])
    test_ids = set(split[split["split"] == "test"]["hadm_id"])

    bundle = joblib.load(os.path.join(MODEL_DIR, "xgb_quantile_remaining_based_with_band.joblib"))
    model, feature_cols = bundle["model"], bundle["features"]

    def eval_split(mask, name):
        sub = df.loc[mask].copy()
        p10, p50, p90 = predict_reconstructed(model, feature_cols, sub)
        sub["pred_p10"], sub["pred_p50"], sub["pred_p90"] = p10, p50, p90
        y_true = sub[TARGET]
        sub["abs_err"] = (y_true - sub["pred_p50"]).abs()
        sub["pct_err"] = (sub["abs_err"] / y_true.replace(0, np.nan)) * 100
        sub["day_bin"] = pd.cut(sub["hospital_day"], DAY_BINS, labels=DAY_LABELS)
        by_day = sub.groupby("day_bin", observed=True).apply(lambda g: pd.Series({
            "n": len(g), "mae": g["abs_err"].mean(), "mape": g["pct_err"].mean(),
            "coverage_80": ((g[TARGET] >= g["pred_p10"]) & (g[TARGET] <= g["pred_p90"])).mean(),
            "interval_width": (g["pred_p90"] - g["pred_p10"]).mean(),
            "mean_true": g[TARGET].mean(),
        }), include_groups=False).reset_index()
        by_day["split"] = name
        return by_day

    train_by_day = eval_split(df["hadm_id"].isin(train_ids), "train")
    test_by_day = eval_split(df["hadm_id"].isin(test_ids), "test")

    overall_train_mape = np.average(train_by_day["mape"], weights=train_by_day["n"])
    overall_test_mape = np.average(test_by_day["mape"], weights=test_by_day["n"])
    print(f"Train MAPE: {overall_train_mape:.1f}%   Test MAPE: {overall_test_mape:.1f}%   "
          f"Gap: {overall_test_mape - overall_train_mape:.1f} points "
          f"({'small, not overfitting badly' if overall_test_mape - overall_train_mape < 10 else 'notable gap, some overfitting'})")

    test_by_day.to_csv(os.path.join(DATA_DIR, "eval_with_band_calibration_by_day.csv"), index=False)

    # ── Chart 1: train vs test MAPE by day (overfitting check) ──
    fig, ax = plt.subplots(figsize=(9, 5))
    x = range(len(DAY_LABELS))
    tr = train_by_day.set_index("day_bin").reindex(DAY_LABELS)
    te = test_by_day.set_index("day_bin").reindex(DAY_LABELS)
    ax.plot(x, tr["mape"], color="#2ecc71", linewidth=2, marker="o", markersize=5, label="Train")
    ax.plot(x, te["mape"], color="#e74c3c", linewidth=2, marker="o", markersize=5, label="Test")
    ax.set_xticks(list(x)); ax.set_xticklabels(DAY_LABELS)
    ax.set_xlabel("Hospital Day"); ax.set_ylabel("MAPE (%)")
    ax.set_title(f"Train vs. Test MAPE by Day (with diagnosis_cost_band)\nOverall: train={overall_train_mape:.1f}%  test={overall_test_mape:.1f}%")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False); ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "with_band_train_vs_test_mape.png"), dpi=150)
    plt.close(fig)

    # ── Chart 2: calibration (coverage) by day, test set ──
    fig, ax = plt.subplots(figsize=(9, 5))
    colors = ["#4c8bf5" if 0.7 <= v <= 0.9 else "#C0392B" for v in te["coverage_80"]]
    ax.bar(x, te["coverage_80"] * 100, color=colors, width=0.6)
    ax.axhline(80, color="#1B2631", linewidth=1.5, linestyle="--", label="Target (80%)")
    ax.set_xticks(list(x)); ax.set_xticklabels(DAY_LABELS)
    ax.set_xlabel("Hospital Day"); ax.set_ylabel("[P10, P90] Coverage (%)")
    ax.set_title("Quantile Calibration by Hospital Day (with diagnosis_cost_band, test set)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="lower right"); ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "with_band_calibration_by_day.png"), dpi=150)
    plt.close(fig)

    print(f"Charts saved to {CHART_DIR}")


if __name__ == "__main__":
    main()
