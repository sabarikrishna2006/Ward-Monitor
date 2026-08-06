"""
Task 7 -- Evaluate the Task 6 models on the held-out test set:
  - Point model: MAE overall, per-admission-weighted, and by hospital_day
    (the actual evidence for "Day 1 affects Day 2" -- Gautam sir's convergence idea)
  - Quantile model: pinball loss per quantile, calibration check (does the
    [P10,P90] interval actually contain ~80% of true bills?), and how the
    interval narrows as hospital_day increases
  - Day-Wise Convergence Curve chart -- the headline chart for the next PPT

Input:  cost_ml_model/data/dcm_model_ready_data.csv
        cost_ml_model/data/train_test_split_hadm_ids.csv
        cost_ml_model/models/{xgb_point,xgb_quantile}.joblib
Output: cost_ml_model/eval_charts/*.png
"""
import os
import numpy as np
import pandas as pd
import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
CHART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_charts")
os.makedirs(CHART_DIR, exist_ok=True)

TARGET = "total_bill_at_discharge"

# Sequential single-hue ramp (light -> dark blue) for the ordered P10/P50/P90
# quantiles -- matches eda_and_preprocessing.py's existing blue ("#2E86C1").
COLOR_P10 = "#AED6F1"
COLOR_P50 = "#2E86C1"
COLOR_P90 = "#154360"
COLOR_MAE = "#2E86C1"
COLOR_MAPE = "#CA6F1E"

# Day bins: individual days 0-10 (where most admissions live), then wider
# buckets for the long tail (avoids a handful of very-long-stay rows creating
# a noisy, unreadable chart).
DAY_BINS = [-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 40, 1000]
DAY_LABELS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11-20", "21-40", "41+"]


def pinball_loss(y_true, y_pred, quantile):
    diff = y_true - y_pred
    return np.mean(np.maximum(quantile * diff, (quantile - 1) * diff))


def main():
    df = pd.read_csv(os.path.join(DATA_DIR, "dcm_model_ready_data.csv"))
    split = pd.read_csv(os.path.join(DATA_DIR, "train_test_split_hadm_ids.csv"))
    test_ids = set(split[split["split"] == "test"]["hadm_id"])
    test_mask = df["hadm_id"].isin(test_ids)
    test_df = df.loc[test_mask].copy()

    point_bundle = joblib.load(os.path.join(MODEL_DIR, "xgb_point.joblib"))
    quantile_bundle = joblib.load(os.path.join(MODEL_DIR, "xgb_quantile.joblib"))
    point_model, point_features = point_bundle["model"], point_bundle["features"]
    quantile_model, quantile_features = quantile_bundle["model"], quantile_bundle["features"]

    test_df["pred_point"] = np.expm1(point_model.predict(test_df[point_features]))
    pred_q = np.expm1(quantile_model.predict(test_df[quantile_features]))
    test_df["pred_p10"] = pred_q[:, 0]
    test_df["pred_p50"] = pred_q[:, 1]
    test_df["pred_p90"] = pred_q[:, 2]

    y_true = test_df[TARGET]

    # ═══════════════════════════════════════════════════════════════
    print("=" * 70)
    print("1) POINT MODEL -- overall")
    print("=" * 70)
    mae = mean_absolute_error(y_true, test_df["pred_point"])
    rmse = np.sqrt(mean_squared_error(y_true, test_df["pred_point"]))
    r2 = r2_score(y_true, test_df["pred_point"])
    print(f"Pooled (row-weighted)   MAE = Rs {mae:>12,.0f}   RMSE = Rs {rmse:>12,.0f}   R2 = {r2:.3f}")

    test_df["abs_err"] = (y_true - test_df["pred_point"]).abs()
    per_adm_mae = test_df.groupby("hadm_id")["abs_err"].mean().mean()
    print(f"Per-admission-weighted  MAE = Rs {per_adm_mae:>12,.0f}  "
          f"(every admission counted once, not once per day -- fairer summary)")

    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("2) POINT MODEL -- by hospital_day (the convergence evidence)")
    print("=" * 70)
    test_df["day_bin"] = pd.cut(test_df["hospital_day"], DAY_BINS, labels=DAY_LABELS)
    test_df["pct_err"] = (test_df["abs_err"] / y_true.replace(0, np.nan)) * 100

    by_day = test_df.groupby("day_bin", observed=True).agg(
        n=("abs_err", "size"),
        mae=("abs_err", "mean"),
        mape=("pct_err", "mean"),
        mean_true=(TARGET, "mean"),
    ).reset_index()
    print(by_day.to_string(index=False,
          formatters={"mae": "Rs {:,.0f}".format, "mape": "{:.1f}%".format,
                      "mean_true": "Rs {:,.0f}".format}))
    by_day.to_csv(os.path.join(DATA_DIR, "eval_mae_by_day.csv"), index=False)

    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("3) QUANTILE MODEL -- pinball loss per quantile")
    print("=" * 70)
    for label, col, alpha in [("P10", "pred_p10", 0.1), ("P50", "pred_p50", 0.5), ("P90", "pred_p90", 0.9)]:
        loss = pinball_loss(y_true.values, test_df[col].values, alpha)
        print(f"{label}: pinball loss = Rs {loss:,.0f}")

    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("4) QUANTILE MODEL -- calibration check")
    print("=" * 70)
    coverage_80 = ((y_true >= test_df["pred_p10"]) & (y_true <= test_df["pred_p90"])).mean()
    below_p10 = (y_true <= test_df["pred_p10"]).mean()
    below_p50 = (y_true <= test_df["pred_p50"]).mean()
    below_p90 = (y_true <= test_df["pred_p90"]).mean()
    print(f"[P10, P90] interval coverage: {coverage_80*100:.1f}%  (target: ~80%)")
    print(f"Fraction of true bills <= predicted P10: {below_p10*100:.1f}%  (target: ~10%)")
    print(f"Fraction of true bills <= predicted P50: {below_p50*100:.1f}%  (target: ~50%)")
    print(f"Fraction of true bills <= predicted P90: {below_p90*100:.1f}%  (target: ~90%)")
    if below_p10 < 0.10 and below_p90 < 0.90:
        print("-> Both P10 and P90 are running LOW (under-covering the true value from above):")
        print("   the model is systematically UNDER-predicting late/expensive admissions,")
        print("   not just noisy -- a directional bias, not pure variance.")

    print("\nCalibration by hospital_day bucket:")
    cal_by_day = test_df.groupby("day_bin", observed=True).apply(
        lambda g: pd.Series({
            "n": len(g),
            "mean_true": g[TARGET].mean(),
            "mean_p10": g["pred_p10"].mean(),
            "mean_p50": g["pred_p50"].mean(),
            "mean_p90": g["pred_p90"].mean(),
            "coverage_80": ((g[TARGET] >= g["pred_p10"]) & (g[TARGET] <= g["pred_p90"])).mean(),
            "interval_width": (g["pred_p90"] - g["pred_p10"]).mean(),
        }), include_groups=False
    ).reset_index()
    cal_by_day["relative_width_pct"] = (cal_by_day["interval_width"] / cal_by_day["mean_true"] * 100).round(0)
    cal_by_day["ceiling_floor_ratio"] = (cal_by_day["mean_p90"] / cal_by_day["mean_p10"]).round(2)
    print(cal_by_day.to_string(index=False,
          formatters={"coverage_80": "{:.1%}".format, "interval_width": "Rs {:,.0f}".format,
                      "mean_true": "Rs {:,.0f}".format, "mean_p10": "Rs {:,.0f}".format,
                      "mean_p50": "Rs {:,.0f}".format, "mean_p90": "Rs {:,.0f}".format}))
    cal_by_day.to_csv(os.path.join(DATA_DIR, "eval_calibration_by_day.csv"), index=False)

    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("5) Charts")
    print("=" * 70)
    _chart_convergence_mae(by_day)
    _chart_convergence_mape(by_day)
    _chart_quantile_fan(cal_by_day, by_day)
    _chart_calibration_coverage(cal_by_day)
    print(f"Saved 4 charts to {CHART_DIR}")


def _chart_convergence_mae(by_day):
    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = range(len(by_day))
    ax.plot(x, by_day["mae"], color=COLOR_MAE, linewidth=2, marker="o", markersize=5)
    ax.set_xticks(list(x))
    ax.set_xticklabels(by_day["day_bin"])
    ax.set_xlabel("Hospital Day")
    ax.set_ylabel("MAE (Rs)")
    ax.set_title("Day-Wise Convergence Curve -- Prediction Error by Hospital Day")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "convergence_mae_by_day.png"), dpi=130)
    plt.close(fig)


def _chart_convergence_mape(by_day):
    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = range(len(by_day))
    ax.plot(x, by_day["mape"], color=COLOR_MAPE, linewidth=2, marker="o", markersize=5)
    ax.set_xticks(list(x))
    ax.set_xticklabels(by_day["day_bin"])
    ax.set_xlabel("Hospital Day")
    ax.set_ylabel("MAPE (%)")
    ax.set_title("Relative Error by Hospital Day (% of true bill)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "convergence_mape_by_day.png"), dpi=130)
    plt.close(fig)


def _chart_quantile_fan(cal_by_day, by_day):
    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = range(len(by_day))
    ax.plot(x, by_day["mean_true"], color="#1B2631", linewidth=2, marker="o",
            markersize=5, label="Mean actual final bill", zorder=3)
    ax.fill_between(x, by_day["mean_true"] - cal_by_day["interval_width"] / 2,
                     by_day["mean_true"] + cal_by_day["interval_width"] / 2,
                     color=COLOR_P50, alpha=0.2, label="Mean [P10, P90] width", zorder=1)
    ax.set_xticks(list(x))
    ax.set_xticklabels(by_day["day_bin"])
    ax.set_xlabel("Hospital Day")
    ax.set_ylabel("Rs")
    ax.set_title("Prediction Interval Width by Hospital Day")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper left")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "quantile_interval_by_day.png"), dpi=130)
    plt.close(fig)


def _chart_calibration_coverage(cal_by_day):
    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = range(len(cal_by_day))
    colors = [COLOR_P50 if 0.7 <= v <= 0.9 else "#C0392B" for v in cal_by_day["coverage_80"]]
    ax.bar(x, cal_by_day["coverage_80"] * 100, color=colors, width=0.6)
    ax.axhline(80, color="#1B2631", linewidth=1.5, linestyle="--", label="Target (80%)")
    ax.set_xticks(list(x))
    ax.set_xticklabels(cal_by_day["day_bin"])
    ax.set_xlabel("Hospital Day")
    ax.set_ylabel("[P10, P90] Coverage (%)")
    ax.set_title("Quantile Calibration by Hospital Day")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="lower right")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "calibration_by_day.png"), dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    main()
