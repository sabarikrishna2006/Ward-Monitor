"""
live_feature_builder.py — build a model-ready feature row for a LIVE
admitted patient, straight from the real MIMIC-derived data the app already
fetched into active_patients / ap_* tables (see backend/cloud_sql_schema.sql).

This mirrors the offline pipeline (cost_ml_model/build_day_costs.py +
build_day_wise_dataset.py + eda_and_preprocessing.py's encoding), just
sourced from live Postgres queries instead of a precomputed CSV, so
predictions work for ANY admitted hadm_id, refreshed as real events post.

hospital_day semantics match the trained model's "end of day t" framing:
pass hospital_day explicitly, or omit it to use (today - admit_time).days,
i.e. "as of the most recently completed day."
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Optional

import pandas as pd
from sqlalchemy import text

PROJECT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
MAPPINGS_DIR = os.path.join(PROJECT_DIR, "cost_ml_model", "pricing_mappings")

with open(os.path.join(PROJECT_DIR, "pricing_config.json")) as f:
    _RATES = json.load(f)["rates"]
WARD_RATE = _RATES["WARD_RATE"]
ICU_RATE = _RATES["ICU_RATE"]

_PROC_MAP = None
_MED_MAP = None
_LAB_MAP = None
_DIAG_BAND_MAP = None

DIAG_BANDS_PATH = os.path.join(MAPPINGS_DIR, "diagnosis_cost_bands_shrunk.csv")


def _dedup_price_map(df: pd.DataFrame, key_col: str) -> pd.Series:
    """A duplicated key (e.g. the same medicine name mapped twice, which
    the medicine mapping file has 44 rows of) makes .set_index()[col].get(k)
    return a pandas Series instead of a scalar price -- silently breaking
    every downstream arithmetic op on it. Average duplicate rows down to
    one price per key so lookups are always scalars."""
    return df.groupby(key_col)["price_in_rupees"].mean()


def _load_mappings():
    global _PROC_MAP, _MED_MAP, _LAB_MAP, _DIAG_BAND_MAP
    if _PROC_MAP is None:
        _PROC_MAP = _dedup_price_map(pd.read_csv(os.path.join(MAPPINGS_DIR, "procedure_mapping_v1.csv")), "us_procedure_code")
        _MED_MAP = _dedup_price_map(pd.read_csv(os.path.join(MAPPINGS_DIR, "medicine_mapping_v1.csv")), "us_medicine")
        _LAB_MAP = _dedup_price_map(pd.read_csv(os.path.join(MAPPINGS_DIR, "lab_mapping_v1.csv")), "us_lab_itemid")
    if _DIAG_BAND_MAP is None:
        _DIAG_BAND_MAP = pd.read_csv(DIAG_BANDS_PATH).set_index("primary_diagnosis")["band"]


def _to_hospital_day(event_dates, admit_date):
    """Same logic as cost_ml_model/build_day_costs.py's _to_hospital_day:
    calendar-day difference from admission, floored at 0."""
    return [max((d - admit_date).days, 0) for d in event_dates]


def build_live_feature_row(hadm_id: int, conn, feature_cols: list,
                            hospital_day: Optional[int] = None) -> pd.DataFrame:
    """
    Returns a single-row DataFrame with exactly `feature_cols` columns
    (matching a trained model's bundle["features"]), built from this
    patient's real data in Postgres, as of the end of `hospital_day`.

    Raises ValueError if the hadm_id isn't found in active_patients.
    """
    _load_mappings()

    ap = conn.execute(text("""
        SELECT hadm_id, subject_id, gender, anchor_age, insurance, admission_type,
               admit_time, primary_diagnosis_title, created_at, estimate_generated_at, los_days
        FROM active_patients WHERE hadm_id = :h
    """), {"h": hadm_id}).fetchone()
    if ap is None:
        raise ValueError(f"hadm_id {hadm_id} not found in active_patients")

    admit_dt = ap.admit_time
    if admit_dt is None:
        raise ValueError(f"hadm_id {hadm_id} has no admit_time yet — data may still be fetching")
    admit_date = admit_dt.date() if isinstance(admit_dt, datetime) else admit_dt

    if hospital_day is None:
        # admit_time is MIMIC's de-identified, shifted date (e.g. year 2140) --
        # NOT usable against real wall-clock "today". Day 0 = the moment we
        # actually start tracking this patient (estimate_generated_at, stamped
        # fresh every time "Generate Cost Estimate" is clicked). If that was
        # never clicked, there's no valid real-world anchor yet -- stay at
        # Day 0 rather than backdating to created_at (row-insert time), which
        # could be arbitrarily far in the past and made the day counter drift
        # upward for reasons unrelated to this patient's actual care.
        # admit_time is still used below for placing each individual clinical
        # event at its correct relative day WITHIN the stay, since that
        # preserves MIMIC's real event spacing.
        if ap.estimate_generated_at is None:
            hospital_day = 0
        else:
            anchor_date = ap.estimate_generated_at.date() if isinstance(ap.estimate_generated_at, datetime) else ap.estimate_generated_at
            hospital_day = max((date.today() - anchor_date).days, 0)

        # Freeze at the patient's real MIMIC length-of-stay once reached --
        # don't keep inventing new "ward days" past the end of their actual
        # clinical record just because real-world time keeps passing.
        if ap.los_days is not None:
            hospital_day = min(hospital_day, int(ap.los_days))

    # ── Static fields ──────────────────────────────────────────────────
    icu_flag = conn.execute(text(
        "SELECT COUNT(*) FROM ap_icustays WHERE hadm_id = :h"), {"h": hadm_id}).scalar() > 0

    svc_row = conn.execute(text("""
        SELECT curr_service FROM ap_services WHERE hadm_id = :h
        ORDER BY transfertime ASC NULLS LAST LIMIT 1
    """), {"h": hadm_id}).fetchone()
    treating_specialty = svc_row.curr_service if svc_row else "Unknown"

    # ── Day-level ICU/Ward tagging, up through hospital_day ────────────
    xfr_rows = conn.execute(text("""
        SELECT careunit, intime, outtime FROM ap_transfers WHERE hadm_id = :h AND intime IS NOT NULL
    """), {"h": hadm_id}).fetchall()
    icu_days = set()
    for r in xfr_rows:
        if r.careunit and "ICU" in r.careunit.upper():
            start_day = max((r.intime.date() - admit_date).days, 0)
            end_dt = r.outtime if r.outtime else r.intime
            end_day = max((end_dt.date() - admit_date).days, start_day)
            icu_days.update(range(start_day, end_day + 1))
    was_in_icu_today = 1 if hospital_day in icu_days else 0
    cumulative_icu_days_so_far = sum(1 for d in icu_days if d <= hospital_day)

    # ── Event-level costs, day by day, through hospital_day ────────────
    proc_rows = conn.execute(text(
        "SELECT icd_code, chartdate FROM ap_procedures WHERE hadm_id = :h"), {"h": hadm_id}).fetchall()
    med_rows = conn.execute(text(
        "SELECT drug, starttime FROM ap_prescriptions WHERE hadm_id = :h AND starttime IS NOT NULL"),
        {"h": hadm_id}).fetchall()
    lab_rows = conn.execute(text(
        "SELECT itemid, charttime FROM ap_labevents WHERE hadm_id = :h AND charttime IS NOT NULL"),
        {"h": hadm_id}).fetchall()

    def _price(rows, date_attr, code_attr, mapping):
        prices_by_day = {}
        for r in rows:
            d = getattr(r, date_attr)
            d = d.date() if isinstance(d, datetime) else d
            day = max((d - admit_date).days, 0)
            code = getattr(r, code_attr)
            price = mapping.get(code, mapping.mean())
            prices_by_day[day] = prices_by_day.get(day, 0) + price
        return prices_by_day

    proc_by_day = _price(proc_rows, "chartdate", "icd_code", _PROC_MAP)
    med_by_day = _price(med_rows, "starttime", "drug", _MED_MAP)
    lab_by_day = _price(lab_rows, "charttime", "itemid", _LAB_MAP)

    # Day 0 = the moment of admission: nothing has been performed on the
    # patient yet, only the diagnosis is known (confirmed against training
    # data -- 908/7077, 12.8%, of real Day-0 rows have zero meds/labs/procs,
    # so this isn't an out-of-distribution input for the model). Real
    # same-day activity only starts counting from Day 1 onward, once days
    # have actually started and things get performed on the patient.
    if hospital_day == 0:
        day_procedures_cost = 0
        day_medicines_cost = 0
        day_labs_cost = 0
    else:
        day_procedures_cost = proc_by_day.get(hospital_day, 0)
        day_medicines_cost = med_by_day.get(hospital_day, 0)
        day_labs_cost = lab_by_day.get(hospital_day, 0)
    day_ward_cost = 0 if was_in_icu_today else WARD_RATE
    day_icu_cost = ICU_RATE if was_in_icu_today else 0
    day_total_cost = day_procedures_cost + day_medicines_cost + day_labs_cost + day_ward_cost + day_icu_cost

    breakdown = {"procedures": 0.0, "medicines": 0.0, "labs": 0.0, "ward": 0.0, "icu": 0.0}
    for d in range(0, hospital_day + 1):
        d_ward = 0 if d in icu_days else WARD_RATE
        d_icu = ICU_RATE if d in icu_days else 0
        if d > 0:
            breakdown["procedures"] += proc_by_day.get(d, 0)
            breakdown["medicines"] += med_by_day.get(d, 0)
            breakdown["labs"] += lab_by_day.get(d, 0)
        breakdown["ward"] += d_ward
        breakdown["icu"] += d_icu
    cumulative_cost_so_far = sum(breakdown.values())
    cost_per_day_so_far = cumulative_cost_so_far / (hospital_day + 1)

    # LOS submodel's extra engineered features (cost_ml_model/train_los_predictor_experiment.py) --
    # harmless to compute unconditionally: the cost model's feature_cols doesn't
    # include these keys, so they're silently dropped for that caller below.
    _activity_days = range(1, hospital_day + 1) if hospital_day == 0 else range(hospital_day + 1)
    cumulative_procedures_so_far = sum(1 for d in _activity_days if proc_by_day.get(d, 0) > 0)
    cumulative_medicines_so_far = sum(1 for d in _activity_days if med_by_day.get(d, 0) > 0)
    cumulative_labs_so_far = sum(1 for d in _activity_days if lab_by_day.get(d, 0) > 0)
    cost_trend_ratio = (day_total_cost / cost_per_day_so_far) if cost_per_day_so_far else 1.0

    today_breakdown = {
        "procedures": round(day_procedures_cost, 2),
        "medicines": round(day_medicines_cost, 2),
        "labs": round(day_labs_cost, 2),
        "ward": round(day_ward_cost, 2),
        "icu": round(day_icu_cost, 2),
        "total": round(day_total_cost, 2),
    }

    # ── Assemble raw fields, then align to the model's exact one-hot columns ──
    row = {
        "age_at_admission": ap.anchor_age,
        "hospital_day": hospital_day,
        "cumulative_cost_so_far": cumulative_cost_so_far,
        "cost_per_day_so_far": cost_per_day_so_far,
        "gender_is_male": 1 if (ap.gender or "").upper() == "M" else 0,
        "icu_flag": int(icu_flag),
        "was_in_icu_today": was_in_icu_today,
        "had_procedure_today": 1 if day_procedures_cost > 0 else 0,
        "had_medicine_today": 1 if day_medicines_cost > 0 else 0,
        "had_lab_today": 1 if day_labs_cost > 0 else 0,
        "day_procedures_cost": day_procedures_cost,
        "day_medicines_cost": day_medicines_cost,
        "day_labs_cost": day_labs_cost,
        "day_ward_cost": day_ward_cost,
        "day_icu_cost": day_icu_cost,
        "day_total_cost": day_total_cost,
        "cumulative_icu_days_so_far": cumulative_icu_days_so_far,
        "cumulative_procedures_so_far": cumulative_procedures_so_far,
        "cumulative_medicines_so_far": cumulative_medicines_so_far,
        "cumulative_labs_so_far": cumulative_labs_so_far,
        "cost_trend_ratio": cost_trend_ratio,
    }

    out = {c: 0 for c in feature_cols}
    for k, v in row.items():
        if k in out:
            out[k] = v

    admission_type_col = f"admission_type_{(ap.admission_type or '').upper()}"
    insurance_col = f"insurance_{(ap.insurance or 'UNKNOWN').upper()}"
    diagnosis_col = f"primary_diagnosis_grouped_{ap.primary_diagnosis_title}"
    specialty_col = f"treating_specialty_{treating_specialty}"
    for col in [admission_type_col, insurance_col, diagnosis_col, specialty_col]:
        if col in out:
            out[col] = 1
    if diagnosis_col not in out and "primary_diagnosis_grouped_Other" in out:
        out["primary_diagnosis_grouped_Other"] = 1  # unseen diagnosis -> "Other" bucket

    # Shrinkage-based cost band (Low/Mid-Low/Mid-High/High, k=3) -- supplements
    # the top-15+Other grouping above with real cost signal for every
    # diagnosis, not just the 15 most frequent ones. Unseen diagnosis ->
    # Mid-Low, close to the population average, same fallback used at
    # training time (see add_diagnosis_cost_band_feature.py).
    band = _DIAG_BAND_MAP.get(ap.primary_diagnosis_title, "Mid-Low")
    band_col = f"primary_diagnosis_cost_band_{band}"
    if band_col in out:
        out[band_col] = 1

    return pd.DataFrame([out])[feature_cols], breakdown, today_breakdown, admit_date
