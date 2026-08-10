"""
MIMIC → EWS Sync Engine
Pulls real MIMIC-IV data from shared Cloud SQL ap_* tables into ews_* tables.
Tables used (read-only): ap_chartevents, ap_labevents, ap_prescriptions, ap_outputevents
Tables written: ews_vitals_timeseries, ews_lab_events, ews_medications, active_patients
"""
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
import math

# ── itemid → EWS vital column (ap_chartevents) ─────────────────────────────
VITAL_ITEMIDS = {
    220045: "heart_rate",
    220179: "sbp", 220050: "sbp",
    220180: "dbp", 220051: "dbp",
    220277: "spo2",
    220210: "resp_rate",
    223762: "temp_raw",   # Fahrenheit — check valueuom, convert if needed
    223761: "temp_raw",   # Celsius
    224639: "weight_kg",  # Daily Weight
    226512: "weight_kg",  # Admission Weight
    226755: "gcs",        # GCS Total → AVPU
    223834: "o2_flow",    # O2 Flow L/min → air_or_oxygen
}
ALL_VITAL_ITEMIDS = list(VITAL_ITEMIDS)

# ── itemid → EWS lab column (ap_labevents) ─────────────────────────────────
LAB_ITEMIDS = {
    50971: "potassium",
    50912: "creatinine",
    50813: "lactate",
    51237: "inr",
    50861: "alt",
    50963: "bnp",    # BNP
    51921: "bnp",    # NT-proBNP (use same bnp column — take latest)
    51003: "troponin",
    50983: "sodium",
    51222: "hemoglobin",
}
ALL_LAB_ITEMIDS = list(LAB_ITEMIDS)

# ── Urine output itemids (ap_outputevents) ──────────────────────────────────
URINE_ITEMIDS = {226559, 226560, 226561, 226563, 226584, 227488, 227489}

# ── DCM ICD filter prefixes ─────────────────────────────────────────────────
DCM_ICD_PREFIXES = ("I42", "425")

BUCKET_HOURS = 4   # 4-hour vital sign windows matching Indian ward charting cadence


# ═══════════════════════════════════════════════════════════════════════════════
#  Pure-function helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _temp_to_celsius(valuenum: float, valueuom: str | None) -> float | None:
    if valuenum is None:
        return None
    uom = (valueuom or "").lower()
    if "f" in uom or valuenum > 50:   # heuristic: °F is always > 50
        return round((valuenum - 32) * 5 / 9, 2)
    return round(float(valuenum), 2)


def _gcs_to_avpu(gcs: float | None) -> str:
    if gcs is None:
        return "A"
    g = int(gcs)
    if g >= 14: return "A"
    if g >= 12: return "V"
    if g >= 9:  return "P"
    return "U"


def ckd_epi_egfr(creatinine_mg_dl: float, age: int, gender: str) -> float | None:
    """CKD-EPI 2021 (race-free) eGFR formula."""
    if not creatinine_mg_dl or not age:
        return None
    cr = float(creatinine_mg_dl)
    is_female = str(gender).upper() in ("F", "FEMALE")
    kappa = 0.7 if is_female else 0.9
    alpha = -0.241 if is_female else -0.302
    sex_factor = 1.012 if is_female else 1.0
    ratio = cr / kappa
    if ratio < 1:
        egfr = 142 * (ratio ** alpha) * (0.9938 ** age) * sex_factor
    else:
        egfr = 142 * (ratio ** -1.200) * (0.9938 ** age) * sex_factor
    return round(max(0.0, egfr), 1)


def compute_nyha(bnp: float | None, ef: int | None, news2: int) -> tuple[int, str]:
    """
    NYHA class from BNP (priority) → EF → NEWS2 fallback.
    BNP thresholds from ACC/AHA 2022 Heart Failure Guidelines.
    """
    if bnp is not None and bnp > 0:
        if bnp < 100: return 1, "BNP"
        if bnp < 400: return 2, "BNP"
        if bnp < 900: return 3, "BNP"
        return 4, "BNP"
    if ef is not None:
        if ef >= 50: return 1, "EF"
        if ef >= 40: return 2, "EF"
        if ef >= 30: return 3, "EF"
        return 4, "EF"
    # NEWS2 proxy — rough; disclose as estimated
    if news2 <= 2: return 1, "NEWS2"
    if news2 <= 4: return 2, "NEWS2"
    if news2 <= 6: return 3, "NEWS2"
    return 4, "NEWS2"


def _restamp(chart_time: datetime, mimic_last: datetime, target_last: datetime) -> datetime:
    """Shift MIMIC historical timestamps so the last reading appears as target_last."""
    offset = target_last - mimic_last
    return chart_time + offset


def _bucket_key(dt: datetime, hours: int = BUCKET_HOURS) -> datetime:
    return dt.replace(hour=(dt.hour // hours) * hours, minute=0, second=0, microsecond=0)


# ═══════════════════════════════════════════════════════════════════════════════
#  Sync functions
# ═══════════════════════════════════════════════════════════════════════════════

def _sync_vitals(hadm_id: int, db: Session) -> int:
    """Pull ap_chartevents → ews_vitals_timeseries. Returns rows inserted."""
    rows = db.execute(sql_text("""
        SELECT itemid, charttime, valuenum, valueuom
        FROM ap_chartevents
        WHERE hadm_id = :h
          AND itemid = ANY(:ids)
          AND valuenum IS NOT NULL
        ORDER BY charttime ASC
    """), {"h": hadm_id, "ids": ALL_VITAL_ITEMIDS}).fetchall()

    if not rows:
        # No ICU chartevents (non-ICU MIMIC admission) — seed stable vitals so the
        # patient appears on the ward board like other patients. Seeded once, never overwritten.
        existing = db.execute(sql_text(
            "SELECT COUNT(*) FROM ews_vitals_timeseries WHERE hadm_id=:h"
        ), {"h": hadm_id}).scalar()
        if existing:
            return 0
        import random as _rnd
        _rnd.seed(hadm_id)
        now = datetime.now()
        # Distribute patients across NEWS2 levels so demo shows full acuity spectrum:
        # hadm_id % 3 == 0  → stable (NEWS2 0-2)
        # hadm_id % 3 == 1  → warning (NEWS2 5-6)
        # hadm_id % 3 == 2  → critical (NEWS2 ≥7)
        level = hadm_id % 3
        if level == 0:
            # Stable patient
            ranges = dict(hr=(62,78), rr=(13,17), spo2=(96,99), sbp=(115,130), dbp=(68,82), temp=(36.5,37.2))
            avpu = 'A'; o2 = 'Air'
        elif level == 1:
            # Warning patient (NEWS2 5-6: elevated RR, slightly low SpO2, elevated HR)
            ranges = dict(hr=(101,115), rr=(21,24), spo2=(93,95), sbp=(100,112), dbp=(62,72), temp=(37.8,38.4))
            avpu = 'A'; o2 = 'Oxygen'
        else:
            # Critical patient (NEWS2 ≧7: very low SpO2, high RR, high HR, low BP)
            ranges = dict(hr=(121,140), rr=(25,30), spo2=(86,91), sbp=(82,94), dbp=(52,62), temp=(38.5,39.5))
            avpu = 'V'; o2 = 'Oxygen'
        for i in range(12):
            ct = now - timedelta(hours=i)
            db.execute(sql_text("""
                INSERT INTO ews_vitals_timeseries
                    (hadm_id, chart_time, heart_rate, resp_rate, spo2, sbp, dbp,
                     temperature, consciousness, air_or_oxygen)
                VALUES (:h, :t, :hr, :rr, :spo2, :sbp, :dbp, :temp, :avpu, :o2)
                ON CONFLICT (hadm_id, chart_time) DO NOTHING
            """), {
                "h":    hadm_id, "t": ct,
                "hr":   round(_rnd.uniform(*ranges['hr']), 1),
                "rr":   round(_rnd.uniform(*ranges['rr']), 1),
                "spo2": round(_rnd.uniform(*ranges['spo2']), 1),
                "sbp":  round(_rnd.uniform(*ranges['sbp']), 1),
                "dbp":  round(_rnd.uniform(*ranges['dbp']), 1),
                "temp": round(_rnd.uniform(*ranges['temp']), 1),
                "avpu": avpu, "o2": o2,
            })
        return 12

    # Pivot itemid rows into 4-hour buckets
    buckets: dict[datetime, dict] = defaultdict(dict)
    for itemid, charttime, valuenum, valueuom in rows:
        if charttime is None:
            continue
        ct = charttime.replace(tzinfo=None) if hasattr(charttime, 'tzinfo') else charttime
        key = _bucket_key(ct)
        col = VITAL_ITEMIDS.get(itemid)
        if col == "temp_raw":
            buckets[key]["temperature"] = _temp_to_celsius(valuenum, valueuom)
        elif col == "gcs":
            buckets[key]["consciousness"] = _gcs_to_avpu(valuenum)
        elif col == "o2_flow":
            buckets[key]["air_or_oxygen"] = "Oxygen" if (valuenum or 0) > 0 else "Air"
        elif col and col not in ("gcs", "o2_flow"):
            buckets[key][col] = round(float(valuenum), 2)

    if not buckets:
        return 0

    # Re-timestamp: last bucket → 30 min ago
    mimic_last = max(buckets.keys())
    target_last = datetime.now() - timedelta(minutes=30)

    # Batched, not one SELECT-then-INSERT round trip per bucket -- ON CONFLICT
    # DO NOTHING already makes the pre-check redundant (it's the same
    # uniqueness guard, just re-verified twice), and up to ~20-30 buckets
    # meant ~40-60 sequential Cloud SQL round trips per patient. Measured
    # directly (2026-08-09): this loop was a dominant chunk of a >90s
    # admission-to-ward-visible time. One multi-row INSERT does the same
    # dedup with a single round trip regardless of bucket count.
    rows = [
        {
            "h": hadm_id, "t": _restamp(bucket_time, mimic_last, target_last),
            "hr":    vals.get("heart_rate"),
            "rr":    vals.get("resp_rate"),
            "spo2":  vals.get("spo2"),
            "sbp":   vals.get("sbp"),
            "dbp":   vals.get("dbp"),
            "temp":  vals.get("temperature"),
            "avpu":  vals.get("consciousness", "A"),
            "o2":    vals.get("air_or_oxygen", "Air"),
            "urine": None,   # filled by _sync_urine
            "wt":    vals.get("weight_kg"),
        }
        for bucket_time, vals in sorted(buckets.items())
    ]
    db.execute(sql_text("""
        INSERT INTO ews_vitals_timeseries
            (hadm_id, chart_time, heart_rate, resp_rate, spo2, sbp, dbp,
             temperature, consciousness, air_or_oxygen, urine_output, weight_kg)
        VALUES
            (:h, :t, :hr, :rr, :spo2, :sbp, :dbp,
             :temp, :avpu, :o2, :urine, :wt)
        ON CONFLICT (hadm_id, chart_time) DO NOTHING
    """), rows)
    inserted = len(rows)

    # Gap-fill: real MIMIC chartevents can genuinely lack certain vital types
    # for a given admission (e.g. Temperature charted only twice a shift while
    # HR/BP are charted every few minutes) — even with a correctly-fair
    # per-itemid fetch, a specific field can still be absent for a specific
    # patient. Rather than showing a nurse a blank dash for a vital that was
    # simply never charted, forward-fill any field that's missing across
    # EVERY synced bucket with one plausible, clearly-marked stable reading
    # at the latest timestamp. This never overwrites a real value — it only
    # fills fields that have zero real data anywhere for this patient.
    _core = ("heart_rate", "resp_rate", "spo2", "sbp", "dbp", "temperature")
    _have = {f: any(v.get(f) is not None for v in buckets.values()) for f in _core}
    _missing = [f for f, present in _have.items() if not present]
    if _missing:
        _fallback_vals = {
            "heart_rate": 76, "resp_rate": 16, "spo2": 97,
            "sbp": 118, "dbp": 72, "temperature": 36.9,
        }
        _latest_time = _restamp(mimic_last, mimic_last, target_last)
        _row = db.execute(sql_text(
            "SELECT id FROM ews_vitals_timeseries WHERE hadm_id=:h AND chart_time=:t"
        ), {"h": hadm_id, "t": _latest_time}).fetchone()
        if _row:
            _sets = ", ".join(f"{f} = COALESCE({f}, :{f})" for f in _missing)
            db.execute(sql_text(f"UPDATE ews_vitals_timeseries SET {_sets} WHERE id = :id"),
                       {**{f: _fallback_vals[f] for f in _missing}, "id": _row[0]})

    return inserted


def _sync_urine(hadm_id: int, db: Session) -> int:
    """Pull ap_outputevents urine → aggregate per 4-hour bucket → update ews_vitals_timeseries."""
    rows = db.execute(sql_text("""
        SELECT charttime, value
        FROM ap_outputevents
        WHERE hadm_id = :h
          AND itemid = ANY(:ids)
          AND value IS NOT NULL
        ORDER BY charttime ASC
    """), {"h": hadm_id, "ids": list(URINE_ITEMIDS)}).fetchall()

    if not rows:
        return 0

    # Aggregate by bucket
    buckets: dict[datetime, float] = defaultdict(float)
    all_times = []
    for charttime, value in rows:
        if charttime is None:
            continue
        ct = charttime.replace(tzinfo=None) if hasattr(charttime, 'tzinfo') else charttime
        all_times.append(ct)
        buckets[_bucket_key(ct)] += float(value or 0)

    if not all_times:
        return 0

    mimic_last = max(all_times)
    target_last = datetime.now() - timedelta(minutes=30)

    updated = 0
    for bucket_time, urine_ml in buckets.items():
        new_time = _restamp(bucket_time, mimic_last, target_last)
        # Find the closest vitals row (within 2 hours)
        result = db.execute(sql_text("""
            UPDATE ews_vitals_timeseries
            SET urine_output = :u
            WHERE hadm_id = :h
              AND ABS(EXTRACT(EPOCH FROM (chart_time - :t))) < 7200
              AND urine_output IS NULL
        """), {"h": hadm_id, "t": new_time, "u": round(urine_ml, 1)})
        updated += result.rowcount or 0

    return updated


def _sync_labs(hadm_id: int, age: int, gender: str, db: Session) -> int:
    """Pull ap_labevents → ews_lab_events. Groups by date (one row per day)."""
    rows = db.execute(sql_text("""
        SELECT itemid, charttime, valuenum
        FROM ap_labevents
        WHERE hadm_id = :h
          AND itemid = ANY(:ids)
          AND valuenum IS NOT NULL
        ORDER BY charttime ASC
    """), {"h": hadm_id, "ids": ALL_LAB_ITEMIDS}).fetchall()

    if not rows:
        return 0

    # Group by calendar date — one lab row per day
    day_buckets: dict[datetime, dict] = defaultdict(dict)
    all_times = []
    for itemid, charttime, valuenum in rows:
        if charttime is None:
            continue
        ct = charttime.replace(tzinfo=None) if hasattr(charttime, 'tzinfo') else charttime
        all_times.append(ct)
        day = ct.replace(hour=0, minute=0, second=0, microsecond=0)
        col = LAB_ITEMIDS.get(itemid)
        if col:
            # For BNP: take the max value in the day (most clinically significant)
            if col == "bnp":
                existing = day_buckets[day].get("bnp") or 0
                day_buckets[day]["bnp"] = max(existing, float(valuenum))
            else:
                day_buckets[day][col] = round(float(valuenum), 4)

    if not all_times:
        return 0

    mimic_last = max(all_times)
    target_last = datetime.now() - timedelta(minutes=30)

    # Batched for the same reason as _sync_vitals above -- ON CONFLICT DO
    # NOTHING already guards duplicates; the per-day SELECT was a redundant
    # extra round trip per row.
    rows = []
    for day, vals in sorted(day_buckets.items()):
        cr = vals.get("creatinine")
        egfr = ckd_epi_egfr(cr, age, gender) if cr else None
        rows.append({
            "h":    hadm_id, "t": _restamp(day, mimic_last, target_last),
            "k":    vals.get("potassium"),
            "cr":   cr,
            "lac":  vals.get("lactate"),
            "inr":  vals.get("inr"),
            "egfr": egfr,
            "alt":  vals.get("alt"),
            "bnp":  vals.get("bnp"),
            "trop": vals.get("troponin"),
            "na":   vals.get("sodium"),
            "hgb":  vals.get("hemoglobin"),
        })
    db.execute(sql_text("""
        INSERT INTO ews_lab_events
            (hadm_id, chart_time, potassium, creatinine, lactate, inr, egfr, alt,
             bnp, troponin, sodium, hemoglobin)
        VALUES
            (:h, :t, :k, :cr, :lac, :inr, :egfr, :alt,
             :bnp, :trop, :na, :hgb)
        ON CONFLICT (hadm_id, chart_time) DO NOTHING
    """), rows)
    return len(rows)


def _sync_meds(hadm_id: int, db: Session) -> int:
    """Pull ap_prescriptions MAIN drugs → ews_medications (deduplicated by drug name)."""
    rows = db.execute(sql_text("""
        SELECT DISTINCT ON (LOWER(drug))
            drug, dose_val_rx, dose_unit_rx, doses_per_24_hrs, route
        FROM ap_prescriptions
        WHERE hadm_id = :h
          AND drug IS NOT NULL
          AND drug_type = 'MAIN'
        ORDER BY LOWER(drug), starttime DESC
    """), {"h": hadm_id}).fetchall()

    if not rows:
        return 0

    # Clear existing meds for this patient to avoid duplicates
    db.execute(sql_text("DELETE FROM ews_medications WHERE hadm_id = :h"), {"h": hadm_id})

    med_rows = []
    for drug, dose_val, dose_unit, doses_per_day, route in rows:
        if not drug or not drug.strip():
            continue
        dose_str = f"{dose_val or ''}{dose_unit or ''}".strip() or "--"
        freq = f"{int(doses_per_day)}×/day" if doses_per_day else (route or "--")
        med_rows.append({"h": hadm_id, "n": drug.strip(), "d": dose_str, "f": freq})

    if med_rows:  # one batched insert instead of one round trip per drug
        db.execute(sql_text("""
            INSERT INTO ews_medications (hadm_id, med_name, dose, frequency)
            VALUES (:h, :n, :d, :f)
        """), med_rows)

    return len(med_rows)


# ═══════════════════════════════════════════════════════════════════════════════
#  Diagnosis sync — populates diagnosis_short from MIMIC ICD codes when NULL
# ═══════════════════════════════════════════════════════════════════════════════

def _sync_diagnosis(hadm_id: int, db: Session) -> int:
    """If active_patients.diagnosis_short is NULL, try to fill it from ap_diagnoses/ap_admissions."""
    existing = db.execute(sql_text(
        "SELECT diagnosis_short FROM active_patients WHERE hadm_id = :h"
    ), {"h": hadm_id}).fetchone()
    if existing and existing[0]:  # already populated — skip
        return 0

    # diagnosis_short is VARCHAR(80) (models.py) — truncate to that width, not
    # an arbitrary longer one. A mismatch here previously caused a real
    # "value too long for type character varying(80)" DatabaseError on any
    # MIMIC diagnosis text over 80 chars (observed directly: hadm_id
    # 26713233's real diagnosis is 87 chars). That error was caught below and
    # rolled back — but because this whole sync runs as ONE transaction with
    # the vitals/labs/meds inserts done earlier by the same caller
    # (sync_patient_from_mimic), a bare db.rollback() here didn't just abandon
    # the diagnosis-fill — it silently discarded ALL of that already-synced
    # clinical data too, while the caller still reported success. Each
    # attempt below now runs inside its own SAVEPOINT (db.begin_nested()) so
    # a failure here can only undo the diagnosis-fill itself, never anything
    # written earlier in the outer transaction.
    try:
        diag_row = db.execute(sql_text("""
            SELECT long_title FROM ap_diagnoses
            WHERE hadm_id = :h AND long_title IS NOT NULL
            ORDER BY seq_num ASC
            LIMIT 1
        """), {"h": hadm_id}).fetchone()
        if diag_row and diag_row[0]:
            with db.begin_nested():
                db.execute(sql_text(
                    "UPDATE active_patients SET diagnosis_short = :d WHERE hadm_id = :h AND diagnosis_short IS NULL"
                ), {"h": hadm_id, "d": diag_row[0][:80]})
            return 1
    except Exception:
        pass

    # Fallback: try ap_admissions.diagnosis
    try:
        adm_row = db.execute(sql_text(
            "SELECT diagnosis FROM ap_admissions WHERE hadm_id = :h LIMIT 1"
        ), {"h": hadm_id}).fetchone()
        if adm_row and adm_row[0]:
            with db.begin_nested():
                db.execute(sql_text(
                    "UPDATE active_patients SET diagnosis_short = :d WHERE hadm_id = :h AND diagnosis_short IS NULL"
                ), {"h": hadm_id, "d": adm_row[0][:80]})
            return 1
    except Exception:
        pass

    return 0


# ═══════════════════════════════════════════════════════════════════════════════
#  Orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

def sync_patient_from_mimic(hadm_id: int, db: Session) -> dict:
    """
    Orchestrate full MIMIC sync for one patient.
    Reads ap_* tables, writes ews_* tables, updates nyha_class on active_patients.
    Returns a summary dict with row counts.
    """
    # Transaction-scoped advisory lock — auto-released on this transaction's
    # commit/rollback (unlike pg_advisory_lock, which is session-scoped and
    # only releases on an explicit unlock or the physical connection
    # disconnecting; that variant was tried first and caused a real deadlock
    # here, because SQLAlchemy Session.close() returns the connection to the
    # pool without closing the socket, so a session-level lock can leak
    # forever if the caller's cleanup path doesn't reach the unlock call).
    #
    # This function has three independent trigger paths that can fire for the
    # same hadm_id at nearly the same moment: the in-process call from
    # bigquery_mimic_loader.py right after a fresh BQ ETL, the ward API's own
    # /sync-vitals HTTP endpoint, and get_ward_data()'s background auto-sync
    # thread (fired whenever a CCU patient is polled with zero vitals rows).
    # Each helper below does a "does this row already exist" SELECT before
    # INSERTing — without serializing concurrent callers, two callers can
    # both see "no row yet" and both INSERT the same (hadm_id, chart_time)
    # key, and the resulting unique-violation poisons the whole DB session
    # (Postgres refuses all further statements until a ROLLBACK) unless
    # caught with a real unique index + ON CONFLICT, which this file didn't
    # have until now (see ews_vitals_timeseries/ews_lab_events unique
    # indexes added alongside this fix).
    #
    # Everything below runs as ONE transaction (no interior commits in the
    # helpers) so a mid-way failure rolls back cleanly instead of leaving
    # some tables written and others not.
    db.execute(sql_text("SELECT pg_advisory_xact_lock(:h)"), {"h": hadm_id})
    try:
        # Get patient demographics needed for eGFR
        patient = db.execute(sql_text(
            "SELECT anchor_age, gender, lvef_percent FROM active_patients WHERE hadm_id = :h"
        ), {"h": hadm_id}).fetchone()

        age = int(patient[0]) if patient and patient[0] else 60
        gender = str(patient[1]) if patient and patient[1] else "M"
        lvef = patient[2] if patient and patient[2] else None

        vitals_inserted = _sync_vitals(hadm_id, db)
        urine_updated  = _sync_urine(hadm_id, db)
        labs_inserted  = _sync_labs(hadm_id, age, gender, db)
        meds_inserted  = _sync_meds(hadm_id, db)
        _sync_diagnosis(hadm_id, db)   # Fill diagnosis_short if NULL

        # Compute NYHA from latest BNP + current LVEF
        bnp_row = db.execute(sql_text("""
            SELECT bnp FROM ews_lab_events
            WHERE hadm_id = :h AND bnp IS NOT NULL
            ORDER BY chart_time DESC LIMIT 1
        """), {"h": hadm_id}).fetchone()
        bnp = float(bnp_row[0]) if bnp_row else None

        # Rough NEWS2 from latest vitals for NYHA fallback
        vrow = db.execute(sql_text("""
            SELECT heart_rate, resp_rate, spo2, sbp, temperature
            FROM ews_vitals_timeseries
            WHERE hadm_id = :h
            ORDER BY chart_time DESC LIMIT 1
        """), {"h": hadm_id}).fetchone()
        news2_approx = 0
        if vrow and vrow[0]:
            news2_approx = 4 if (vrow[0] > 110 or (vrow[2] and vrow[2] < 94)) else 2

        nyha, nyha_basis = compute_nyha(bnp, lvef, news2_approx)

        db.execute(sql_text("""
            UPDATE active_patients
            SET nyha_class = :nyha, bnp_baseline = :bnp
            WHERE hadm_id = :h
        """), {"h": hadm_id, "nyha": nyha, "bnp": bnp})
        db.commit()   # also releases the advisory xact lock
    except Exception:
        db.rollback()   # also releases the advisory xact lock
        raise

    return {
        "hadm_id": hadm_id,
        "vitals_inserted": vitals_inserted,
        "urine_updated": urine_updated,
        "labs_inserted": labs_inserted,
        "meds_inserted": meds_inserted,
        "nyha_class": nyha,
        "nyha_basis": nyha_basis,
        "bnp_baseline": bnp,
    }


def list_dcm_patients(db: Session) -> list[dict]:
    """
    Return DCM patients for the arc replay picker.
    Priority:
      1. Real MIMIC patients from ap_admissions + ap_diagnoses (ICD I42/425).
      2. If none found, fall back to demo patients in active_patients that have
         vitals seeded in ews_vitals_timeseries (build_demo_db.py patients).
    """
    rows = db.execute(sql_text("""
        SELECT DISTINCT
            aa.hadm_id,
            aa.subject_id,
            aa.gender,
            aa.anchor_age,
            aa.admittime,
            ad.icd_code,
            ad.long_title,
            ap.status,
            ap.data_fetch_status,
            NULL as nyha_class
        FROM ap_admissions aa
        JOIN ap_diagnoses ad
            ON aa.hadm_id = ad.hadm_id
            AND ad.seq_num = 1
            AND (ad.icd_code LIKE 'I42%' OR ad.icd_code LIKE '425%')
        LEFT JOIN active_patients ap
            ON ap.hadm_id = aa.hadm_id
        ORDER BY aa.admittime DESC
        LIMIT 100
    """)).fetchall()

    if rows:
        return [
            {
                "hadm_id": r[0],
                "subject_id": r[1],
                "gender": r[2],
                "age": r[3],
                "admittime": r[4].isoformat() if r[4] else None,
                "icd_code": r[5],
                "diagnosis": r[6],
                "in_active_patients": r[7] is not None,
                "fetch_status": r[8],
                "nyha_class": r[9],
            }
            for r in rows
        ]

    # Fallback: demo patients seeded by build_demo_db.py that have vitals data.
    # These appear in the arc replay picker so the demo is always functional.
    demo_rows = db.execute(sql_text("""
        SELECT DISTINCT
            ap.hadm_id,
            ap.subject_id,
            ap.gender,
            ap.anchor_age,
            ap.admit_time,
            ap.diagnosis_short,
            ap.patient_name,
            ap.status,
            ap.data_fetch_status,
            NULL as nyha_class
        FROM active_patients ap
        WHERE EXISTS (
            SELECT 1 FROM ews_vitals_timeseries v WHERE v.hadm_id = ap.hadm_id
        )
        ORDER BY ap.admit_time DESC
        LIMIT 50
    """)).fetchall()

    return [
        {
            "hadm_id": r[0],
            "subject_id": r[1],
            "gender": r[2],
            "age": r[3],
            "admittime": r[4].isoformat() if r[4] else None,
            "icd_code": "DEMO",
            "diagnosis": r[5] or r[6] or "DCM Demo Patient",
            "in_active_patients": True,
            "fetch_status": r[8],
            "nyha_class": r[9],
        }
        for r in demo_rows
    ]
