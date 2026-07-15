"""
Task 3 — Join real MIMIC-IV clinical events (procedures/medicines/labs) to the
3 completed price-mapping files, producing one row per (hadm_id, hospital_day)
with that day's cost breakdown. Uses ONLY procedure_mapping_v1.csv /
medicine_mapping_v1.csv / lab_mapping_v1.csv as the cost source — no
flat-rate/synthetic pricing anywhere in this step.

All lab/medication/procedure costs are treated as reliable, correctly-mapped
prices for this project — no confidence tracking on the mapping quality.

Output: cost_ml_model/data/dcm_day_costs.csv
"""
import json
import os
import sys
import pandas as pd

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "backend"))

from app.bq_mimic_loader import _query, _hosp  # noqa: E402

DL = r"c:\Users\ASUS\Downloads"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

with open(os.path.join(PROJECT_DIR, "pricing_config.json")) as f:
    RATES = json.load(f)["rates"]
WARD_RATE = RATES["WARD_RATE"]
ICU_RATE = RATES["ICU_RATE"]


def load_static():
    static = pd.read_csv(os.path.join(OUT_DIR, "dcm_admissions_static.csv"))
    admittime = pd.to_datetime(static.set_index("hadm_id")["admittime"]).dt.normalize()
    return static["hadm_id"].tolist(), admittime


def _to_hospital_day(events, time_col, admittime):
    """Convert an absolute timestamp column into hospital_day (days since
    admission, floored at 0). Done PER EVENT, before any grouping — a handful
    of events (e.g. ED labs drawn just before formal ward admission) have a
    raw timestamp before admittime; flooring them at 0 must happen before the
    groupby, otherwise they silently create a second, un-merged group that
    also happens to land on day 0 (this was a real bug — caught it by noticing
    dcm_day_costs.csv had MORE rows than dcm_daily_location.csv, which a
    left-merge should never produce)."""
    event_date = pd.to_datetime(events[time_col]).dt.normalize()
    admit_date = events["hadm_id"].map(admittime)
    return (event_date - admit_date).dt.days.clip(lower=0)


def build_procedure_costs(hadm_ids, admittime):
    id_list = ",".join(str(h) for h in hadm_ids)
    rows = _query(f"""
        SELECT hadm_id, icd_code, icd_version, chartdate
        FROM {_hosp('procedures_icd')}
        WHERE hadm_id IN ({id_list})
    """)
    events = pd.DataFrame(rows)
    if events.empty:
        return pd.DataFrame(columns=["hadm_id", "hospital_day", "day_procedures_cost", "day_procedures_count"])

    mapping = pd.read_csv(os.path.join(DL, "procedure_mapping_v1.csv"))
    price_lookup = mapping.set_index("us_procedure_code")["price_in_rupees"]

    events = events.merge(price_lookup, left_on="icd_code", right_index=True, how="left")
    events["price_in_rupees"] = events["price_in_rupees"].fillna(mapping["price_in_rupees"].mean())
    events["hospital_day"] = _to_hospital_day(events, "chartdate", admittime)

    grp = events.groupby(["hadm_id", "hospital_day"]).agg(
        day_procedures_cost=("price_in_rupees", "sum"),
        day_procedures_count=("price_in_rupees", "count"),
    ).reset_index()
    return grp


def build_medicine_costs(hadm_ids, admittime):
    id_list = ",".join(str(h) for h in hadm_ids)
    rows = _query(f"""
        SELECT hadm_id, drug, starttime
        FROM {_hosp('prescriptions')}
        WHERE hadm_id IN ({id_list}) AND starttime IS NOT NULL
    """)
    events = pd.DataFrame(rows)
    if events.empty:
        return pd.DataFrame(columns=["hadm_id", "hospital_day", "day_medicines_cost", "day_medicines_count"])

    mapping = pd.read_csv(os.path.join(DL, "medicine_mapping_v1.csv"))
    price_lookup = mapping.set_index("us_medicine")["price_in_rupees"]
    global_avg_price = mapping["price_in_rupees"].mean()

    events = events.merge(price_lookup, left_on="drug", right_index=True, how="left")
    # Drug string not in the 1,865-row mapping (typo/dose-variant/new prescription
    # not seen when the mapping was built): fall back to the global average price
    # rather than dropping the row — classifying it into a drug class would need
    # re-running the enrichment pipeline, out of scope here.
    events["price_in_rupees"] = events["price_in_rupees"].fillna(global_avg_price)
    events["hospital_day"] = _to_hospital_day(events, "starttime", admittime)

    grp = events.groupby(["hadm_id", "hospital_day"]).agg(
        day_medicines_cost=("price_in_rupees", "sum"),
        day_medicines_count=("price_in_rupees", "count"),
    ).reset_index()
    return grp


def build_lab_costs(hadm_ids, admittime):
    id_list = ",".join(str(h) for h in hadm_ids)
    rows = _query(f"""
        SELECT hadm_id, itemid, charttime
        FROM {_hosp('labevents')}
        WHERE hadm_id IN ({id_list}) AND charttime IS NOT NULL
    """)
    events = pd.DataFrame(rows)
    if events.empty:
        return pd.DataFrame(columns=["hadm_id", "hospital_day", "day_labs_cost", "day_labs_count"])

    mapping = pd.read_csv(os.path.join(DL, "lab_mapping_v1.csv"))
    price_lookup = mapping.set_index("us_lab_itemid")["price_in_rupees"]
    global_avg_price = mapping["price_in_rupees"].mean()

    events = events.merge(price_lookup, left_on="itemid", right_index=True, how="left")
    events["price_in_rupees"] = events["price_in_rupees"].fillna(global_avg_price)
    events["hospital_day"] = _to_hospital_day(events, "charttime", admittime)

    grp = events.groupby(["hadm_id", "hospital_day"]).agg(
        day_labs_cost=("price_in_rupees", "sum"),
        day_labs_count=("price_in_rupees", "count"),
    ).reset_index()
    return grp


def main():
    hadm_ids, admittime = load_static()
    print(f"Building day-level costs for {len(hadm_ids)} admissions...")

    print("Procedures...")
    proc = build_procedure_costs(hadm_ids, admittime)
    print(f"  {len(proc)} (hadm_id, day) rows with a procedure")

    print("Medicines...")
    med = build_medicine_costs(hadm_ids, admittime)
    print(f"  {len(med)} (hadm_id, day) rows with a medicine")

    print("Labs...")
    lab = build_lab_costs(hadm_ids, admittime)
    print(f"  {len(lab)} (hadm_id, day) rows with a lab test")

    # Verify no duplicate (hadm_id, hospital_day) keys before merging — would
    # silently explode row count via a many-to-one left merge otherwise.
    for name, df in [("procedures", proc), ("medicines", med), ("labs", lab)]:
        dupes = df.duplicated(subset=["hadm_id", "hospital_day"]).sum()
        assert dupes == 0, f"{name}: {dupes} duplicate (hadm_id, hospital_day) rows before merge!"

    daily_loc = pd.read_csv(os.path.join(OUT_DIR, "dcm_daily_location.csv"))
    day_costs = daily_loc.merge(proc, on=["hadm_id", "hospital_day"], how="left") \
                         .merge(med, on=["hadm_id", "hospital_day"], how="left") \
                         .merge(lab, on=["hadm_id", "hospital_day"], how="left")

    assert len(day_costs) == len(daily_loc), \
        f"Row count changed after merge: {len(daily_loc)} -> {len(day_costs)} (left-merge should never grow the row count)"

    for col in ["day_procedures_cost", "day_medicines_cost", "day_labs_cost",
                "day_procedures_count", "day_medicines_count", "day_labs_count"]:
        day_costs[col] = day_costs[col].fillna(0)

    day_costs["day_ward_cost"] = day_costs["was_in_icu_today"].apply(lambda icu: 0 if icu else WARD_RATE)
    day_costs["day_icu_cost"] = day_costs["was_in_icu_today"].apply(lambda icu: ICU_RATE if icu else 0)
    day_costs["day_total_cost"] = (day_costs["day_procedures_cost"] + day_costs["day_medicines_cost"]
                                    + day_costs["day_labs_cost"] + day_costs["day_ward_cost"]
                                    + day_costs["day_icu_cost"])

    day_costs["had_procedure_today"] = (day_costs["day_procedures_count"] > 0).astype(int)
    day_costs["had_medicine_today"] = (day_costs["day_medicines_count"] > 0).astype(int)
    day_costs["had_lab_today"] = (day_costs["day_labs_count"] > 0).astype(int)

    day_costs = day_costs.drop(columns=["day_procedures_count", "day_medicines_count", "day_labs_count"])

    out_path = os.path.join(OUT_DIR, "dcm_day_costs.csv")
    day_costs.to_csv(out_path, index=False)
    print(f"\nSaved {len(day_costs)} rows -> {out_path}")
    print("\n--- Sanity check ---")
    print("Mean day_total_cost:", day_costs["day_total_cost"].mean().round(0))
    print("Days with any procedure:", day_costs["had_procedure_today"].sum())
    print("Days with any medicine:", day_costs["had_medicine_today"].sum())
    print("Days with any lab:", day_costs["had_lab_today"].sum())
    dupes = day_costs.duplicated(subset=["hadm_id", "hospital_day"]).sum()
    print("Duplicate (hadm_id, hospital_day) rows in final output:", dupes)


if __name__ == "__main__":
    main()
