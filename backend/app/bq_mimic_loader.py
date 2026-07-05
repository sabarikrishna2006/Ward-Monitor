"""
BigQuery MIMIC-IV Loader
========================
Queries MIMIC-IV tables from BigQuery.
Returns dicts consumed by bigquery_mimic_loader and cloud_sql_reader.

Environment variables:
    BQ_PROJECT        GCP project that owns the MIMIC-IV BQ datasets
                      Default: extracted from CLOUD_SQL_INSTANCE prefix
    BQ_HOSP_DATASET   BigQuery dataset for hosp tables  (default: mimiciv_3_1_hosp)
    BQ_ICU_DATASET    BigQuery dataset for ICU tables   (default: mimiciv_3_1_icu)
    GOOGLE_APPLICATION_CREDENTIALS
                      Service-account JSON path (same creds as GCS/Cloud SQL)
"""
import logging
import os
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
_CLOUD_SQL_INSTANCE = os.getenv(
    "CLOUD_SQL_INSTANCE",
    "healthcare-project-496207:asia-south1:healthcare-project-496207-instance"
)
_DEFAULT_BQ_PROJECT = _CLOUD_SQL_INSTANCE.split(":")[0]

BQ_PROJECT      = os.getenv("BQ_PROJECT",      _DEFAULT_BQ_PROJECT)  # billing project
BQ_DATA_PROJECT = os.getenv("BQ_DATA_PROJECT", "physionet-data")      # where MIMIC data lives
BQ_HOSP_DATASET = os.getenv("BQ_HOSP_DATASET", "mimiciv_3_1_hosp")
BQ_ICU_DATASET  = os.getenv("BQ_ICU_DATASET",  "mimiciv_3_1_icu")
BQ_NOTE_DATASET = os.getenv("BQ_NOTE_DATASET", "mimiciv_3_1_note")    # discharge notes for ROUGE

_bq_client = None


def _get_bq_client():
    global _bq_client
    if _bq_client is None:
        from google.cloud import bigquery
        # MIMIC-IV data is in physionet-data (PhysioNet hosts it).
        # Jobs are billed to BQ_PROJECT (mimic-bq-ashmit, owned by IIIT account).
        # Load IIIT OAuth ADC directly — don't use GOOGLE_APPLICATION_CREDENTIALS
        # (that's the sir's service account which has no PhysioNet data access).
        import json, pathlib
        _adc_candidates = [
            pathlib.Path(os.environ.get("APPDATA", "")) / "gcloud" / "application_default_credentials.json",
            pathlib.Path.home() / ".config" / "gcloud" / "application_default_credentials.json",
        ]
        adc_path = next((p for p in _adc_candidates if p.exists()), None)
        if adc_path:
            data = json.loads(adc_path.read_text())
            if data.get("type") == "authorized_user":
                from google.oauth2.credentials import Credentials
                creds = Credentials(
                    token=None,
                    refresh_token=data["refresh_token"],
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=data["client_id"],
                    client_secret=data["client_secret"],
                )
                _bq_client = bigquery.Client(project=BQ_PROJECT, credentials=creds)
                log.info(f"BigQuery client via IIIT OAuth (project={BQ_PROJECT})")
                return _bq_client
        _bq_client = bigquery.Client(project=BQ_PROJECT)
        log.info(f"BigQuery client via ADC fallback (project={BQ_PROJECT})")
    return _bq_client


def _hosp(table: str) -> str:
    return f"`{BQ_DATA_PROJECT}.{BQ_HOSP_DATASET}.{table}`"


def _icu(table: str) -> str:
    return f"`{BQ_DATA_PROJECT}.{BQ_ICU_DATASET}.{table}`"


def _note(table: str) -> str:
    return f"`{BQ_DATA_PROJECT}.{BQ_NOTE_DATASET}.{table}`"


def _cardio_service_filter(hadm_alias: str = "a") -> str:
    """Filter to true cardiology admissions via services table (CARD/CCARD).
    More precise than the ICD filter for identifying cardiology-managed patients."""
    return f"""
    EXISTS (
        SELECT 1 FROM {_hosp('services')} svc
        WHERE svc.hadm_id = {hadm_alias}.hadm_id
          AND svc.curr_service IN ('CARD', 'CCARD')
    )"""


def _query(sql: str, params: Optional[Dict] = None) -> List[Dict]:
    """Execute a BigQuery query with named parameters (@name style) and return list[dict]."""
    from google.cloud.bigquery import QueryJobConfig, ScalarQueryParameter

    client = _get_bq_client()
    job_config = None

    if params:
        bq_params = []
        for k, v in params.items():
            if isinstance(v, bool):
                bq_params.append(ScalarQueryParameter(k, "BOOL", v))
            elif isinstance(v, int):
                bq_params.append(ScalarQueryParameter(k, "INT64", v))
            elif isinstance(v, float):
                bq_params.append(ScalarQueryParameter(k, "FLOAT64", v))
            else:
                bq_params.append(ScalarQueryParameter(k, "STRING", str(v)))
        job_config = QueryJobConfig(query_parameters=bq_params)

    job = client.query(sql, job_config=job_config)
    result = []
    for row in job.result():
        d = dict(row.items())
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        result.append(d)
    return result


# ── Cardiology cohort ICD filter ──────────────────────────────────────────────
# ICD-10: I00-I99 (diseases of the circulatory system)
# ICD-9 : 390-459 (diseases of the circulatory system)
def _cardio_filter(alias: str = "a") -> str:
    return f"""
    EXISTS (
        SELECT 1 FROM {_hosp('diagnoses_icd')} dx
        WHERE dx.hadm_id = {alias}.hadm_id AND (
            (dx.icd_version = 10 AND LEFT(dx.icd_code, 1) = 'I')
            OR (dx.icd_version = 9
                AND SAFE_CAST(REGEXP_EXTRACT(dx.icd_code, r'^[0-9]+') AS INT64)
                    BETWEEN 390 AND 459)
        )
    )"""


# ── Browse / search admissions ────────────────────────────────────────────────
def browse_admissions(page: int = 1, per_page: int = 20, search: str = "") -> Dict:
    """Paginated cardiology admissions from BigQuery with primary diagnosis joined."""
    offset = (page - 1) * per_page
    params: Dict = {"per_page": per_page, "offset": offset}

    search_clause = ""
    if search:
        search_clause = """
            AND (
                CAST(a.hadm_id AS STRING) LIKE CONCAT('%', @search, '%')
                OR LOWER(a.race)             LIKE CONCAT('%', LOWER(@search), '%')
                OR LOWER(a.admission_type)   LIKE CONCAT('%', LOWER(@search), '%')
                OR LOWER(a.admission_location) LIKE CONCAT('%', LOWER(@search), '%')
            )"""
        params["search"] = search

    cardio = _cardio_filter("a")

    count_sql = f"""
        SELECT COUNT(*) AS cnt
        FROM {_hosp('admissions')} a
        WHERE {cardio} {search_clause}
    """
    count_rows = _query(count_sql, params if search else None)
    total = count_rows[0]["cnt"] if count_rows else 0

    data_sql = f"""
        SELECT
            a.hadm_id, a.subject_id, a.admittime, a.dischtime,
            a.admission_type, a.admission_location, a.discharge_location,
            a.insurance, a.language, a.marital_status, a.race,
            a.hospital_expire_flag,
            p.gender, p.anchor_age, p.anchor_year, p.anchor_year_group,
            COALESCE(dx1.icd_code, '')      AS primary_icd_code,
            COALESCE(dx1.long_title, '')    AS primary_diagnosis
        FROM {_hosp('admissions')} a
        JOIN {_hosp('patients')} p ON a.subject_id = p.subject_id
        LEFT JOIN (
            SELECT di.hadm_id, di.icd_code,
                   COALESCE(dd.long_title, di.icd_code) AS long_title
            FROM {_hosp('diagnoses_icd')} di
            LEFT JOIN {_hosp('d_icd_diagnoses')} dd
                   ON di.icd_code = dd.icd_code AND di.icd_version = dd.icd_version
            WHERE di.seq_num = 1
        ) dx1 ON a.hadm_id = dx1.hadm_id
        WHERE {cardio} {search_clause}
        ORDER BY a.admittime DESC
        LIMIT @per_page OFFSET @offset
    """
    rows = _query(data_sql, params)

    return {"admissions": rows, "page": page, "per_page": per_page, "total": total}


def list_all_hadm_ids() -> List[int]:
    """Return all cardiology hadm_ids. Used sparingly — can be a large result."""
    rows = _query(f"""
        SELECT DISTINCT a.hadm_id
        FROM {_hosp('admissions')} a
        WHERE {_cardio_filter()}
        ORDER BY a.hadm_id
    """)
    return [r["hadm_id"] for r in rows]


def get_top_dcm_patients(limit: int = 100) -> List[Dict]:
    """
    Return the top `limit` Dilated Cardiomyopathy ICU patients ranked by
    data richness — total event rows across labs, chartevents, prescriptions,
    emar, microbiology, procedures, and diagnoses.

    Filter: ICD-10 I420 or ICD-9 4254, AND must have at least one ICU stay.
    """
    log.info(f"[BQ] Scoring DCM cohort for top {limit} data-rich patients …")
    rows = _query(f"""
        WITH dcm AS (
            SELECT DISTINCT a.hadm_id, a.subject_id
            FROM {_hosp('admissions')} a
            JOIN {_hosp('diagnoses_icd')} d ON a.hadm_id = d.hadm_id
            WHERE d.icd_code IN ('I420', '4254')
              AND a.hadm_id IN (SELECT hadm_id FROM {_icu('icustays')})
        ),
        richness AS (
            SELECT
                p.hadm_id,
                p.subject_id,
                COALESCE(lab.cnt,   0) +
                COALESCE(chart.cnt, 0) +
                COALESCE(rx.cnt,    0) +
                COALESCE(em.cnt,    0) +
                COALESCE(micro.cnt, 0) +
                COALESCE(proc.cnt,  0) +
                COALESCE(diag.cnt,  0) AS total_rows
            FROM dcm p
            LEFT JOIN (
                SELECT hadm_id, COUNT(*) AS cnt
                FROM {_hosp('labevents')} GROUP BY hadm_id
            ) lab ON p.hadm_id = lab.hadm_id
            LEFT JOIN (
                SELECT hadm_id, COUNT(*) AS cnt
                FROM {_icu('chartevents')} GROUP BY hadm_id
            ) chart ON p.hadm_id = chart.hadm_id
            LEFT JOIN (
                SELECT hadm_id, COUNT(*) AS cnt
                FROM {_hosp('prescriptions')} GROUP BY hadm_id
            ) rx ON p.hadm_id = rx.hadm_id
            LEFT JOIN (
                SELECT hadm_id, COUNT(*) AS cnt
                FROM {_hosp('emar')} GROUP BY hadm_id
            ) em ON p.hadm_id = em.hadm_id
            LEFT JOIN (
                SELECT hadm_id, COUNT(*) AS cnt
                FROM {_hosp('microbiologyevents')} GROUP BY hadm_id
            ) micro ON p.hadm_id = micro.hadm_id
            LEFT JOIN (
                SELECT hadm_id, COUNT(*) AS cnt
                FROM {_hosp('procedures_icd')} GROUP BY hadm_id
            ) proc ON p.hadm_id = proc.hadm_id
            LEFT JOIN (
                SELECT hadm_id, COUNT(*) AS cnt
                FROM {_hosp('diagnoses_icd')} GROUP BY hadm_id
            ) diag ON p.hadm_id = diag.hadm_id
        )
        SELECT hadm_id, subject_id, total_rows
        FROM richness
        ORDER BY total_rows DESC
        LIMIT @limit
    """, {"limit": limit})
    log.info(f"[BQ] DCM scoring done — {len(rows)} patients returned")
    return rows


# ── Per-patient display data ──────────────────────────────────────────────────
def fetch_patient_display(hadm_id: int) -> Dict:
    """
    Fast-path data: admissions + patients + diagnoses + procedures + drg +
    icustays + transfers + services + microbiology + omr.
    Large event tables (labs, meds, chartevents) returned empty; use fetch_patient_tab().
    """
    log.info(f"[BQ] display hadm_id={hadm_id}")

    adm_rows = _query(f"""
        SELECT a.*, p.gender, p.anchor_age, p.anchor_year, p.anchor_year_group, p.dod
        FROM {_hosp('admissions')} a
        JOIN {_hosp('patients')} p ON a.subject_id = p.subject_id
        WHERE a.hadm_id = @hadm_id
    """, {"hadm_id": hadm_id})

    if not adm_rows:
        return {"error": f"hadm_id {hadm_id} not found in BigQuery"}

    adm        = adm_rows[0]
    subject_id = adm.get("subject_id")

    # These 6 queries are mutually independent (all keyed off hadm_id/subject_id
    # resolved above) — dispatching them concurrently instead of one-at-a-time
    # turns ~7 sequential BQ round trips (2-7s each => 15-45s) into the time of
    # the single slowest query. bigquery.Client supports concurrent query() calls
    # from multiple threads (each dispatches its own job); only the blocking
    # .result() iteration inside _query() happens per-thread.
    _jobs = {
        "diagnoses": (f"""
            SELECT di.hadm_id, di.subject_id, di.seq_num, di.icd_code, di.icd_version,
                   COALESCE(dd.long_title, di.icd_code) AS long_title
            FROM {_hosp('diagnoses_icd')} di
            LEFT JOIN {_hosp('d_icd_diagnoses')} dd
                   ON di.icd_code = dd.icd_code AND di.icd_version = dd.icd_version
            WHERE di.hadm_id = @hadm_id ORDER BY di.seq_num
        """, {"hadm_id": hadm_id}),
        "procedures": (f"""
            SELECT pi.hadm_id, pi.subject_id, pi.seq_num, pi.chartdate,
                   pi.icd_code, pi.icd_version,
                   COALESCE(dp.long_title, pi.icd_code) AS long_title
            FROM {_hosp('procedures_icd')} pi
            LEFT JOIN {_hosp('d_icd_procedures')} dp
                   ON pi.icd_code = dp.icd_code AND pi.icd_version = dp.icd_version
            WHERE pi.hadm_id = @hadm_id ORDER BY pi.seq_num
        """, {"hadm_id": hadm_id}),
        "icustays": (
            f"SELECT * FROM {_icu('icustays')} WHERE hadm_id = @hadm_id ORDER BY intime",
            {"hadm_id": hadm_id}
        ),
        "transfers": (
            f"SELECT * FROM {_hosp('transfers')} WHERE hadm_id = @hadm_id ORDER BY intime",
            {"hadm_id": hadm_id}
        ),
        "microbiologyevents": (
            f"SELECT * FROM {_hosp('microbiologyevents')} WHERE hadm_id = @hadm_id ORDER BY charttime DESC",
            {"hadm_id": hadm_id}
        ),
        "omr": (f"""
            SELECT * FROM {_hosp('omr')}
            WHERE subject_id = @subject_id ORDER BY chartdate DESC LIMIT 100
        """, {"subject_id": subject_id}),
    }
    from concurrent.futures import ThreadPoolExecutor
    _results: Dict[str, List[Dict]] = {}
    with ThreadPoolExecutor(max_workers=len(_jobs)) as _pool:
        _futs = {_pool.submit(_query, sql, params): name for name, (sql, params) in _jobs.items()}
        for _fut in _futs:
            name = _futs[_fut]
            try:
                _results[name] = _fut.result()
            except Exception as _e:
                log.warning(f"[BQ] display query '{name}' failed for hadm_id={hadm_id}: {_e}")
                _results[name] = []

    diagnoses          = _results["diagnoses"]
    procedures         = _results["procedures"]
    icustays           = _results["icustays"]
    transfers          = _results["transfers"]
    microbiologyevents = _results["microbiologyevents"]
    omr                = _results["omr"]

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
        "microbiologyevents": microbiologyevents,
        "omr":                omr,
        # Large tables empty — caller must use fetch_patient_tab()
        "labevents":          [],
        "prescriptions":      [],
        "pharmacy":           [],
        "poe":                [],
        "chartevents":        [],
        "inputevents":        [],
        "outputevents":       [],
        "procedureevents":    [],
    }


# ── Lazy tab ──────────────────────────────────────────────────────────────────
def fetch_patient_tab(hadm_id: int, tab_name: str) -> Dict:
    """Load one large table on demand."""
    log.info(f"[BQ] tab={tab_name} hadm_id={hadm_id}")

    if tab_name == "prescriptions":
        rows = _query(
            f"SELECT * FROM {_hosp('prescriptions')} WHERE hadm_id = @hadm_id ORDER BY starttime DESC LIMIT 20",
            {"hadm_id": hadm_id}
        )
    elif tab_name == "labevents":
        rows = _query(f"""
            SELECT le.*, dl.label, dl.fluid, dl.category
            FROM {_hosp('labevents')} le
            LEFT JOIN {_hosp('d_labitems')} dl ON le.itemid = dl.itemid
            WHERE le.hadm_id = @hadm_id ORDER BY le.charttime DESC LIMIT 25
        """, {"hadm_id": hadm_id})
    elif tab_name == "pharmacy":
        rows = _query(
            f"SELECT * FROM {_hosp('pharmacy')} WHERE hadm_id = @hadm_id ORDER BY starttime DESC LIMIT 20",
            {"hadm_id": hadm_id}
        )
    elif tab_name == "poe":
        rows = _query(
            f"SELECT * FROM {_hosp('poe')} WHERE hadm_id = @hadm_id ORDER BY ordertime DESC LIMIT 20",
            {"hadm_id": hadm_id}
        )
    elif tab_name == "chartevents":
        # 50 rows needed for general display, 100 vitals needed for sabari's EWS sync
        vital_ids = (220045, 220179, 220050, 220180, 220051, 220277, 220210, 223762, 223761, 224639, 226512, 226755, 223834)
        rows = _query(f"""
            WITH top_general AS (
                SELECT ce.stay_id, ce.hadm_id, ce.subject_id, ce.itemid,
                       di.label, di.category,
                       ce.charttime, ce.storetime, ce.value, ce.valuenum,
                       ce.valueuom, ce.warning
                FROM {_icu('chartevents')} ce
                LEFT JOIN {_icu('d_items')} di ON ce.itemid = di.itemid
                WHERE ce.hadm_id = @hadm_id
                ORDER BY ce.charttime DESC LIMIT 50
            ),
            top_vitals AS (
                SELECT ce.stay_id, ce.hadm_id, ce.subject_id, ce.itemid,
                       di.label, di.category,
                       ce.charttime, ce.storetime, ce.value, ce.valuenum,
                       ce.valueuom, ce.warning
                FROM {_icu('chartevents')} ce
                LEFT JOIN {_icu('d_items')} di ON ce.itemid = di.itemid
                WHERE ce.hadm_id = @hadm_id AND ce.itemid IN {vital_ids}
                ORDER BY ce.charttime DESC LIMIT 100
            )
            SELECT * FROM top_general
            UNION DISTINCT
            SELECT * FROM top_vitals
            ORDER BY charttime DESC
        """, {"hadm_id": hadm_id})
    elif tab_name == "fluids":
        rows = _query(f"""
            SELECT ie.*, di.label, di.category
            FROM {_icu('inputevents')} ie
            LEFT JOIN {_icu('d_items')} di ON ie.itemid = di.itemid
            WHERE ie.hadm_id = @hadm_id ORDER BY ie.starttime DESC LIMIT 20
        """, {"hadm_id": hadm_id})
    elif tab_name == "procedureevents":
        rows = _query(f"""
            SELECT pe.*, di.label, di.category
            FROM {_icu('procedureevents')} pe
            LEFT JOIN {_icu('d_items')} di ON pe.itemid = di.itemid
            WHERE pe.hadm_id = @hadm_id ORDER BY pe.starttime DESC LIMIT 20
        """, {"hadm_id": hadm_id})
    else:
        return {"error": f"Unknown tab: {tab_name}"}

    return {tab_name: rows}


# ── Full data for generate-summary ───────────────────────────────────────────
def fetch_patient_full(hadm_id: int) -> Dict:
    """All tables. Used by generate_summary. Slow first call; Cloud SQL caches after."""
    data = fetch_patient_display(hadm_id)
    if "error" in data:
        return data
    for tab in ["labevents", "prescriptions", "pharmacy", "poe",
                "chartevents", "fluids"]:
        tab_data = fetch_patient_tab(hadm_id, tab)
        data.update(tab_data)
    # Attempt to fetch discharge note from mimiciv_note module (best-effort)
    # This is the primary Pass 1 document; if unavailable, other tables fill context.
    discharge_note = fetch_discharge_note(hadm_id)
    if discharge_note:
        data["discharge_note_text"] = discharge_note
        log.info(f"[BQ] discharge note fetched ({len(discharge_note)} chars)")
    else:
        data["discharge_note_text"] = None
        log.info("[BQ] discharge note unavailable (mimiciv_note not accessible)")
    return data


# ── ICD / lab label lookups  (used by data_server enrichment endpoints) ───────
# In-memory cache for static BQ reference tables — loaded once, reused forever.
_icd_diag_cache:  Dict[tuple, str] = {}   # (icd_code, icd_version) → long_title
_icd_proc_cache:  Dict[tuple, str] = {}
_lab_label_cache: Dict[int, Dict]  = {}   # itemid → {label, fluid, category}
_icd_cache_loaded: Dict[str, bool] = {}   # tracks which tables are fully loaded


def _ensure_icd_cache(table_type: str) -> Dict[tuple, str]:
    """Load the full d_icd_* table into memory on first call (30s once, then instant)."""
    cache = _icd_diag_cache if table_type == "diagnoses" else _icd_proc_cache
    if _icd_cache_loaded.get(table_type):
        return cache
    bq_table = _hosp("d_icd_diagnoses") if table_type == "diagnoses" else _hosp("d_icd_procedures")
    log.info(f"[icd-cache] loading full {bq_table} into memory…")
    rows = _query(f"SELECT icd_code, icd_version, long_title FROM {bq_table}")
    for r in rows:
        cache[(r["icd_code"], int(r["icd_version"]))] = r["long_title"]
    _icd_cache_loaded[table_type] = True
    log.info(f"[icd-cache] {table_type}: {len(cache):,} codes cached")
    return cache


def _ensure_lab_cache() -> Dict[int, Dict]:
    if _icd_cache_loaded.get("labs"):
        return _lab_label_cache
    log.info("[icd-cache] loading full d_labitems into memory…")
    rows = _query(f"SELECT itemid, label, fluid, category FROM {_hosp('d_labitems')}")
    for r in rows:
        _lab_label_cache[r["itemid"]] = r
    _icd_cache_loaded["labs"] = True
    log.info(f"[icd-cache] lab items: {len(_lab_label_cache):,} items cached")
    return _lab_label_cache


def lookup_icd_titles(rows: List[Dict], table_type: str) -> List[Dict]:
    """Fill in long_title for ICD rows missing descriptions. Uses in-memory cache after first BQ load."""
    needs = [r for r in rows if not r.get("long_title") and r.get("icd_code")]
    if not needs:
        return rows
    lookup = _ensure_icd_cache(table_type)
    for r in rows:
        if not r.get("long_title") and r.get("icd_code"):
            key = (r["icd_code"], int(r.get("icd_version", 10)))
            if key in lookup:
                r["long_title"] = lookup[key]
    return rows


def lookup_lab_labels(rows: List[Dict]) -> List[Dict]:
    """Fill in label/fluid/category for labevents rows missing a label. Uses in-memory cache after first BQ load."""
    needs = [r for r in rows if not r.get("label") and r.get("itemid")]
    if not needs:
        return rows
    lookup = _ensure_lab_cache()
    for r in rows:
        if not r.get("label") and r.get("itemid"):
            info = lookup.get(int(r["itemid"]))
            if info:
                r["label"]    = info.get("label")
                r["fluid"]    = info.get("fluid")
                r["category"] = info.get("category")
    return rows


def fetch_discharge_note(hadm_id: int) -> Optional[str]:
    """Fetch the MIMIC discharge summary note text for ROUGE evaluation.
    Returns the note text, or None if note module not available."""
    try:
        rows = _query(f"""
            SELECT text, charttime, note_type
            FROM {_note('discharge')}
            WHERE hadm_id = @hadm_id
            ORDER BY charttime DESC
            LIMIT 1
        """, {"hadm_id": hadm_id})
        if rows and rows[0].get("text"):
            return rows[0]["text"]
    except Exception as e:
        log.warning(f"fetch_discharge_note({hadm_id}): note module may not be accessible — {e}")
    return None


def fetch_cardiology_notes(limit: int = 50) -> List[Dict]:
    """Fetch cardiology discharge notes (CARD/CCARD service) for Pass 1 batch processing.
    Requires mimiciv_note access. Returns list of {hadm_id, subject_id, charttime, text}."""
    try:
        rows = _query(f"""
            SELECT n.subject_id, n.hadm_id, n.charttime, n.text
            FROM {_note('discharge')} n
            JOIN {_hosp('services')} s ON n.hadm_id = s.hadm_id
            WHERE s.curr_service IN ('CARD', 'CCARD')
            ORDER BY n.charttime DESC
            LIMIT @limit
        """, {"limit": limit})
        return rows
    except Exception as e:
        log.warning(f"fetch_cardiology_notes: note module not accessible — {e}")
        return []


def check_note_access() -> dict:
    """Verify mimiciv_note module access. Call once at startup or from admin panel."""
    try:
        rows = _query(f"SELECT COUNT(*) AS cnt FROM {_note('discharge')} LIMIT 1")
        count = rows[0]["cnt"] if rows else 0
        return {"accessible": True, "discharge_note_count": count}
    except Exception as e:
        return {"accessible": False, "error": str(e),
                "hint": "Request mimiciv_note access at physionet.org or use BigQuery physionet-data.mimiciv_note"}
