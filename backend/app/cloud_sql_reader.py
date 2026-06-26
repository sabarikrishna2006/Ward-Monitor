"""
Cloud SQL Patient Reader
========================
Reads clinical data from ap_* tables for patients already in the
active directory (data_fetch_status = 'fetched').
Returns dicts in the same format as bq_mimic_loader.py.
"""
import json as _json
import logging
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple

from sqlalchemy import text

from .cloud_sql_db import get_engine

log = logging.getLogger(__name__)


def _to_dict(row) -> Optional[Dict]:
    if row is None:
        return None
    d = dict(row._mapping)
    for k, v in d.items():
        if isinstance(v, (datetime, date)):
            d[k] = v.isoformat()
    return d


def _fetch(conn, sql: str, params: dict = None) -> List[Dict]:
    rows = conn.execute(text(sql), params or {}).fetchall()
    result = []
    for r in rows:
        d = dict(zip(r._mapping.keys(), r))
        for k, v in d.items():
            if isinstance(v, (datetime, date)):
                d[k] = v.isoformat()
        result.append(d)
    return result


# ── Status checks ─────────────────────────────────────────────────────────────

def get_fetch_status(hadm_id: int) -> Optional[str]:
    """Return data_fetch_status or None if patient not in active_patients."""
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT data_fetch_status FROM active_patients WHERE hadm_id = :h"),
            {"h": hadm_id}
        ).fetchone()
    return row[0] if row else None


def is_fetched(hadm_id: int) -> bool:
    return get_fetch_status(hadm_id) == "fetched"


# ── Display data (fast-path tables) ──────────────────────────────────────────

def _parse_json(v):
    """pg8000 may return JSON columns as Python objects or as strings — handle both."""
    if v is None:
        return []
    if isinstance(v, (list, dict)):
        return v
    try:
        return _json.loads(v)
    except Exception:
        return []


# Single-query display read — 1 network round-trip instead of 8 serial queries
_DISPLAY_SQL = text("""
SELECT
    (SELECT data_fetch_status FROM active_patients  WHERE hadm_id = :h LIMIT 1) AS status,
    (SELECT row_to_json(a)    FROM ap_admissions    a WHERE a.hadm_id = :h LIMIT 1) AS admission,
    COALESCE((SELECT json_agg(d ORDER BY d.seq_num)            FROM ap_diagnoses           d WHERE d.hadm_id = :h), '[]'::json) AS diagnoses,
    COALESCE((SELECT json_agg(p ORDER BY p.seq_num)            FROM ap_procedures          p WHERE p.hadm_id = :h), '[]'::json) AS procedures,
    COALESCE((SELECT json_agg(i ORDER BY i.intime)             FROM ap_icustays            i WHERE i.hadm_id = :h), '[]'::json) AS icustays,
    COALESCE((SELECT json_agg(t ORDER BY t.intime)             FROM ap_transfers           t WHERE t.hadm_id = :h), '[]'::json) AS transfers,
    COALESCE((SELECT json_agg(m ORDER BY m.charttime DESC)     FROM ap_microbiologyevents  m WHERE m.hadm_id = :h), '[]'::json) AS micro,
    COALESCE((SELECT json_agg(o ORDER BY o.chartdate  DESC)    FROM (SELECT * FROM ap_omr WHERE hadm_id = :h ORDER BY chartdate DESC LIMIT 100) o), '[]'::json) AS omr
""")


def read_display_data(hadm_id: int) -> Dict:
    """
    Read all display tables in a single round-trip via JSON aggregation.
    Replaces 8 serial queries with 1 — critical for reducing Cloud SQL latency.
    """
    with get_engine().connect() as conn:
        row = conn.execute(_DISPLAY_SQL, {"h": hadm_id}).fetchone()

    if row is None:
        return {"error": f"hadm_id {hadm_id} not in active directory"}

    status = row[0]
    adm_raw = row[1]

    if status is None or adm_raw is None:
        return {"error": f"hadm_id {hadm_id} not in active directory"}

    adm = adm_raw if isinstance(adm_raw, dict) else _json.loads(adm_raw)

    diagnoses  = _parse_json(row[2])
    procedures = _parse_json(row[3])
    icustays   = _parse_json(row[4])
    transfers  = _parse_json(row[5])
    micro      = _parse_json(row[6])
    omr        = _parse_json(row[7])

    return {
        "admission":          adm,
        "patient":            adm,
        "admissions":         [adm],
        "diagnoses":          diagnoses,
        "diagnoses_icd":      diagnoses,
        "procedures":         procedures,
        "procedures_icd":     procedures,
        "icustays":           icustays,
        "transfers":          transfers,
        "microbiologyevents": micro,
        "omr":                omr,
        "labevents":    [],
        "prescriptions":[],
        "pharmacy":     [],
        "poe":          [],
        "chartevents":  [],
        "inputevents":  [],
        "outputevents": [],
        "procedureevents":  [],
    }


def read_display_status_and_data(hadm_id: int) -> Tuple[Optional[str], Dict]:
    """
    Returns (status, data_dict) in one round-trip.
    status is None if patient not in active_patients.
    Used by get_patient_display to skip _ensure_in_active_directory for cached patients.
    """
    with get_engine().connect() as conn:
        row = conn.execute(_DISPLAY_SQL, {"h": hadm_id}).fetchone()

    if row is None or row[0] is None:
        return None, {}

    status = row[0]
    adm_raw = row[1]

    if adm_raw is None:
        return status, {"error": f"hadm_id {hadm_id} not in active directory"}

    adm = adm_raw if isinstance(adm_raw, dict) else _json.loads(adm_raw)

    diagnoses  = _parse_json(row[2])
    procedures = _parse_json(row[3])
    icustays   = _parse_json(row[4])
    transfers  = _parse_json(row[5])
    micro      = _parse_json(row[6])
    omr        = _parse_json(row[7])

    data = {
        "admission":          adm,
        "patient":            adm,
        "admissions":         [adm],
        "diagnoses":          diagnoses,
        "diagnoses_icd":      diagnoses,
        "procedures":         procedures,
        "procedures_icd":     procedures,
        "icustays":           icustays,
        "transfers":          transfers,
        "microbiologyevents": micro,
        "omr":                omr,
        "labevents":    [],
        "prescriptions":[],
        "pharmacy":     [],
        "poe":          [],
        "chartevents":  [],
        "inputevents":  [],
        "outputevents": [],
        "procedureevents":  [],
    }
    return status, data


# ── Lazy tab reads ────────────────────────────────────────────────────────────

_TAB_SQL: Dict[str, str] = {
    "prescriptions":  "SELECT * FROM ap_prescriptions WHERE hadm_id = :h ORDER BY starttime",
    "labevents":      "SELECT * FROM ap_labevents WHERE hadm_id = :h ORDER BY charttime DESC",
    "pharmacy":       "SELECT * FROM ap_pharmacy WHERE hadm_id = :h ORDER BY starttime",
    "poe":            "SELECT * FROM ap_poe WHERE hadm_id = :h ORDER BY ordertime DESC",
    "chartevents":    "SELECT * FROM ap_chartevents WHERE hadm_id = :h ORDER BY charttime DESC LIMIT 5000",
    "fluids":         "SELECT * FROM ap_inputevents WHERE hadm_id = :h ORDER BY starttime",
    "datetimeevents": "SELECT * FROM ap_datetimeevents WHERE hadm_id = :h ORDER BY charttime",
    "emar":            "SELECT * FROM ap_emar WHERE hadm_id = :h ORDER BY charttime DESC",
    "emar_detail":     "SELECT * FROM ap_emar_detail WHERE hadm_id = :h ORDER BY charttime DESC",
    "procedureevents": "SELECT * FROM ap_procedureevents WHERE hadm_id = :h ORDER BY starttime DESC",
    "outputevents":    "SELECT * FROM ap_outputevents   WHERE hadm_id = :h ORDER BY charttime DESC LIMIT 200",
}


def read_tab(hadm_id: int, tab_name: str) -> Optional[Dict]:
    """
    Read one large tab from Cloud SQL.
    Returns None if the tab is not stored in Cloud SQL (unknown tab name).
    """
    sql = _TAB_SQL.get(tab_name)
    if sql is None:
        return None  # caller should fall back to BigQuery
    with get_engine().connect() as conn:
        rows = _fetch(conn, sql, {"h": hadm_id})
    return {tab_name: rows}


# ── Full data for generate-summary ────────────────────────────────────────────

def read_full_data(hadm_id: int) -> Dict:
    """Read all cached tables. Falls back gracefully if tabs are missing."""
    data = read_display_data(hadm_id)
    if "error" in data:
        return data
    for tab in ["labevents", "prescriptions", "pharmacy", "poe",
                "chartevents", "fluids", "datetimeevents"]:
        tab_data = read_tab(hadm_id, tab)
        if tab_data:
            data.update(tab_data)
    return data


# ── Active patient list (for browse / stats) ──────────────────────────────────

def list_active_patients(page: int = 1, per_page: int = 20,
                         status_filter: Optional[str] = None) -> Dict:
    """Return patients in Cloud SQL active directory with basic metadata."""
    offset = (page - 1) * per_page
    sql = """
        SELECT ap.hadm_id, ap.subject_id, ap.gender, ap.anchor_age, ap.race,
               ap.admission_type, ap.admit_time, ap.discharge_time, ap.los_days,
               ap.primary_diagnosis_title, ap.primary_diagnosis_code,
               ap.data_fetch_status, ap.status, ap.created_at
        FROM active_patients ap
        WHERE ap.data_fetch_status = 'fetched'
    """
    params: Dict = {"limit": per_page, "offset": offset}
    if status_filter:
        sql += " AND ap.status = :status_filter"
        params["status_filter"] = status_filter
    sql += " ORDER BY ap.created_at DESC LIMIT :limit OFFSET :offset"

    with get_engine().connect() as conn:
        rows = _fetch(conn, sql, params)
        count_row = conn.execute(
            text("SELECT COUNT(*) FROM active_patients WHERE data_fetch_status = 'fetched'")
        ).fetchone()
    total = count_row[0] if count_row else 0

    return {"admissions": rows, "page": page, "per_page": per_page, "total": total}
