"""
Chart: Top-10 feature importance, Gain vs SHAP side by side -- for the PPT.
Shows the divergence between the two measures directly (gain over-weights
sparse one-hot splits; SHAP is the more trustworthy ranking -- see the
gain vs SHAP discussion already had with Ashmit).

Input:  cost_ml_model/data/feature_importance_gain.csv
        cost_ml_model/data/feature_importance_shap.csv
Output: cost_ml_model/eval_charts/feature_importance_gain_vs_shap.png
"""
import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CHART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_charts")
os.makedirs(CHART_DIR, exist_ok=True)

COLOR_GAIN = "#2E86C1"   # blue -- matches existing chart style
COLOR_SHAP = "#CA6F1E"   # orange -- matches existing chart style

CLEAN_PREFIXES = {
    "primary_diagnosis_grouped_": "Diagnosis: ",
    "treating_specialty_": "Specialty: ",
    "admission_type_": "Admission: ",
    "insurance_": "Insurance: ",
}


def clean_name(name):
    for prefix, label in CLEAN_PREFIXES.items():
        if name.startswith(prefix):
            rest = name[len(prefix):]
            if len(rest) > 28:
                rest = rest[:25] + "..."
            return label + rest
    return {
        "cumulative_cost_so_far": "Money spent so far",
        "icu_flag": "Ever needed ICU",
        "hospital_day": "Day of stay (t)",
        "cost_per_day_so_far": "Avg. daily spend so far",
        "day_labs_cost": "Today's lab cost",
        "day_total_cost": "Today's total cost",
        "day_medicines_cost": "Today's medicine cost",
        "day_icu_cost": "Today's ICU cost",
        "day_ward_cost": "Today's ward cost",
        "day_procedures_cost": "Today's procedure cost",
        "was_in_icu_today": "In ICU today",
        "had_lab_today": "Had a lab today",
        "had_medicine_today": "Had medicine today",
        "had_procedure_today": "Had a procedure today",
        "age_at_admission": "Age",
        "gender_is_male": "Gender (male)",
    }.get(name, name)


def main():
    gain = pd.read_csv(os.path.join(DATA_DIR, "feature_importance_gain.csv"), index_col=0)
    shap = pd.read_csv(os.path.join(DATA_DIR, "feature_importance_shap.csv"), index_col=0)
    gain.columns = ["gain"]
    shap.columns = ["shap"]
    gain["gain_pct"] = gain["gain"] / gain["gain"].sum() * 100
    shap["shap_pct"] = shap["shap"] / shap["shap"].sum() * 100

    merged = gain[["gain_pct"]].join(shap[["shap_pct"]], how="outer").fillna(0)
    top10 = merged.sort_values("shap_pct", ascending=False).head(10)
    top10 = top10.iloc[::-1]  # reverse so #1 ends up at the top of the horizontal chart
    labels = list(top10.index)  # raw CSV column names, unmodified

    fig, ax = plt.subplots(figsize=(9, 6))
    y = range(len(top10))
    bar_h = 0.35
    ax.barh([i + bar_h / 2 for i in y], top10["gain_pct"], height=bar_h, color=COLOR_GAIN, label="Gain")
    ax.barh([i - bar_h / 2 for i in y], top10["shap_pct"], height=bar_h, color=COLOR_SHAP, label="SHAP")

    ax.set_yticks(list(y))
    ax.set_yticklabels(labels)
    ax.set_xlabel("Importance (%)")
    ax.set_title("Top 10 Features Driving the Cost Prediction (Gain vs. SHAP)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="lower right")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(CHART_DIR, "feature_importance_gain_vs_shap.png"), dpi=150)
    plt.close(fig)
    print(f"Saved chart -> {os.path.join(CHART_DIR, 'feature_importance_gain_vs_shap.png')}")
    print(top10[["gain_pct", "shap_pct"]].round(1).to_string())


if __name__ == "__main__":
    main()
