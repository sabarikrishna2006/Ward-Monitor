"""
Task 4 — Assemble the final one-row-per-patient-per-day training table.

Joins static admission data (Task 1) onto every day-row (Task 3), then computes
the running/target columns:
  cumulative_cost_so_far   = running sum of day_total_cost, Day 0..t
  total_bill_at_discharge  = final cumulative value, broadcast to every row
                             (== the TRAINING TARGET for Task 6 — Ashmit's call:
                             predict the final cost directly, not remaining_cost)
  remaining_cost           = total_bill_at_discharge - cumulative_cost_so_far
                             (derived/reporting only, never a training label)

Output: cost_ml_model/data/dcm_day_wise_training_data.csv
"""
import os
import pandas as pd

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def main():
    static = pd.read_csv(os.path.join(OUT_DIR, "dcm_admissions_static.csv"))
    day_costs = pd.read_csv(os.path.join(OUT_DIR, "dcm_day_costs.csv"))

    static_cols = ["hadm_id", "gender", "admission_type", "insurance", "age_at_admission",
                   "primary_diagnosis", "treating_specialty", "icu_flag",
                   "los_days_total"]
    df = day_costs.merge(static[static_cols], on="hadm_id", how="left")

    assert len(df) == len(day_costs), \
        f"Row count changed after static join: {len(day_costs)} -> {len(df)} (should be identical, left-join on hadm_id)"
    assert df["gender"].isnull().sum() == 0, "Some hadm_ids in day_costs have no matching static row!"

    df = df.sort_values(["hadm_id", "hospital_day"])
    df["cumulative_cost_so_far"] = df.groupby("hadm_id")["day_total_cost"].cumsum()

    final_cost = df.groupby("hadm_id")["cumulative_cost_so_far"].transform("last")
    df["total_bill_at_discharge"] = final_cost
    df["remaining_cost"] = df["total_bill_at_discharge"] - df["cumulative_cost_so_far"]

    out_path = os.path.join(OUT_DIR, "dcm_day_wise_training_data.csv")
    df.to_csv(out_path, index=False)

    # --- Sanity checks (per the plan's Verification section) ---
    print(f"Saved {len(df)} rows -> {out_path}")
    print("\n--- Sanity check ---")
    print("Total rows:", len(df))
    print("Distinct admissions:", df["hadm_id"].nunique())

    expected_rows = (static["los_days_total"] + 1).sum()
    print(f"Expected rows (sum of los_days_total+1): {expected_rows} | Actual: {len(df)}")
    assert len(df) == expected_rows, "Row count doesn't match sum(los_days_total + 1) — a day is missing or duplicated somewhere."

    last_rows = df.groupby("hadm_id").tail(1)
    non_zero_remaining = (last_rows["remaining_cost"].round(2) != 0).sum()
    print(f"Admissions whose LAST day has remaining_cost != 0: {non_zero_remaining} (should be 0)")
    assert non_zero_remaining == 0, "Some admissions end with nonzero remaining_cost — cumulative sum logic is broken."

    print("\nTarget variable (total_bill_at_discharge) stats:")
    print(static.merge(df.groupby("hadm_id")["total_bill_at_discharge"].first(), on="hadm_id")
          ["total_bill_at_discharge"].describe().round(0))
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
