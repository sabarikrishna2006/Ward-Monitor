"""
BigQuery MIMIC-IV → Cloud SQL ETL loader.

Fetches patient data from BigQuery and writes it into the Cloud SQL ap_* tables.

Fetch sequence:
  Round 1: admissions, diagnoses, procedures, drgcodes, labevents,
           microbiologyevents, prescriptions, icustays, chartevents,
           transfers, services
  Round 2: pharmacy, poe, omr
  Round 3 (ICU only): procedureevents, datetimeevents, inputevents, outputevents

Usage:
    from backend.app.bigquery_mimic_loader import fetch_and_store_patient
    result = fetch_and_store_patient(hadm_id=20000293, engine=get_engine())
"""
import os, sys, time
from typing import Any

# Ensure backend package is on path when run standalone
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault(
    "GOOGLE_APPLICATION_CREDENTIALS",
    r"C:\Users\ASUS\Desktop\discharge-summary-ai\Foqal_Bucket\foqal-healthcare-project-google.json",
)

from sqlalchemy import text


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _safe_list(data: Any) -> list[dict]:
    """Convert DataFrame, list-of-dicts, or anything else to list[dict]."""
    if data is None:
        return []
    try:
        import pandas as pd
        if isinstance(data, pd.DataFrame):
            return data.where(data.notna(), None).to_dict(orient="records")
    except ImportError:
        pass
    if isinstance(data, list):
        return [dict(r) for r in data]
    return []


def _bulk_insert(conn, table: str, rows: list[dict], pk_col: str | None = None):
    """Batch-insert rows; skip duplicates. Returns count inserted."""
    if not rows:
        return 0
    cols    = list(rows[0].keys())
    ph      = ", ".join(f":{c}" for c in cols)
    col_str = ", ".join(cols)
    conflict = "ON CONFLICT DO NOTHING" if pk_col is None else \
               f"ON CONFLICT ({pk_col}) DO NOTHING"
    sql = text(f"INSERT INTO {table} ({col_str}) VALUES ({ph}) {conflict}")
    conn.execute(sql, rows)
    return len(rows)


def _mark_failed(engine, hadm_id: int, reason: str):
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE active_patients "
            "SET data_fetch_status='failed', fetch_error=:e, updated_at=NOW() "
            "WHERE hadm_id=:h"
        ), {"h": hadm_id, "e": reason})


def _los(adm: dict):
    try:
        delta = adm["dischtime"] - adm["admittime"]
        return round(delta.total_seconds() / 86400, 2)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def fetch_and_store_patient(hadm_id: int, engine, display_only: bool = False) -> dict:
    """
    ETL for one hadm_id.
    display_only=True: loads only metadata tables (fast, ~5s), marks status='partial'.
    display_only=False (default): also loads lazy tabs (labs, meds, charts), marks status='fetched'.
    Returns dict of row counts per table.
    """
    t0 = time.time()
    counts: dict[str, int] = {}

    # ── advisory lock + guard ──────────────────────────────────────────────
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:h)"), {"h": hadm_id})
        row = conn.execute(
            text("SELECT data_fetch_status FROM active_patients WHERE hadm_id=:h"),
            {"h": hadm_id}
        ).fetchone()
        current_status = row[0] if row else None
        # Skip only if fully fetched AND display tables are actually present.
        # Guard: patients loaded by older code may have status="fetched"/"partial" but
        # empty ap_diagnoses (ETL didn't write those tables). Re-run for them.
        if current_status in ("fetched", "partial"):
            has_diag = conn.execute(
                text("SELECT 1 FROM ap_diagnoses WHERE hadm_id = :h LIMIT 1"),
                {"h": hadm_id}
            ).fetchone()
            if has_diag:
                if current_status == "fetched":
                    return {"skipped": True, "reason": "already fetched"}
                if display_only:
                    return {"skipped": True, "reason": "display data already loaded"}
            # No diagnoses → fall through and re-fetch (old ETL didn't save these tables)

        # Ensure row exists (bulk ETL creates patients not registered by billing)
        conn.execute(text("""
            INSERT INTO active_patients (hadm_id, subject_id, status, data_fetch_status)
            VALUES (:h, 0, 'active', 'fetching')
            ON CONFLICT (hadm_id) DO UPDATE
                SET data_fetch_status='fetching', updated_at=NOW()
        """), {"h": hadm_id})

    # ── load from BigQuery ────────────────────────────────────────────────
    print(f"[BQ] hadm_id={hadm_id}  loading display data …")
    from backend.app.bq_mimic_loader import (
        fetch_patient_display,
        fetch_patient_tab,
    )

    data = fetch_patient_display(hadm_id)
    if "error" in data:
        _mark_failed(engine, hadm_id, data["error"])
        return {"error": data["error"]}

    if not display_only:
        print(f"[BQ] hadm_id={hadm_id}  loading lazy tabs …")
        for tab in ["prescriptions", "pharmacy", "poe", "labevents", "chartevents", "fluids",
                    "procedureevents", "emar", "emar_detail", "datetimeevents"]:
            try:
                tab_data = fetch_patient_tab(hadm_id, tab)
                if "error" not in tab_data:
                    data.update(tab_data)
            except Exception as e:
                print(f"[BQ] hadm_id={hadm_id}  tab={tab} skipped: {e}")

    # ── extract raw lists ──────────────────────────────────────────────────
    adm_row     = data.get("admission", data.get("admissions", {}))
    pat_row     = data.get("patient",   data.get("patients",   {}))
    if isinstance(adm_row, list) and adm_row:
        adm_row = adm_row[0]
    if isinstance(pat_row, list) and pat_row:
        pat_row = pat_row[0]

    diag_rows   = _safe_list(data.get("diagnoses",          data.get("diagnoses_icd")))
    proc_rows   = _safe_list(data.get("procedures",         data.get("procedures_icd")))
    drg_rows    = _safe_list(data.get("drgcodes"))
    lab_rows    = _safe_list(data.get("labevents"))
    micro_rows  = _safe_list(data.get("microbiologyevents"))
    rx_rows     = _safe_list(data.get("prescriptions"))
    icu_rows    = _safe_list(data.get("icustays"))
    chart_rows  = _safe_list(data.get("chartevents"))
    xfr_rows    = _safe_list(data.get("transfers"))
    svc_rows    = _safe_list(data.get("services"))
    pharm_rows  = _safe_list(data.get("pharmacy"))
    poe_rows    = _safe_list(data.get("poe"))
    inp_rows    = _safe_list(data.get("fluids",     data.get("inputevents")))
    out_rows    = _safe_list(data.get("outputevents"))
    pe_rows     = _safe_list(data.get("procedureevents"))
    dte_rows    = _safe_list(data.get("datetimeevents"))
    emar_rows   = _safe_list(data.get("emar"))
    emar_d_rows = _safe_list(data.get("emar_detail"))
    has_icu     = len(icu_rows) > 0

    subject_id: int = int(adm_row.get("subject_id") or pat_row.get("subject_id") or 0)

    # ── build merged admissions row ────────────────────────────────────────
    merged_adm = [{
        "hadm_id":             hadm_id,
        "subject_id":          subject_id,
        "admittime":           adm_row.get("admittime"),
        "dischtime":           adm_row.get("dischtime"),
        "deathtime":           adm_row.get("deathtime"),
        "admission_type":      adm_row.get("admission_type"),
        "admit_provider_id":   adm_row.get("admit_provider_id"),
        "admission_location":  adm_row.get("admission_location"),
        "discharge_location":  adm_row.get("discharge_location"),
        "insurance":           adm_row.get("insurance"),
        "language":            adm_row.get("language"),
        "marital_status":      adm_row.get("marital_status"),
        "race":                adm_row.get("race"),
        "edregtime":           adm_row.get("edregtime"),
        "edouttime":           adm_row.get("edouttime"),
        "hospital_expire_flag": adm_row.get("hospital_expire_flag"),
        "gender":              pat_row.get("gender"),
        "anchor_age":          pat_row.get("anchor_age"),
        "anchor_year":         pat_row.get("anchor_year"),
        "anchor_year_group":   pat_row.get("anchor_year_group"),
        "dod":                 pat_row.get("dod"),
    }]

    # Normalise diagnoses keys (GCS loader may use "icd_code"/"icd_version" already)
    def _norm_diag(r):
        return {
            "hadm_id":    hadm_id,
            "subject_id": subject_id,
            "seq_num":    r.get("seq_num", 0),
            "icd_code":   r.get("icd_code", r.get("icd_code")),
            "icd_version": int(r.get("icd_version", 10)),
            "long_title": r.get("long_title"),
        }

    def _norm_proc(r):
        return {
            "hadm_id":    hadm_id,
            "subject_id": subject_id,
            "seq_num":    r.get("seq_num", 0),
            "chartdate":  r.get("chartdate"),
            "icd_code":   r.get("icd_code"),
            "icd_version": int(r.get("icd_version", 10)),
            "long_title": r.get("long_title"),
        }

    def _norm_drg(r):
        return {
            "hadm_id":      hadm_id,
            "subject_id":   subject_id,
            "drg_type":     r.get("drg_type"),
            "drg_code":     str(r.get("drg_code", "")),
            "description":  r.get("description"),
            "drg_severity": r.get("drg_severity"),
            "drg_mortality":r.get("drg_mortality"),
        }

    def _norm_icu(r):
        return {
            "stay_id":         int(r.get("stay_id", 0)),
            "hadm_id":         hadm_id,
            "subject_id":      subject_id,
            "first_careunit":  r.get("first_careunit"),
            "last_careunit":   r.get("last_careunit"),
            "intime":          r.get("intime"),
            "outtime":         r.get("outtime"),
            "los":             r.get("los"),
        }

    def _norm_xfr(r):
        return {
            "transfer_id": int(r.get("transfer_id", 0)),
            "hadm_id":     hadm_id,
            "subject_id":  subject_id,
            "eventtype":   r.get("eventtype"),
            "careunit":    r.get("careunit"),
            "intime":      r.get("intime"),
            "outtime":     r.get("outtime"),
        }

    def _norm_svc(r):
        return {
            "hadm_id":      hadm_id,
            "subject_id":   subject_id,
            "transfertime": r.get("transfertime"),
            "prev_service": r.get("prev_service"),
            "curr_service": r.get("curr_service", ""),
        }

    def _norm_lab(r):
        return {
            "labevent_id":    int(r.get("labevent_id", 0)),
            "hadm_id":        hadm_id,
            "subject_id":     subject_id,
            "specimen_id":    r.get("specimen_id"),
            "itemid":         int(r.get("itemid", 0)),
            "label":          r.get("label"),
            "fluid":          r.get("fluid"),
            "category":       r.get("category"),
            "loinc_code":     r.get("loinc_code"),
            "charttime":      r.get("charttime"),
            "storetime":      r.get("storetime"),
            "value":          str(r.get("value", ""))[:200] if r.get("value") is not None else None,
            "valuenum":       r.get("valuenum"),
            "valueuom":       r.get("valueuom"),
            "ref_range_lower":r.get("ref_range_lower"),
            "ref_range_upper":r.get("ref_range_upper"),
            "flag":           r.get("flag"),
            "priority":       r.get("priority"),
            "comments":       r.get("comments"),
        }

    def _norm_micro(r):
        return {
            "microevent_id":     int(r.get("microevent_id", 0)),
            "hadm_id":           hadm_id,
            "subject_id":        subject_id,
            "micro_specimen_id": r.get("micro_specimen_id"),
            "chartdate":         r.get("chartdate"),
            "charttime":         r.get("charttime"),
            "spec_type_desc":    r.get("spec_type_desc"),
            "test_seq":          r.get("test_seq"),
            "storedate":         r.get("storedate"),
            "storetime":         r.get("storetime"),
            "org_name":          r.get("org_name"),
            "isolate_num":       r.get("isolate_num"),
            "quantity":          r.get("quantity"),
            "ab_name":           r.get("ab_name"),
            "dilution_text":     r.get("dilution_text"),
            "dilution_comparison":r.get("dilution_comparison"),
            "dilution_value":    r.get("dilution_value"),
            "interpretation":    r.get("interpretation"),
            "comments":          r.get("comments"),
        }

    def _norm_rx(r):
        return {
            "hadm_id":        hadm_id,
            "subject_id":     subject_id,
            "pharmacy_id":    r.get("pharmacy_id"),
            "poe_id":         r.get("poe_id"),
            "starttime":      r.get("starttime"),
            "stoptime":       r.get("stoptime"),
            "drug_type":      r.get("drug_type"),
            "drug":           r.get("drug"),
            "formulary_drug_cd": r.get("formulary_drug_cd"),
            "gsn":            r.get("gsn"),
            "ndc":            r.get("ndc"),
            "prod_strength":  r.get("prod_strength"),
            "form_rx":        r.get("form_rx"),
            "dose_val_rx":    r.get("dose_val_rx"),
            "dose_unit_rx":   r.get("dose_unit_rx"),
            "form_val_disp":  r.get("form_val_disp"),
            "form_unit_disp": r.get("form_unit_disp"),
            "doses_per_24_hrs": r.get("doses_per_24_hrs"),
            "route":          r.get("route"),
        }

    def _norm_chart(r):
        stay = r.get("stay_id")
        return {
            "hadm_id":    hadm_id,
            "subject_id": subject_id,
            "stay_id":    int(stay) if stay else None,
            "itemid":     int(r.get("itemid", 0)),
            "label":      r.get("label"),
            "category":   r.get("category"),
            "charttime":  r.get("charttime"),
            "storetime":  r.get("storetime"),
            "value":      str(r.get("value", ""))[:200] if r.get("value") is not None else None,
            "valuenum":   r.get("valuenum"),
            "valueuom":   r.get("valueuom"),
            "warning":    r.get("warning"),
        }

    def _norm_pharm(r):
        return {
            "pharmacy_id":     int(r.get("pharmacy_id", 0)),
            "hadm_id":         hadm_id,
            "subject_id":      subject_id,
            "poe_id":          r.get("poe_id"),
            "starttime":       r.get("starttime"),
            "stoptime":        r.get("stoptime"),
            "medication":      r.get("medication"),
            "proc_type":       r.get("proc_type"),
            "status":          r.get("status"),
            "route":           r.get("route"),
            "frequency":       r.get("frequency"),
            "disp_sched":      r.get("disp_sched"),
            "infusion_type":   r.get("infusion_type"),
            "doses_per_24_hrs":r.get("doses_per_24_hrs"),
            "duration":        r.get("duration"),
            "duration_interval":r.get("duration_interval"),
            "fill_quantity":   r.get("fill_quantity"),
        }

    def _norm_poe(r):
        return {
            "poe_id":               str(r.get("poe_id", "")),
            "hadm_id":              hadm_id,
            "subject_id":           subject_id,
            "poe_seq":              r.get("poe_seq"),
            "ordertime":            r.get("ordertime"),
            "order_type":           r.get("order_type"),
            "order_subtype":        r.get("order_subtype"),
            "transaction_type":     r.get("transaction_type"),
            "discontinue_of_poe_id": None,   # avoid FK cycle on first insert
            "order_status":         r.get("order_status"),
            "order_provider_id":    r.get("order_provider_id"),
        }

    def _norm_inp(r):
        stay = r.get("stay_id")
        return {
            "hadm_id":            hadm_id,
            "subject_id":         subject_id,
            "stay_id":            int(stay) if stay else 0,
            "itemid":             int(r.get("itemid", 0)),
            "label":              r.get("label"),
            "starttime":          r.get("starttime"),
            "endtime":            r.get("endtime"),
            "storetime":          r.get("storetime"),
            "amount":             r.get("amount"),
            "amountuom":          r.get("amountuom"),
            "rate":               r.get("rate"),
            "rateuom":            r.get("rateuom"),
            "orderid":            r.get("orderid"),
            "ordercategoryname":  r.get("ordercategoryname"),
            "statusdescription":  r.get("statusdescription"),
            "patientweight":      r.get("patientweight"),
            "totalamount":        r.get("totalamount"),
            "totalamountuom":     r.get("totalamountuom"),
        }

    def _norm_out(r):
        stay = r.get("stay_id")
        return {
            "hadm_id":    hadm_id,
            "subject_id": subject_id,
            "stay_id":    int(stay) if stay else 0,
            "itemid":     int(r.get("itemid", 0)),
            "label":      r.get("label"),
            "charttime":  r.get("charttime"),
            "storetime":  r.get("storetime"),
            "value":      r.get("value"),
            "valueuom":   r.get("valueuom"),
        }

    def _norm_pe(r):
        stay = r.get("stay_id")
        return {
            "hadm_id":           hadm_id,
            "subject_id":        subject_id,
            "stay_id":           int(stay) if stay else 0,
            "itemid":            int(r.get("itemid", 0)),
            "label":             r.get("label"),
            "starttime":         r.get("starttime"),
            "endtime":           r.get("endtime"),
            "storetime":         r.get("storetime"),
            "value":             r.get("value"),
            "valueuom":          r.get("valueuom"),
            "location":          r.get("location"),
            "locationcategory":  r.get("locationcategory"),
            "ordercategoryname": r.get("ordercategoryname"),
            "statusdescription": r.get("statusdescription"),
        }

    def _norm_emar(r):
        return {
            "emar_id":     str(r.get("emar_id", "")),
            "emar_seq":    r.get("emar_seq"),
            "hadm_id":     hadm_id,
            "subject_id":  subject_id,
            "charttime":   r.get("charttime"),
            "medication":  r.get("medication"),
            "event_txt":   str(r.get("event_txt", ""))[:200] if r.get("event_txt") else None,
            "scheduletime":r.get("scheduletime"),
            "route":       str(r.get("route", ""))[:100] if r.get("route") else None,
        }

    def _norm_emar_d(r):
        return {
            "emar_id":             str(r.get("emar_id", "")),
            "hadm_id":             hadm_id,
            "subject_id":          subject_id,
            "medication":          r.get("medication"),
            "product_description": r.get("product_description"),
            "dose_given":          str(r.get("dose_given", ""))[:60] if r.get("dose_given") is not None else None,
            "dose_given_unit":     str(r.get("dose_given_unit", ""))[:60] if r.get("dose_given_unit") else None,
            "route":               str(r.get("route", ""))[:100] if r.get("route") else None,
            "administration_type": str(r.get("administration_type", ""))[:60] if r.get("administration_type") else None,
            "charttime":           r.get("charttime"),
        }

    def _norm_dte(r):
        stay = r.get("stay_id")
        return {
            "hadm_id":    hadm_id,
            "subject_id": subject_id,
            "stay_id":    int(stay) if stay else 0,
            "itemid":     int(r.get("itemid", 0)),
            "label":      r.get("label"),
            "category":   r.get("category"),
            "charttime":  r.get("charttime"),
            "storetime":  r.get("storetime"),
            "value":      r.get("value"),
            "warning":    r.get("warning"),
        }

    # ── Write all to Cloud SQL ─────────────────────────────────────────────
    print(f"[SQL] Writing {hadm_id} to Cloud SQL ...")

    with engine.begin() as conn:

        counts["ap_admissions"]        = _bulk_insert(conn, "ap_admissions",        merged_adm,                          "hadm_id")
        counts["ap_diagnoses"]         = _bulk_insert(conn, "ap_diagnoses",         [_norm_diag(r) for r in diag_rows])
        counts["ap_procedures"]        = _bulk_insert(conn, "ap_procedures",        [_norm_proc(r) for r in proc_rows])
        counts["ap_drgcodes"]          = _bulk_insert(conn, "ap_drgcodes",          [_norm_drg(r)  for r in drg_rows])
        counts["ap_labevents"]         = _bulk_insert(conn, "ap_labevents",         [_norm_lab(r)  for r in lab_rows],   "labevent_id")
        counts["ap_microbiologyevents"]= _bulk_insert(conn, "ap_microbiologyevents",[_norm_micro(r)for r in micro_rows], "microevent_id")
        counts["ap_prescriptions"]     = _bulk_insert(conn, "ap_prescriptions",     [_norm_rx(r)   for r in rx_rows])
        counts["ap_icustays"]          = _bulk_insert(conn, "ap_icustays",          [_norm_icu(r)  for r in icu_rows],   "stay_id")
        counts["ap_chartevents"]       = _bulk_insert(conn, "ap_chartevents",       [_norm_chart(r)for r in chart_rows])
        counts["ap_transfers"]         = _bulk_insert(conn, "ap_transfers",         [_norm_xfr(r)  for r in xfr_rows],  "transfer_id")
        counts["ap_services"]          = _bulk_insert(conn, "ap_services",          [_norm_svc(r)  for r in svc_rows])
        counts["ap_pharmacy"]          = _bulk_insert(conn, "ap_pharmacy",          [_norm_pharm(r) for r in pharm_rows], "pharmacy_id")
        counts["ap_poe"]               = _bulk_insert(conn, "ap_poe",               [_norm_poe(r)   for r in poe_rows],   "poe_id")
        counts["ap_emar"]              = _bulk_insert(conn, "ap_emar",             [_norm_emar(r) for r in emar_rows],  "emar_id")
        # emar_detail uses BIGSERIAL PK — delete stale rows then re-insert
        if emar_d_rows:
            conn.execute(text("DELETE FROM ap_emar_detail WHERE hadm_id = :h"), {"h": hadm_id})
            counts["ap_emar_detail"]   = _bulk_insert(conn, "ap_emar_detail",      [_norm_emar_d(r) for r in emar_d_rows])

        if has_icu:
            counts["ap_inputevents"]     = _bulk_insert(conn, "ap_inputevents",     [_norm_inp(r) for r in inp_rows])
            counts["ap_procedureevents"] = _bulk_insert(conn, "ap_procedureevents", [_norm_pe(r)  for r in pe_rows])
            counts["ap_datetimeevents"]  = _bulk_insert(conn, "ap_datetimeevents",  [_norm_dte(r) for r in dte_rows])
            # ap_outputevents dropped — skip

        # ── Update active_patients master row ──────────────────────────────
        primary_dx   = diag_rows[0].get("long_title") if diag_rows else None
        primary_code = diag_rows[0].get("icd_code")   if diag_rows else None
        top_drg      = next((d for d in drg_rows if d.get("drg_type") == "APR"), drg_rows[0] if drg_rows else None)

        adm_time = adm_row.get("admittime")
        dis_time = adm_row.get("dischtime")
        try:
            import pandas as pd
            los = round((pd.Timestamp(dis_time) - pd.Timestamp(adm_time)).total_seconds() / 86400, 2) if adm_time and dis_time else None
        except Exception:
            los = None

        conn.execute(text("""
            UPDATE active_patients SET
                subject_id                = :subject_id,
                gender                    = :gender,
                anchor_age                = :anchor_age,
                race                      = :race,
                marital_status            = :marital_status,
                language                  = :language,
                insurance                 = :insurance,
                admission_type            = :admission_type,
                admission_location        = :admission_location,
                discharge_location        = :discharge_location,
                admit_time                = :admit_time,
                discharge_time            = :discharge_time,
                los_days                  = :los_days,
                hospital_expire_flag      = :hospital_expire_flag,
                primary_diagnosis_code    = :primary_diagnosis_code,
                primary_diagnosis_title   = :primary_diagnosis_title,
                principal_drg_code        = :principal_drg_code,
                principal_drg_description = :principal_drg_description,
                drg_severity              = :drg_severity,
                drg_mortality             = :drg_mortality,
                data_fetch_status         = :fetch_status,
                fetch_round2_done         = :round2_done,
                fetch_icu_done            = :fetch_icu_done,
                data_fetched_at           = NOW(),
                status                    = 'data_ready',
                updated_at                = NOW()
            WHERE hadm_id = :hadm_id
        """), {
            "hadm_id":                 hadm_id,
            "subject_id":              subject_id,
            "gender":                  pat_row.get("gender"),
            "anchor_age":              pat_row.get("anchor_age"),
            "race":                    adm_row.get("race"),
            "marital_status":          adm_row.get("marital_status"),
            "language":                adm_row.get("language"),
            "insurance":               adm_row.get("insurance"),
            "admission_type":          adm_row.get("admission_type"),
            "admission_location":      adm_row.get("admission_location"),
            "discharge_location":      adm_row.get("discharge_location"),
            "admit_time":              adm_time,
            "discharge_time":          dis_time,
            "los_days":                los,
            "hospital_expire_flag":    adm_row.get("hospital_expire_flag"),
            "primary_diagnosis_code":  primary_code,
            "primary_diagnosis_title": primary_dx,
            "principal_drg_code":      str(top_drg.get("drg_code","")) if top_drg else None,
            "principal_drg_description": top_drg.get("description") if top_drg else None,
            "drg_severity":            top_drg.get("drg_severity")  if top_drg else None,
            "drg_mortality":           top_drg.get("drg_mortality") if top_drg else None,
            "fetch_icu_done":          has_icu,
            "fetch_status":            "partial" if display_only else "fetched",
            "round2_done":             not display_only,
        })

    elapsed = round(time.time() - t0, 1)
    total   = sum(v for v in counts.values() if isinstance(v, int))
    print(f"[DONE] hadm_id={hadm_id}  {total} rows  {elapsed}s")
    counts["_elapsed_s"]  = elapsed
    counts["_total_rows"] = total
    return counts
