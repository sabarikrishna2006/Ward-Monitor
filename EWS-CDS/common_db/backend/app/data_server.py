"""
Data Server — Port 8002
=======================
Cache-aside patient data layer:
  1. Check Cloud SQL active directory  (data_fetch_status = 'fetched')
     → HIT:  read from ap_* tables  (milliseconds)
     → MISS: fetch from BigQuery → write to Cloud SQL → return

Browse (admissions list) hits BigQuery directly — paginated, indexed.
ICD/lab enrichment lookups hit BigQuery directly — lookup tables, fast.
"""

import asyncio
import logging
import os

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Any, Dict, List

from . import bq_mimic_loader as bql
from . import cloud_sql_reader as csr
from . import cloud_sql_app_db as gdb
from .cloud_sql_db import get_engine
from .bigquery_mimic_loader import fetch_and_store_patient

# Tracks hadm_ids with a background full ETL in flight (avoid duplicate jobs)
_etl_running: set = set()

# Per-patient locks — prevent concurrent display-only ETL for the same patient
_etl_locks: dict = {}  # hadm_id → asyncio.Lock

# In-memory tab cache — after first BQ fetch, serve instantly on re-open (same server session)
# Key: (hadm_id, tab_name), Value: response dict from bql.fetch_patient_tab
_tab_memory_cache: dict = {}  # (hadm_id, tab_name) → data
# In-flight deduplication: concurrent requests for the same tab share one BigQuery fetch
_tab_in_flight: dict = {}     # (hadm_id, tab_name) → asyncio.Future

# In-memory display cache — diagnoses/procedures/etc served instantly on re-open
_display_memory_cache: dict = {}  # hadm_id → display data dict

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Discharge Summary — Data Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _warm_cloud_sql():
    """Pre-establish Cloud SQL connection during startup so first user request is fast."""
    try:
        def _ping():
            from sqlalchemy import text as _t
            engine = get_engine()
            with engine.connect() as conn:
                conn.execute(_t("SELECT 1"))
        await run_in_threadpool(_ping)
        log.info("[startup] Cloud SQL connection pool warmed")
    except Exception as e:
        log.warning(f"[startup] Cloud SQL warm failed (non-fatal): {e}")


@app.on_event("startup")
async def _warm_icd_lab_caches():
    """Pre-load ICD and lab label reference tables into memory at startup.
    These are static BQ tables (~35s to load). Done in background so startup is not delayed."""
    async def _load():
        try:
            await asyncio.gather(
                run_in_threadpool(bql.lookup_icd_titles, [{"icd_code": "J189", "icd_version": 10}], "diagnoses"),
                run_in_threadpool(bql.lookup_icd_titles, [{"icd_code": "0BH17EZ", "icd_version": 10}], "procedures"),
                run_in_threadpool(bql.lookup_lab_labels, [{"itemid": 50912}]),
            )
            log.info("[startup] ICD/lab reference caches loaded")
        except Exception as e:
            log.warning(f"[startup] ICD/lab cache warm failed (non-fatal): {e}")
    asyncio.create_task(_load())


@app.on_event("startup")
async def _ensure_missing_tables():
    """Create ap_pharmacy, ap_poe, ap_datetimeevents, ap_omr, ap_procedureevents if they were
    missing from the initial schema apply (cloud_sql_schema.sql was partially run)."""
    _DDL = [
        """CREATE TABLE IF NOT EXISTS ap_pharmacy (
            pharmacy_id       BIGINT      PRIMARY KEY,
            hadm_id           INTEGER     NOT NULL REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
            subject_id        INTEGER     NOT NULL,
            poe_id            VARCHAR(30),
            starttime         TIMESTAMPTZ,
            stoptime          TIMESTAMPTZ,
            medication        VARCHAR(200),
            proc_type         VARCHAR(30),
            status            VARCHAR(20),
            route             VARCHAR(50),
            frequency         VARCHAR(30),
            disp_sched        TEXT,
            infusion_type     VARCHAR(20),
            doses_per_24_hrs  NUMERIC(6,2),
            duration          NUMERIC(10,4),
            duration_interval VARCHAR(20),
            fill_quantity     VARCHAR(30),
            source_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_pharm_hadm_id ON ap_pharmacy (hadm_id)",
        "CREATE INDEX IF NOT EXISTS idx_pharm_start   ON ap_pharmacy (hadm_id, starttime)",
        """CREATE TABLE IF NOT EXISTS ap_poe (
            poe_id                VARCHAR(30)  PRIMARY KEY,
            hadm_id               INTEGER      NOT NULL REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
            subject_id            INTEGER      NOT NULL,
            poe_seq               INTEGER,
            ordertime             TIMESTAMPTZ,
            order_type            VARCHAR(30),
            order_subtype         VARCHAR(50),
            transaction_type      VARCHAR(20),
            discontinue_of_poe_id VARCHAR(30)  REFERENCES ap_poe (poe_id) ON DELETE SET NULL,
            order_status          VARCHAR(20),
            order_provider_id     VARCHAR(20),
            source_fetched_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_poe_hadm_id   ON ap_poe (hadm_id)",
        "CREATE INDEX IF NOT EXISTS idx_poe_ordertime ON ap_poe (hadm_id, ordertime DESC)",
        "CREATE INDEX IF NOT EXISTS idx_poe_type      ON ap_poe (order_type)",
        """CREATE TABLE IF NOT EXISTS ap_omr (
            id                BIGSERIAL    PRIMARY KEY,
            hadm_id           INTEGER      NOT NULL REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
            subject_id        INTEGER      NOT NULL,
            chartdate         DATE,
            seq_num           SMALLINT,
            result_name       VARCHAR(50),
            result_value      VARCHAR(100),
            source_fetched_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_omr UNIQUE (hadm_id, chartdate, seq_num, result_name)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_omr_hadm_id   ON ap_omr (hadm_id)",
        "CREATE INDEX IF NOT EXISTS idx_omr_chartdate ON ap_omr (hadm_id, chartdate DESC)",
        """CREATE TABLE IF NOT EXISTS ap_procedureevents (
            id                  BIGSERIAL    PRIMARY KEY,
            hadm_id             INTEGER      NOT NULL REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
            subject_id          INTEGER      NOT NULL,
            stay_id             INTEGER      NOT NULL REFERENCES ap_icustays (stay_id) ON DELETE CASCADE,
            itemid              INTEGER      NOT NULL,
            label               VARCHAR(100),
            starttime           TIMESTAMPTZ,
            endtime             TIMESTAMPTZ,
            storetime           TIMESTAMPTZ,
            value               NUMERIC(14,4),
            valueuom            VARCHAR(30),
            location            VARCHAR(30),
            locationcategory    VARCHAR(30),
            ordercategoryname   VARCHAR(50),
            statusdescription   VARCHAR(30),
            source_fetched_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_pe_hadm_id ON ap_procedureevents (hadm_id)",
        "CREATE INDEX IF NOT EXISTS idx_pe_stay_id ON ap_procedureevents (stay_id)",
        "CREATE INDEX IF NOT EXISTS idx_pe_item    ON ap_procedureevents (itemid)",
        """CREATE TABLE IF NOT EXISTS ap_datetimeevents (
            id                BIGSERIAL    PRIMARY KEY,
            hadm_id           INTEGER      NOT NULL REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
            subject_id        INTEGER      NOT NULL,
            stay_id           INTEGER      NOT NULL REFERENCES ap_icustays (stay_id) ON DELETE CASCADE,
            itemid            INTEGER      NOT NULL,
            label             VARCHAR(100),
            category          VARCHAR(50),
            charttime         TIMESTAMPTZ  NOT NULL,
            storetime         TIMESTAMPTZ,
            value             TIMESTAMPTZ,
            warning           SMALLINT     CHECK (warning IN (0, 1)),
            source_fetched_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_dte_hadm_id ON ap_datetimeevents (hadm_id)",
        "CREATE INDEX IF NOT EXISTS idx_dte_stay_id ON ap_datetimeevents (stay_id)",
        "CREATE INDEX IF NOT EXISTS idx_dte_time    ON ap_datetimeevents (hadm_id, charttime)",
    ]
    async def _do_ddl():
        try:
            from sqlalchemy import text as _text
            engine = get_engine()
            def _sync():
                with engine.begin() as conn:
                    for stmt in _DDL:
                        conn.execute(_text(stmt))
            await run_in_threadpool(_sync)
            log.info("[startup] Missing ap_* tables ensured (pharmacy, poe, omr, procedureevents, datetimeevents)")
        except Exception as e:
            log.warning(f"[startup] ap_* table migration skipped (non-fatal): {e}")
    asyncio.create_task(_do_ddl())


@app.on_event("startup")
async def _backfill_existing_patients():
    """For patients already in Cloud SQL with data_fetch_status='fetched', check if the
    newly-created ap_pharmacy/poe/datetimeevents tables are empty for them and re-run ETL
    in the background so those tabs get cached without waiting for a user request."""
    async def _do():
        try:
            from sqlalchemy import text as _text
            engine = get_engine()
            def _get_stale():
                with engine.connect() as conn:
                    rows = conn.execute(_text("""
                        SELECT DISTINCT ap.hadm_id FROM active_patients ap
                        WHERE ap.data_fetch_status = 'fetched'
                        AND NOT EXISTS (
                            SELECT 1 FROM ap_pharmacy p WHERE p.hadm_id = ap.hadm_id
                        )
                        LIMIT 20
                    """)).fetchall()
                return [r[0] for r in rows]
            stale = await run_in_threadpool(_get_stale)
            if not stale:
                log.info("[startup] backfill: all fetched patients already have pharmacy data")
                return
            log.info(f"[startup] backfill: scheduling re-ETL for {len(stale)} patients missing pharmacy/poe/datetimeevents: {stale}")
            for hadm_id in stale:
                if hadm_id not in _etl_running:
                    _etl_running.add(hadm_id)
                    asyncio.create_task(_background_full_etl(hadm_id, engine))
        except Exception as e:
            log.warning(f"[startup] backfill check skipped (non-fatal): {e}")
    asyncio.create_task(_do())


@app.exception_handler(Exception)
async def _err(request, exc):
    log.error(f"{request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
        headers={"Access-Control-Allow-Origin": "*"},
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _background_full_etl(hadm_id: int, engine) -> None:
    """Run full ETL for a partial patient in background — caches all lazy tabs."""
    log.info(f"[bg-etl] starting full ETL for hadm_id={hadm_id}")
    try:
        await run_in_threadpool(fetch_and_store_patient, hadm_id, engine)
        log.info(f"[bg-etl] done for hadm_id={hadm_id}")
    except Exception as e:
        log.warning(f"[bg-etl] failed for hadm_id={hadm_id}: {e}")
    finally:
        _etl_running.discard(hadm_id)


def _downgrade_status_to_partial(hadm_id: int) -> None:
    """Downgrade a 'fetched' patient to 'partial' so background ETL will re-write lazy tabs."""
    from sqlalchemy import text
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE active_patients SET data_fetch_status='partial' WHERE hadm_id=:h AND data_fetch_status='fetched'"),
            {"h": hadm_id}
        )
    log.info(f"[bg-etl] downgraded hadm_id={hadm_id} fetched→partial to trigger lazy tab write")


async def _ensure_in_active_directory(hadm_id: int) -> str:
    """
    Guarantee display data for hadm_id is in Cloud SQL.
    Returns the current data_fetch_status after ensuring the patient is active.
    - 'fetched'/'partial'/'fetching': data ready → returns immediately.
    - pending/failed/None: runs display_only ETL (~5 s) then returns.
    """
    status = await run_in_threadpool(csr.get_fetch_status, hadm_id)

    if status in ("fetched", "partial", "fetching"):
        return status

    # pending / failed / None → run display_only ETL now
    # Lock prevents concurrent ETL for same hadm_id across 9 parallel tab requests
    if hadm_id not in _etl_locks:
        _etl_locks[hadm_id] = asyncio.Lock()
    async with _etl_locks[hadm_id]:
        status = await run_in_threadpool(csr.get_fetch_status, hadm_id)
        if status in ("fetched", "partial", "fetching"):
            return status
        engine = await run_in_threadpool(get_engine)
        result = await run_in_threadpool(fetch_and_store_patient, hadm_id, engine, True)
        if "error" in result and not result.get("skipped"):
            raise HTTPException(status_code=404, detail=result["error"])
        return "partial"


# ── Patient browse ────────────────────────────────────────────────────────────

@app.get("/api/mimic/admissions")
async def get_admissions(page: int = 1, per_page: int = 20, search: str = ""):
    return await run_in_threadpool(
        bql.browse_admissions, page=page, per_page=per_page, search=search.strip()
    )


@app.get("/api/hadm_ids")
async def get_hadm_ids():
    """Returns hadm_ids currently in Cloud SQL active directory."""
    from sqlalchemy import text
    engine = await run_in_threadpool(get_engine)
    def _fetch():
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT hadm_id FROM active_patients WHERE data_fetch_status = 'fetched' ORDER BY hadm_id")
            ).fetchall()
        return [r[0] for r in rows]
    ids = await run_in_threadpool(_fetch)
    return {"count": len(ids), "hadm_ids": ids}


# ── Patient display data ──────────────────────────────────────────────────────

@app.get("/api/patient/{hadm_id}/display")
async def get_patient_display(hadm_id: int):
    """
    Fast display data: demographics, diagnoses, procedures, DRG, services,
    transfers, ICU stays, microbiology.
    Cached in server memory after first fetch — sub-millisecond on re-open.
    First fetch: 1 SQL round-trip via JSON aggregation (was 9 serial queries).
    """
    # Tier 1: in-memory cache — instant, sub-millisecond
    if hadm_id in _display_memory_cache:
        log.debug(f"[display-cache] HIT {hadm_id}")
        return _display_memory_cache[hadm_id]

    # Tier 2: combined status+data in ONE Cloud SQL round-trip
    status, data = await run_in_threadpool(csr.read_display_status_and_data, hadm_id)

    if status in ("fetched", "partial", "fetching"):
        # Patient already active — check if display tables are actually populated.
        # Patients loaded by older code (or failed mid-ETL) may have status="fetched"/"partial"
        # but empty ap_diagnoses / ap_admissions. Re-run ETL for them instead of serving stale data.
        if "error" not in data and data.get("diagnoses"):
            _display_memory_cache[hadm_id] = data
            return data
        # Data missing or stale — re-run ETL directly (bypass _ensure_in_active_directory
        # which would skip for "fetched"/"partial" status)
        _display_memory_cache.pop(hadm_id, None)
        log.info(f"[display] hadm_id={hadm_id} status={status} — stale/missing display data, re-running BQ ETL")
        engine = await run_in_threadpool(get_engine)
        result = await run_in_threadpool(fetch_and_store_patient, hadm_id, engine, True)
        if "error" in result and not result.get("skipped"):
            raise HTTPException(status_code=404, detail=result["error"])
        data = await run_in_threadpool(csr.read_display_data, hadm_id)
        if "error" in data:
            raise HTTPException(status_code=404, detail=data["error"])
        _display_memory_cache[hadm_id] = data
        return data

    # Tier 3: patient not yet in active directory → run display ETL (BQ fetch, ~5 s)
    await _ensure_in_active_directory(hadm_id)
    data = await run_in_threadpool(csr.read_display_data, hadm_id)
    if "error" in data:
        raise HTTPException(status_code=404, detail=data["error"])
    _display_memory_cache[hadm_id] = data
    return data


# ── Lazy tab ─────────────────────────────────────────────────────────────────

@app.get("/api/patient/{hadm_id}/tab/{tab_name}")
async def get_patient_tab(hadm_id: int, tab_name: str):
    """
    Load one large clinical tab on demand — always live from BigQuery.
    Uploaded rows (from Cloud SQL ap_* tables) are merged in and tagged _uploaded=True.

    tab_name: prescriptions | labevents | pharmacy | poe | fluids |
              chartevents | procedureevents | outputevents
    """
    allowed = {"prescriptions", "pharmacy", "poe", "fluids",
               "labevents", "chartevents",
               "procedureevents", "outputevents"}
    if tab_name not in allowed:
        raise HTTPException(status_code=400, detail=f"Unknown tab: {tab_name}")

    _cache_key = (hadm_id, tab_name)

    # 1. In-memory cache hit — return immediately
    if _cache_key in _tab_memory_cache:
        log.debug(f"[tab-cache] HIT {hadm_id}/{tab_name}")
        return _tab_memory_cache[_cache_key]

    # 2. In-flight deduplication — if another coroutine is already fetching this tab
    #    (e.g. UI and generate_summary racing), wait for that one instead of a 2nd BQ query.
    if _cache_key in _tab_in_flight:
        log.debug(f"[tab-inflight] waiting for in-flight fetch {hadm_id}/{tab_name}")
        return await _tab_in_flight[_cache_key]

    loop = asyncio.get_event_loop()
    fut: asyncio.Future = loop.create_future()
    _tab_in_flight[_cache_key] = fut

    try:
        # Best-effort: ensure patient is in Cloud SQL active directory.
        # If Cloud SQL is down, still serve from BigQuery (non-fatal).
        fetch_status = "unknown"
        try:
            fetch_status = await _ensure_in_active_directory(hadm_id)
        except Exception as e:
            log.warning(f"[tab] _ensure_in_active_directory failed (non-fatal, will still fetch BQ): {e}")

        # 3. Try Cloud SQL first — avoids a BigQuery round-trip for cached patients.
        # If data_fetch_status='fetched', Cloud SQL is authoritative even for empty tabs
        # (empty list = patient genuinely has no rows, not "not yet fetched").
        sql_data = None
        try:
            sql_data = await run_in_threadpool(csr.read_tab, hadm_id, tab_name)
            if sql_data is not None and fetch_status == "fetched":
                rows = sql_data.get(tab_name, [])
                log.debug(f"[tab-sql] HIT {hadm_id}/{tab_name} ({len(rows)} rows, status=fetched)")
                _tab_memory_cache[_cache_key] = sql_data
                fut.set_result(sql_data)
                return sql_data
            if sql_data and sql_data.get(tab_name):
                log.debug(f"[tab-sql] HIT {hadm_id}/{tab_name} ({len(sql_data[tab_name])} rows)")
                _tab_memory_cache[_cache_key] = sql_data
                fut.set_result(sql_data)
                return sql_data
        except Exception as e:
            log.warning(f"[tab] Cloud SQL read failed, falling back to BigQuery: {e}")
            sql_data = None

        # 4. Fetch live from BigQuery (fallback or first-time load)
        try:
            data = await run_in_threadpool(bql.fetch_patient_tab, hadm_id, tab_name)
        except Exception as exc:
            # BigQuery unavailable — serve Cloud SQL result (may be empty) rather than 500
            if sql_data is not None:
                log.warning(f"[tab] BigQuery failed for {hadm_id}/{tab_name}, serving Cloud SQL data: {exc}")
                _tab_memory_cache[_cache_key] = sql_data
                fut.set_result(sql_data)
                return sql_data
            # Optional ICU tabs: return empty rather than 500 — missing ICU data is expected
            # for non-ICU patients and should not block the UI or summary pipeline.
            _optional_empty = {"procedureevents", "datetimeevents", "outputevents"}
            if tab_name in _optional_empty:
                log.warning(f"[tab] BigQuery failed for {hadm_id}/{tab_name} (no Cloud SQL cache), returning empty: {exc}")
                empty = {tab_name: []}
                fut.set_result(empty)
                return empty
            exc2 = HTTPException(status_code=500, detail=str(exc))
            fut.set_exception(exc2)
            raise exc2
        if "error" in data:
            # Optional ICU tabs return empty rather than propagating BQ errors
            _optional_empty2 = {"procedureevents", "datetimeevents", "outputevents"}
            if tab_name in _optional_empty2:
                log.warning(f"[tab] BQ error for optional tab {hadm_id}/{tab_name}, returning empty: {data['error']}")
                empty = {tab_name: []}
                fut.set_result(empty)
                return empty
            exc2 = HTTPException(status_code=500, detail=data["error"])
            fut.set_exception(exc2)
            raise exc2

        # 5. Merge uploaded rows from Cloud SQL (tagged _uploaded=True so UI can badge them)
        _TAB_UPLOAD_KEY = {
            "labevents": "labs", "chartevents": "vitals", "prescriptions": "meds",
            "pharmacy": "pharmacy", "poe": "poe", "procedureevents": "icu",
        }
        upload_key = _TAB_UPLOAD_KEY.get(tab_name)
        if upload_key:
            try:
                uploaded = await run_in_threadpool(gdb.fetch_all_uploaded_clinical_data, hadm_id)
                uploaded_rows = uploaded.get(upload_key, [])
                if uploaded_rows:
                    bq_key = next(iter(data), None)
                    if bq_key:
                        data[bq_key] = data[bq_key] + uploaded_rows
            except Exception as exc:
                log.warning(f"[tab] failed to merge uploaded rows for {tab_name}: {exc}")

        _tab_memory_cache[_cache_key] = data
        fut.set_result(data)
        return data

    except Exception as exc:
        if not fut.done():
            fut.set_exception(exc)
        raise
    finally:
        _tab_in_flight.pop(_cache_key, None)


# ── Full patient data for Generate Summary ────────────────────────────────────

@app.get("/api/patient/{hadm_id}/full")
async def get_patient_full(hadm_id: int):
    """
    Complete patient data including labevents and chartevents.
    Called by the UI server's generate_summary endpoint.
    Served from Cloud SQL after first open.
    """
    await _ensure_in_active_directory(hadm_id)
    data = await run_in_threadpool(csr.read_full_data, hadm_id)
    if "error" in data:
        raise HTTPException(status_code=404, detail=data["error"])
    return data


# ── ICD title lookup ─────────────────────────────────────────────────────────

class IcdLookupRequest(BaseModel):
    rows: List[Dict[str, Any]]
    table_type: str  # "procedures" or "diagnoses"


@app.post("/api/icd/lookup")
async def icd_lookup(req: IcdLookupRequest):
    if req.table_type not in ("procedures", "diagnoses"):
        raise HTTPException(status_code=400, detail="table_type must be 'procedures' or 'diagnoses'")
    enriched = await run_in_threadpool(bql.lookup_icd_titles, req.rows, req.table_type)
    return {"rows": enriched}


# ── Lab item label lookup ─────────────────────────────────────────────────────

class LabLookupRequest(BaseModel):
    rows: List[Dict[str, Any]]


@app.post("/api/labitems/lookup")
async def labitems_lookup(req: LabLookupRequest):
    enriched = await run_in_threadpool(bql.lookup_lab_labels, req.rows)
    return {"rows": enriched}


# ── Active directory stats ────────────────────────────────────────────────────

@app.get("/api/cache/stats")
async def get_cache_stats():
    from sqlalchemy import text
    engine = await run_in_threadpool(get_engine)
    def _stats():
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE data_fetch_status = 'fetched')  AS fetched,
                    COUNT(*) FILTER (WHERE data_fetch_status = 'partial')  AS partial,
                    COUNT(*) FILTER (WHERE data_fetch_status = 'fetching') AS fetching,
                    COUNT(*) FILTER (WHERE data_fetch_status = 'pending')  AS pending,
                    COUNT(*) FILTER (WHERE data_fetch_status = 'failed')   AS failed,
                    COUNT(*) AS total
                FROM active_patients
            """)).fetchone()
        return dict(row._mapping) if row else {}
    stats = await run_in_threadpool(_stats)
    return {"active_directory": stats, "source": "cloud_sql"}


@app.get("/api/cache/patients")
async def get_cached_patients():
    """Patients in Cloud SQL active directory."""
    result = await run_in_threadpool(csr.list_active_patients, 1, 200)
    active = [
        {
            "hadm_id":       r["hadm_id"],
            "last_accessed": r.get("created_at"),
        }
        for r in result.get("admissions", [])
    ]
    return {"active": active}


@app.delete("/api/patient/{hadm_id}/cache")
async def invalidate_patient_cache(hadm_id: int, tab: str = None):
    """
    Clear in-memory cache for a patient — called by main server after upload or delete.
    If `tab` is provided, only clears that specific tab; otherwise clears all tabs + display.
    """
    _display_memory_cache.pop(hadm_id, None)
    if tab:
        _tab_memory_cache.pop((hadm_id, tab), None)
    else:
        keys = [k for k in list(_tab_memory_cache) if k[0] == hadm_id]
        for k in keys:
            _tab_memory_cache.pop(k, None)
    log.info(f"[cache-clear] hadm_id={hadm_id} tab={tab or 'all'}")
    return {"cleared": True, "hadm_id": hadm_id, "tab": tab}


_DCM_TOP10 = [25434637, 20553493, 28113079, 24339216, 28855911,
              29950776, 26972341, 26935676, 24823642, 23149252]

@app.post("/api/seed/cardiology")
async def seed_cardiology_cohort():
    """
    Pre-load top 10 data-rich DCM cardiology ICU patients into active directory.
    Runs display_only ETL (~5s each) so patients appear instantly in My Patients tab.
    """
    engine = await run_in_threadpool(get_engine)
    results = []
    for hadm_id in _DCM_TOP10:
        try:
            status = await run_in_threadpool(csr.get_fetch_status, hadm_id)
            if status in ("fetched", "partial", "fetching"):
                results.append({"hadm_id": hadm_id, "status": "already_loaded"})
                continue
            await run_in_threadpool(fetch_and_store_patient, hadm_id, engine, True)
            results.append({"hadm_id": hadm_id, "status": "seeded"})
        except Exception as e:
            results.append({"hadm_id": hadm_id, "status": "error", "detail": str(e)})
    return {"seeded": results}


@app.get("/api/cache/loading")
async def get_loading_patients():
    """Patients currently being fetched from BigQuery."""
    from sqlalchemy import text
    engine = await run_in_threadpool(get_engine)
    def _fetch():
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT hadm_id FROM active_patients WHERE data_fetch_status = 'fetching'")
            ).fetchall()
        return [r[0] for r in rows]
    loading = await run_in_threadpool(_fetch)
    return {"loading": loading}


@app.get("/api/mimic/note_access")
async def check_note_access():
    """Check if mimiciv_note module (discharge notes) is accessible in BigQuery.
    Required for Pass 1 note extraction and ROUGE evaluation (Week 2)."""
    result = await run_in_threadpool(bql.check_note_access)
    return result


@app.get("/api/mimic/cardiology_notes")
async def get_cardiology_notes(limit: int = 50):
    """Fetch cardiology discharge notes from mimiciv_note (CARD/CCARD service).
    Used for Pass 1 batch processing and few-shot calibration."""
    rows = await run_in_threadpool(bql.fetch_cardiology_notes, limit)
    return {"count": len(rows), "notes": rows}
