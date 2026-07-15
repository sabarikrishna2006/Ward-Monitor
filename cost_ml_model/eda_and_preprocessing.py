"""
EDA + Data Cleaning + Data Preprocessing + Feature Engineering + Feature
Selection for the day-wise cost prediction dataset, following the structure
in Machine Learning (2).pdf (EDA -> Data Cleaning -> Preprocessing -> Feature
Engineering -> Feature Selection).

Input:  cost_ml_model/data/dcm_day_wise_training_data.csv
Output: cost_ml_model/data/dcm_model_ready_data.csv (encoded/scaled, ready for Task 6)
        cost_ml_model/eda_charts/*.png
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats
from sklearn.preprocessing import StandardScaler

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CHART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eda_charts")
os.makedirs(CHART_DIR, exist_ok=True)

TARGET = "total_bill_at_discharge"
# NOTE: los_days_total is kept here for EDA/description only (e.g. to show WHY
# it's tempting and how strongly it correlates with the target) — it is
# deliberately EXCLUDED from MODEL_FEATURE_NUMERIC_COLS below and never enters
# model_ready, because it's only known at discharge (leakage). No
# elixhauser_score in this version — see pull_dcm_admissions.py for why.
NUMERIC_COLS = ["age_at_admission", "los_days_total", "hospital_day",
                 "day_procedures_cost", "day_medicines_cost", "day_labs_cost",
                 "day_ward_cost", "day_icu_cost", "day_total_cost",
                 "cumulative_cost_so_far", TARGET]
# The only numeric columns genuinely known at prediction time (day t) — these,
# and only these, become model input features.
MODEL_FEATURE_NUMERIC_COLS = ["age_at_admission", "hospital_day",
                               "cumulative_cost_so_far", "cost_per_day_so_far"]
CATEGORICAL_COLS = ["gender", "admission_type", "insurance", "primary_diagnosis", "treating_specialty"]
BINARY_COLS = ["was_in_icu_today", "had_procedure_today", "had_medicine_today", "had_lab_today",
               "icu_flag"]


def section(title):
    print(f"\n{'='*70}\n{title}\n{'='*70}")


# ═══════════════════════════════════════════════════════════════════════
# 1) EDA
# ═══════════════════════════════════════════════════════════════════════

def eda_view_data(df):
    section("1) EDA — Viewing the Data")
    print("Shape:", df.shape)
    print("\ndtypes:\n", df.dtypes)
    print("\nHead:\n", df.head(3).to_string())


def eda_summary_stats(df):
    section("2) EDA — Summary Statistics (numeric columns)")
    print(df[NUMERIC_COLS].describe().round(1).to_string())


def eda_value_counts(df):
    section("3) EDA — Value Counts (categorical columns)")
    for col in CATEGORICAL_COLS:
        print(f"\n--- {col} ({df[col].nunique()} unique) ---")
        print(df[col].value_counts().head(10))


def eda_missing_values(df):
    section("4) EDA — Missing Value Analysis")
    missing = df.isnull().sum()
    missing_pct = (missing / len(df) * 100).round(2)
    report = pd.DataFrame({"missing_count": missing, "missing_pct": missing_pct})
    report = report[report["missing_count"] > 0]
    if report.empty:
        print("No missing values in any column.")
    else:
        print(report.to_string())
    return report


def eda_visualizations(df):
    section("5) EDA — Visualizations")

    # Histogram of the target
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.hist(df[TARGET].clip(upper=df[TARGET].quantile(0.95)), bins=40, color="#2E86C1", edgecolor="white")
    ax.set_title("Distribution of total_bill_at_discharge (clipped at 95th pct)")
    ax.set_xlabel("Rs"); ax.set_ylabel("Count")
    fig.tight_layout(); fig.savefig(os.path.join(CHART_DIR, "target_histogram.png"), dpi=130); plt.close(fig)

    # Boxplot of target for outlier visibility
    fig, ax = plt.subplots(figsize=(7, 3))
    ax.boxplot(df[TARGET], vert=False, patch_artist=True, boxprops=dict(facecolor="#2E86C1", alpha=0.7))
    ax.set_xscale("log")
    ax.set_title("total_bill_at_discharge — Boxplot (log scale, shows outliers)")
    fig.tight_layout(); fig.savefig(os.path.join(CHART_DIR, "target_boxplot.png"), dpi=130); plt.close(fig)

    # Correlation heatmap of numeric features
    corr = df[NUMERIC_COLS].corr()
    fig, ax = plt.subplots(figsize=(9, 7))
    im = ax.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr.columns))); ax.set_xticklabels(corr.columns, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(corr.columns))); ax.set_yticklabels(corr.columns, fontsize=8)
    for i in range(len(corr)):
        for j in range(len(corr)):
            ax.text(j, i, f"{corr.iloc[i,j]:.2f}", ha="center", va="center", fontsize=6)
    fig.colorbar(im, ax=ax, shrink=0.8)
    ax.set_title("Correlation Heatmap (numeric features)")
    fig.tight_layout(); fig.savefig(os.path.join(CHART_DIR, "correlation_heatmap.png"), dpi=130); plt.close(fig)

    # Bar plot: mean target by treating_specialty (top 8)
    top_spec = df.groupby("treating_specialty")[TARGET].mean().sort_values(ascending=False).head(8)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.barh(top_spec.index[::-1], top_spec.values[::-1], color="#279E4E")
    ax.set_title("Mean Final Bill by Treating Specialty (top 8)")
    ax.set_xlabel("Rs")
    fig.tight_layout(); fig.savefig(os.path.join(CHART_DIR, "specialty_bar.png"), dpi=130); plt.close(fig)

    print(f"Saved 4 charts to {CHART_DIR}")


def eda_target_exploration(df):
    section("6) EDA — Target Variable Exploration")
    per_admission = df.groupby("hadm_id").first()
    print("Correlation of static/summary features with total_bill_at_discharge:")
    print(per_admission[["age_at_admission", "los_days_total",
                          "icu_flag", TARGET]].corr()[TARGET].sort_values(ascending=False))
    print("\nNOTE: los_days_total correlates very strongly with the target (as shown above) —")
    print("      that's exactly why it's excluded from the model. It's only known at")
    print("      discharge, so using it as a feature would be leakage, not a real predictor.")


# ═══════════════════════════════════════════════════════════════════════
# 2) DATA CLEANING
# ═══════════════════════════════════════════════════════════════════════

def clean_check_duplicates(df):
    section("Data Cleaning — 1) Duplicate rows")
    dupes = df.duplicated(subset=["hadm_id", "hospital_day"]).sum()
    print(f"Duplicate (hadm_id, hospital_day) rows: {dupes}")
    assert dupes == 0, "Found duplicates — should have been caught in Task 3/4."


def clean_fix_dtypes(df):
    section("Data Cleaning — 2) Fix Data Types")
    print("Before:\n", df[CATEGORICAL_COLS + ["gender"]].dtypes)
    for col in CATEGORICAL_COLS:
        df[col] = df[col].astype(str).str.strip()
    print("Confirmed all categorical columns are clean strings (stripped whitespace).")
    return df


def clean_inconsistent_categories(df):
    section("Data Cleaning — 3) Inconsistent Categories")
    for col in ["gender", "admission_type", "insurance"]:
        before = df[col].nunique()
        df[col] = df[col].str.upper().str.strip()
        after = df[col].nunique()
        print(f"{col}: {before} -> {after} unique values after case/whitespace normalization")
    return df


def clean_logic_errors(df):
    section("Data Cleaning — 4) Logic / Domain Errors")
    issues = {
        "negative age": (df["age_at_admission"] < 0).sum(),
        "age > 120": (df["age_at_admission"] > 120).sum(),
        "negative hospital_day": (df["hospital_day"] < 0).sum(),
        "negative day_total_cost": (df["day_total_cost"] < 0).sum(),
        "negative cumulative_cost": (df["cumulative_cost_so_far"] < 0).sum(),
        "negative remaining_cost (rounding)": (df["remaining_cost"].round(2) < -1).sum(),
    }
    for k, v in issues.items():
        print(f"  {k}: {v}")
    total_issues = sum(issues.values())
    assert total_issues == 0, f"Found {total_issues} logic errors — needs investigation before modeling."
    print("No logic/domain errors found.")


def clean_outliers(df):
    section("Data Cleaning — 5) Detect & Handle Outliers (IQR, capped not dropped)")
    # Hospital costs are naturally heavy-tailed (a few genuinely very sick/expensive
    # patients) — these are real, not data errors, so we CAP at a high percentile
    # rather than removing rows (removing would delete real, important cases).
    cap_cols = ["day_total_cost", "cumulative_cost_so_far", TARGET]
    for col in cap_cols:
        q1, q3 = df[col].quantile([0.25, 0.75])
        iqr = q3 - q1
        upper_fence = q3 + 3 * iqr  # 3x IQR (wide fence) since these are legitimate values, not errors
        n_outliers = (df[col] > upper_fence).sum()
        cap_value = df[col].quantile(0.995)  # cap at 99.5th percentile, not the fence itself
        df[f"{col}_capped"] = df[col].clip(upper=cap_value)
        print(f"  {col}: {n_outliers} rows beyond IQR fence (Rs {upper_fence:,.0f}); "
              f"capped column at 99.5th pct = Rs {cap_value:,.0f}")
    return df


# ═══════════════════════════════════════════════════════════════════════
# 3) DATA PREPROCESSING
# ═══════════════════════════════════════════════════════════════════════

def preprocess_encode_categoricals(df):
    section("Preprocessing — 1) Encoding Categorical Variables")
    # Binary (2-category) fields -> single 0/1 column, per sir's explicit instruction
    df["gender_is_male"] = (df["gender"] == "M").astype(int)
    print("gender -> gender_is_male (single binary column)")

    # 3+-category fields -> one-hot (each resulting column is itself 0/1)
    top_diag = df["primary_diagnosis"].value_counts().head(15).index
    df["primary_diagnosis_grouped"] = df["primary_diagnosis"].where(
        df["primary_diagnosis"].isin(top_diag), "Other")

    onehot_source_cols = ["admission_type", "insurance", "primary_diagnosis_grouped", "treating_specialty"]
    df_onehot = pd.get_dummies(df[onehot_source_cols], prefix=onehot_source_cols, dtype=int)
    print(f"One-hot encoded {onehot_source_cols} -> {df_onehot.shape[1]} binary columns "
          f"(primary_diagnosis grouped to top 15 + 'Other' to avoid an explosion of columns)")
    return df, df_onehot


def preprocess_feature_transformation(df):
    section("Preprocessing — 2) Feature Transformation (log for skewed cost columns)")
    skew_before = df[TARGET].skew()
    df[f"{TARGET}_log"] = np.log1p(df[TARGET])
    skew_after = df[f"{TARGET}_log"].skew()
    print(f"{TARGET} skew: {skew_before:.2f} -> log1p-transformed skew: {skew_after:.2f}")
    for col in ["day_total_cost", "cumulative_cost_so_far"]:
        df[f"{col}_log"] = np.log1p(df[col])
    return df


def preprocess_feature_scaling(df, numeric_cols_to_scale):
    section("Preprocessing — 3) Feature Scaling (Standardization)")
    scaler = StandardScaler()
    scaled = scaler.fit_transform(df[numeric_cols_to_scale])
    scaled_df = pd.DataFrame(scaled, columns=[f"{c}_scaled" for c in numeric_cols_to_scale], index=df.index)
    print(f"Standardized {len(numeric_cols_to_scale)} numeric columns (mean=0, std=1): {numeric_cols_to_scale}")
    return scaled_df


# ═══════════════════════════════════════════════════════════════════════
# 4) FEATURE ENGINEERING
# ═══════════════════════════════════════════════════════════════════════

def feature_engineering(df):
    section("Feature Engineering")
    df["cost_per_day_so_far"] = df["cumulative_cost_so_far"] / (df["hospital_day"] + 1)
    print("New feature: cost_per_day_so_far")
    print("(NOT adding pct_of_stay_elapsed or a los_bucket — both are derived from")
    print(" los_days_total, which is only known at discharge; same leakage problem,")
    print(" just hidden behind a transformation. Ashmit's correction applied here too.)")
    return df


# ═══════════════════════════════════════════════════════════════════════
# 5) FEATURE SELECTION
# ═══════════════════════════════════════════════════════════════════════

def feature_selection_correlation(df):
    section("Feature Selection — 1) Correlation Matrix (drop highly-correlated redundant features)")
    corr = df[NUMERIC_COLS].corr().abs()
    upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
    high_corr_pairs = [(col, row, upper.loc[row, col]) for col in upper.columns for row in upper.index
                        if pd.notna(upper.loc[row, col]) and upper.loc[row, col] > 0.9]
    if high_corr_pairs:
        print("Highly correlated pairs (>0.9) — candidates to drop one of each:")
        for a, b, v in high_corr_pairs:
            print(f"  {a} <-> {b}: {v:.2f}")
    else:
        print("No feature pairs above 0.9 correlation.")
    return high_corr_pairs


def feature_selection_anova(df):
    section("Feature Selection — 2) ANOVA F-test (categorical features vs. numeric target)")
    for col in CATEGORICAL_COLS:
        groups = [g[TARGET].values for _, g in df.groupby(col) if len(g) > 1]
        if len(groups) > 1:
            f_stat, p_val = stats.f_oneway(*groups)
            sig = "SIGNIFICANT" if p_val < 0.05 else "not significant"
            print(f"  {col}: F={f_stat:.2f}, p={p_val:.4g} -> {sig}")


def feature_selection_tree_importance(df, feature_cols):
    section("Feature Selection — 3) Tree-based Feature Importance (quick RandomForest probe)")
    from sklearn.ensemble import RandomForestRegressor
    X = df[feature_cols].fillna(0)
    y = df[TARGET]
    rf = RandomForestRegressor(n_estimators=100, max_depth=8, random_state=42, n_jobs=-1)
    rf.fit(X, y)
    importances = pd.Series(rf.feature_importances_, index=feature_cols).sort_values(ascending=False)
    print(importances.head(15).to_string())
    return importances


# ═══════════════════════════════════════════════════════════════════════
def main():
    df = pd.read_csv(os.path.join(DATA_DIR, "dcm_day_wise_training_data.csv"))

    # --- EDA ---
    eda_view_data(df)
    eda_summary_stats(df)
    eda_value_counts(df)
    eda_missing_values(df)
    eda_visualizations(df)
    eda_target_exploration(df)

    # --- Data Cleaning ---
    clean_check_duplicates(df)
    df = clean_fix_dtypes(df)
    df = clean_inconsistent_categories(df)
    clean_logic_errors(df)
    df = clean_outliers(df)

    # --- Preprocessing ---
    df, df_onehot = preprocess_encode_categoricals(df)
    df = preprocess_feature_transformation(df)

    # --- Feature Engineering ---
    df = feature_engineering(df)

    # --- Feature Selection ---
    high_corr = feature_selection_correlation(df)
    feature_selection_anova(df)

    scale_cols = MODEL_FEATURE_NUMERIC_COLS  # only features genuinely known at prediction time
    scaled_df = preprocess_feature_scaling(df, scale_cols)

    model_ready = pd.concat([
        df[["hadm_id", TARGET, f"{TARGET}_log"]],
        df[["gender_is_male", "icu_flag", "was_in_icu_today", "had_procedure_today",
            "had_medicine_today", "had_lab_today"]],
        df[scale_cols],  # keep raw (unscaled) too, for tree models that don't need scaling — includes hospital_day
        scaled_df,        # scaled versions, for the Linear Regression baseline
        df_onehot,
        df[["day_procedures_cost", "day_medicines_cost", "day_labs_cost",
            "day_ward_cost", "day_icu_cost", "day_total_cost"]],
    ], axis=1)
    dupe_cols = model_ready.columns[model_ready.columns.duplicated()].tolist()
    if dupe_cols:
        print(f"Dropping duplicate columns after concat: {dupe_cols}")
        model_ready = model_ready.loc[:, ~model_ready.columns.duplicated()]

    feature_cols = [c for c in model_ready.columns if c not in ("hadm_id", TARGET, f"{TARGET}_log")]
    feature_selection_tree_importance(model_ready, feature_cols)

    out_path = os.path.join(DATA_DIR, "dcm_model_ready_data.csv")
    model_ready.to_csv(out_path, index=False)
    section("DONE")
    print(f"Model-ready dataset: {model_ready.shape} -> {out_path}")


if __name__ == "__main__":
    main()
