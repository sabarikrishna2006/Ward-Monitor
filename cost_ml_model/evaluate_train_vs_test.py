"""
Task 1 (Phase 2) -- Run the same MAE/MAPE-by-day and calibration-by-day
evaluation on the TRAINING set, alongside the existing TEST set evaluation,
so the two can be compared side by side -- an overfitting check. If training
accuracy is dramatically better than test accuracy, that's a sign the model
memorized quirks of the training patients rather than generalizing.

Input:  cost_ml_model/data/dcm_model_ready_data.csv
        cost_ml_model/data/train_test_split_hadm_ids.csv
        cost_ml_model/models/{xgb_point,xgb_quantile}.joblib
Output: cost_ml_model/data/eval_mae_by_day_{train,test}.csv
        cost_ml_model/data/eval_calibration_by_day_{train,test}.csv
        cost_ml_model/eval_charts/train_vs_test_*.png
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

COLOR_TRAIN = "#27AE60"   # green -- new series for this comparison
COLOR_TEST = "#CA6F1E"    # orange -- matches existing MAPE chart color

DAY_BINS = [-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 40, 1000]
DAY_LABELS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11-20", "21-40", "41+"]


def compute_by_day(sub_df):
    """Same MAE/MAPE-by-day + calibration-by-day logic as evaluate_models.py,
    factored out so it can run identically on either split."""
    sub_df = sub_df.copy()
    y_true = sub_df[TARGET]
    sub_df["abs_err"] = (y_true - sub_df["pred_point"]).abs()
    sub_df["pct_err"] = (sub_df["abs_err"] / y_true.replace(0, np.nan)) * 100
    sub_df["day_bin"] = pd.cut(sub_df["hospital_day"], DAY_BINS, labels=DAY_LABELS)

    by_day = sub_df.groupby("day_bin", observed=True).agg(
        n=("abs_err", "size"),
        mae=("abs_err", "mean"),
        mape=("pct_err", "mean"),
        mean_true=(TARGET, "mean"),
    ).reset_index()

    cal_by_day = sub_df.groupby("day_bin", observed=True).apply(
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

    return by_day, cal_by_day


def overall_metrics(sub_df):
    y_true = sub_df[TARGET]
    mae = mean_absolute_error(y_true, sub_df["pred_point"])
    rmse = np.sqrt(mean_squared_error(y_true, sub_df["pred_point"]))
    r2 = r2_score(y_true, sub_df["pred_point"])
    mape = ((y_true - sub_df["pred_point"]).abs() / y_true.replace(0, np.nan) * 100).mean()
    return mae, rmse, r2, mape


def main():
    df = pd.read_csv(os.path.join(DATA_DIR, "dcm_model_ready_data.csv"))
    split = pd.read_csv(os.path.join(DATA_DIR, "train_test_split_hadm_ids.csv"))
    train_ids = set(split[split["split"] == "train"]["hadm_id"])
    test_ids = set(split[split["split"] == "test"]["hadm_id"])

    point_bundle = joblib.load(os.path.join(MODEL_DIR, "xgb_point.joblib"))
    quantile_bundle = joblib.load(os.path.join(MODEL_DIR, "xgb_quantile.joblib"))
    point_model, point_features = point_bundle["model"], point_bundle["features"]
    quantile_model, quantile_features = quantile_bundle["model"], quantile_bundle["features"]

    df["pred_point"] = np.expm1(point_model.predict(df[point_features]))
    pred_q = np.expm1(quantile_model.predict(df[quantile_features]))
    df["pred_p10"] = pred_q[:, 0]
    df["pred_p50"] = pred_q[:, 1]
    df["pred_p90"] = pred_q[:, 2]

    train_df = df.loc[df["hadm_id"].isin(train_ids)]
    test_df = df.loc[df["hadm_id"].isin(test_ids)]

    print("=" * 70)
    print("OVERALL: train vs. test")
    print("=" * 70)
    train_mae, train_rmse, train_r2, train_mape = overall_metrics(train_df)
    test_mae, test_rmse, test_r2, test_mape = overall_metrics(test_df)
    print(f"{'':10s} {'MAE':>14s} {'RMSE':>14s} {'R2':>8s} {'MAPE':>8s}")
    print(f"{'Train':10s} Rs {train_mae:>10,.0f} Rs {train_rmse:>10,.0f} {train_r2:>8.3f} {train_mape:>7.1f}%")
    print(f"{'Test':10s} Rs {test_mae:>10,.0f} Rs {test_rmse:>10,.0f} {test_r2:>8.3f} {test_mape:>7.1f}%")
    mae_gap_pct = (test_mae - train_mae) / train_mae * 100
    mape_gap_pts = test_mape - train_mape
    print(f"\nGap: test MAE is {mae_gap_pct:+.1f}% {'higher' if mae_gap_pct>0 else 'lower'} than train MAE")
    print(f"Gap: test MAPE is {mape_gap_pts:+.1f} percentage points {'higher' if mape_gap_pts>0 else 'lower'} than train MAPE")
    if mae_gap_pct > 25:
        print("-> Gap exceeds 25%: meaningful sign of overfitting, worth investigating (e.g. more regularization).")
    else:
        print("-> Gap is modest: no strong sign of overfitting.")

    by_day_train, cal_train = compute_by_day(train_df)
    by_day_test, cal_test = compute_by_day(test_df)

    by_day_train.to_csv(os.path.join(DATA_DIR, "eval_mae_by_day_train.csv"), index=False)
    by_day_test.to_csv(os.path.join(DATA_DIR, "eval_mae_by_day_test.csv"), index=False)
    cal_train.to_csv(os.path.join(DATA_DIR, "eval_calibration_by_day_train.csv"), index=False)
    cal_test.to_csv(os.path.join(DATA_DIR, "eval_calibration_by_day_test.csv"), index=False)

    print("\n" + "=" * 70)
    print("BY DAY: train vs. test MAPE")
    print("=" * 70)
    merged = by_day_train[["day_bin", "n", "mape"]].merge(
        by_day_test[["day_bin", "n", "mape"]], on="day_bin", suffixes=("_train", "_test"))
    print(merged.to_string(index=False, formatters={"mape_train": "{:.1f}%".format, "mape_test": "{:.1f}%".format}))

    _chart_train_vs_test_mape(by_day_train, by_day_test)
    _chart_train_vs_test_mae(by_day_train, by_day_test)
    print(f"\nSaved 2 comparison charts to {CHART_DIR}")


def _chart_train_vs_test_mape(by_day_train, by_day_test):
    fig, ax = plt.subplots(figsize=(9, 5))
    x = range(len(by_day_test))
    ax.plot(x, by_day_train["mape"], color=COLOR_TRAIN, linewidth=2, marker="o", markersize=5, label="Train")
    ax.plot(x, by_day_test["mape"], color=COLOR_TEST, linewidth=2, marker="o", markersize=5, label="Test")
    ax.set_xticks(list(x))
    ax.set_xticklabels(by_day_test["day_bin"])
    ax.set_xlabel("Hospital Day")
    ax.set_ylabel("MAPE (%)")
    ax.set_title("Train vs. Test: Relative Error by Hospital Day (Overfitting Check)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper right")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "train_vs_test_mape_by_day.png"), dpi=130)
    plt.close(fig)


def _chart_train_vs_test_mae(by_day_train, by_day_test):
    fig, ax = plt.subplots(figsize=(9, 5))
    x = range(len(by_day_test))
    ax.plot(x, by_day_train["mae"], color=COLOR_TRAIN, linewidth=2, marker="o", markersize=5, label="Train")
    ax.plot(x, by_day_test["mae"], color=COLOR_TEST, linewidth=2, marker="o", markersize=5, label="Test")
    ax.set_xticks(list(x))
    ax.set_xticklabels(by_day_test["day_bin"])
    ax.set_xlabel("Hospital Day")
    ax.set_ylabel("MAE (Rs)")
    ax.set_title("Train vs. Test: Absolute Error by Hospital Day (Overfitting Check)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper left")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "train_vs_test_mae_by_day.png"), dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    main()
