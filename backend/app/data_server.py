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

def _synth_tab(hadm_id: int, tab_name: str) -> list:
    """Deterministic synthetic fallback rows for demo patients with no BQ/SQL data."""
    import random as _r
    _r.seed(hadm_id + hash(tab_name))
    now_str = "2180-07-23"
    def _t(h): return f"{now_str} {h:02d}:{_r.randint(0,59):02d}:00"
    if tab_name == "labevents":
        labs = [
            ("BNP",50001,"Cardiology","pg/mL",100,900,120,None),
            ("Troponin T",51003,"Cardiology","ng/mL",0,0.1,0.04,None),
            ("Sodium",50983,"Chemistry","mEq/L",136,145,_r.randint(136,144),None),
            ("Potassium",50971,"Chemistry","mEq/L",3.5,5.0,round(_r.uniform(3.8,4.8),1),None),
            ("Creatinine",50912,"Chemistry","mg/dL",0.6,1.2,round(_r.uniform(0.8,1.3),2),None),
            ("Haemoglobin",51222,"Haematology","g/dL",12,16,round(_r.uniform(11,15),1),None),
            ("WBC",51301,"Haematology","K/uL",4,11,round(_r.uniform(5,10),1),None),
            ("Glucose",50931,"Chemistry","mg/dL",70,110,_r.randint(82,108),None),
            ("Albumin",50862,"Chemistry","g/dL",3.5,5,round(_r.uniform(3.4,4.5),1),None),
            ("INR",51237,"Haematology","",0.8,1.2,round(_r.uniform(0.9,1.3),2),None),
        ]
        return [{"labevent_id": hadm_id*100+i, "hadm_id": hadm_id, "itemid": it,
                 "label": lb, "fluid": cat, "category": cat, "charttime": _t(8+i),
                 "value": str(val), "valuenum": val, "valueuom": uom,
                 "ref_range_lower": lo, "ref_range_upper": hi,
                 "flag": ("critical" if val>hi*1.5 else ("abnormal" if val>hi else None))}
                for i,(lb,it,cat,uom,lo,hi,val,_) in enumerate(labs)]
    if tab_name == "chartevents":
        rows = []
        for i in range(8):
            ct = _t(8+i)
            hr  = _r.randint(62,88)
            rr  = _r.randint(14,18)
            spo2 = _r.randint(95,99)
            sbp = _r.randint(108,130); dbp = sbp-_r.randint(30,45)
            temp = round(_r.uniform(36.5,37.2),1)
            rows += [
                {"hadm_id":hadm_id,"charttime":ct,"itemid":220045,"label":"Heart Rate","value":str(hr),"valuenum":hr,"valueuom":"bpm"},
                {"hadm_id":hadm_id,"charttime":ct,"itemid":220210,"label":"Respiratory Rate","value":str(rr),"valuenum":rr,"valueuom":"/min"},
                {"hadm_id":hadm_id,"charttime":ct,"itemid":220277,"label":"SpO2","value":str(spo2),"valuenum":spo2,"valueuom":"%"},
                {"hadm_id":hadm_id,"charttime":ct,"itemid":220050,"label":"Arterial BP [Systolic]","value":str(sbp),"valuenum":sbp,"valueuom":"mmHg"},
                {"hadm_id":hadm_id,"charttime":ct,"itemid":220051,"label":"Arterial BP [Diastolic]","value":str(dbp),"valuenum":dbp,"valueuom":"mmHg"},
                {"hadm_id":hadm_id,"charttime":ct,"itemid":223761,"label":"Temperature Fahrenheit","value":str(temp*9/5+32),"valuenum":temp*9/5+32,"valueuom":"°F"},
            ]
        return rows
    if tab_name == "prescriptions":
        meds = [("Furosemide","40 mg","Oral","Daily"),("Carvedilol","12.5 mg","Oral","BD"),
                ("Enalapril","5 mg","Oral","OD"),("Aspirin","75 mg","Oral","OD"),
                ("Atorvastatin","40 mg","Oral","Night"),("Clopidogrel","75 mg","Oral","OD"),
                ("Metoprolol","25 mg","Oral","BD"),("Digoxin","0.125 mg","Oral","OD")]
        return [{"hadm_id":hadm_id,"drug":d,"dose_val_rx":dos.split()[0],"dose_unit_rx":dos.split()[1],
                 "route":rt,"frequency":freq,"starttime":_t(6),"stoptime":_t(18)}
                for d,dos,rt,freq in meds[:6+_r.randint(0,2)]]
    if tab_name == "pharmacy":
        meds = [("Furosemide 40mg","40 mg","daily"),("Carvedilol 12.5mg","12.5 mg","BD"),
                ("Enalapril 5mg","5 mg","OD"),("Aspirin 75mg","75 mg","OD"),
                ("Atorvastatin 40mg","40 mg","nocte"),("Clopidogrel 75mg","75 mg","OD")]
        return [{"hadm_id":hadm_id,"pharmacy_id":hadm_id*10+i,"medication":m,"doses_given":str(d),
                 "frequency":f,"starttime":_t(6),"stoptime":_t(22),"status":"Active"}
                for i,(m,d,f) in enumerate(meds[:4+_r.randint(0,2)])]
    if tab_name == "poe":
        orders = [("Medication","Furosemide 40mg OD PO"),("Medication","Carvedilol 12.5mg BD PO"),
                  ("Lab","BNP STAT"),("Lab","Complete Blood Count"),
                  ("Nursing","Strict I/O monitoring"),("Radiology","CXR AP View"),
                  ("Diet","Sodium restricted 2g/day"),("Monitoring","Daily weights")]
        return [{"hadm_id":hadm_id,"poe_id":f"POE-{hadm_id}-{i}","order_type":ot,
                 "order_subtype":os_,"ordertime":_t(8+i),"order_status":"Active"}
                for i,(ot,os_) in enumerate(orders[:5+_r.randint(0,3)])]
    if tab_name == "fluids":
        items = [("NS 0.9% 100ml",100),("D5W 250ml",250),("KCl 20mEq in NS",100)]
        return [{"hadm_id":hadm_id,"itemid":220949+i%3,"label":lb,
                 "starttime":_t(8+i*4),"endtime":_t(10+i*4),
                 "amount":amt,"amountuom":"mL","rate":round(amt/2,1),"rateuom":"mL/hr"}
                for i,(lb,amt) in enumerate(items*(1+_r.randint(0,1)))]
    if tab_name == "procedureevents":
        procs = [("Peripheral IV insertion","IV access"),("12-Lead ECG","Monitoring"),
                 ("Echocardiogram","Imaging")]
        return [{"hadm_id":hadm_id,"itemid":224267+i,"label":lb,"starttime":_t(9+i*3),
                 "endtime":_t(9+i*3+1),"value":1,"valueuom":"dose",
                 "ordercategoryname":cat,"statusdescription":"FinishedRunning"}
                for i,(lb,cat) in enumerate(procs[:1+_r.randint(0,2)])]
    return []


def _synth_display(hadm_id: int) -> dict:
    """Read demo patient demographics from active_patients and build synthetic display payload."""
    from .cloud_sql_db import get_engine as _ge
    from sqlalchemy import text as _text
    import random as _r; _r.seed(hadm_id)
    engine = _ge()
    row = None
    try:
        with engine.connect() as conn:
            row = conn.execute(_text(
                "SELECT patient_name, gender, anchor_age, admitting_diagnosis, "
                "primary_diagnosis_title, diagnosis_short, admit_time, patient_code, "
                "ward, room, bed, admission_type, race, insurance "
                "FROM active_patients WHERE hadm_id=:h"
            ), {"h": hadm_id}).fetchone()
    except Exception:
        pass

    name       = (row[0] if row else None) or "Demo Patient"
    gender     = (row[1] if row else None) or "M"
    age        = (row[2] if row else None) or 55
    adm_dx     = (row[3] if row else None) or "Cardiac admission"
    dx_title   = (row[4] if row else None) or adm_dx
    admit_time = str(row[6]) if row and row[6] else "2180-07-23 08:00:00"
    pt_code    = (row[7] if row else None) or f"PT-00-{hadm_id}"
    adm_type   = (row[11] if row else None) or "EMERGENCY"
    race       = (row[12] if row else None) or "UNKNOWN"
    insurance  = (row[13] if row else None) or "Other"

    adm = {
        "hadm_id": hadm_id, "subject_id": hadm_id,
        "patient_name": name, "full_name": name,
        "gender": gender, "anchor_age": age,
        "admission_type": adm_type, "race": race, "insurance": insurance,
        "admission_location": "EMERGENCY ROOM ADMIT",
        "discharge_location": "HOME",
        "admittime": admit_time, "admit_time": admit_time,
        "dischtime": admit_time,
        "admitting_diagnosis": adm_dx,
        "primary_diagnosis_title": dx_title,
        "patient_code": pt_code,
        "hospital_expire_flag": 0,
    }
    # Deterministic ICD codes from diagnosis title keywords
    dx_map = {
        "dcm": [("I42.0","Dilated cardiomyopathy"),("I47.2","Ventricular tachycardia"),("I50.1","Left ventricular failure")],
        "heart failure": [("I50.9","Heart failure, unspecified"),("I10","Essential hypertension"),("E11.9","Type 2 diabetes mellitus")],
        "hypertension": [("I10","Essential hypertension"),("N18.3","Chronic kidney disease, stage 3"),("E78.5","Hyperlipidaemia")],
        "pneumonia": [("J18.9","Pneumonia, unspecified"),("J96.00","Acute respiratory failure"),("R04.2","Haemoptysis")],
        "sepsis": [("A41.9","Sepsis, unspecified"),("N39.0","Urinary tract infection"),("R65.20","Severe sepsis without septic shock")],
    }
    title_lower = (dx_title or "").lower()
    dx_list = next((v for k,v in dx_map.items() if k in title_lower),
                   [("I99.9","Other circulatory disorders"),("R00.0","Tachycardia, unspecified")])
    diagnoses = [{"hadm_id":hadm_id,"icd_code":code,"icd_version":10,"long_title":title,"seq_num":i+1}
                 for i,(code,title) in enumerate(dx_list)]
    procedures = [
        {"hadm_id":hadm_id,"icd_code":"4A023N7","icd_version":10,"long_title":"Measurement of Cardiac Sampling and Pressure, Percutaneous Approach","seq_num":1},
        {"hadm_id":hadm_id,"icd_code":"5A02116","icd_version":10,"long_title":"Assistance with Cardiac Output using Impeller Pump, Continuous","seq_num":2},
    ]
    icustays = [{"hadm_id":hadm_id,"stay_id":hadm_id*10,"first_careunit":"CCU","last_careunit":"CCU",
                 "intime":admit_time,"outtime":admit_time,"los":round(_r.uniform(1,4),2)}]
    transfers = [
        {"hadm_id":hadm_id,"transfer_id":hadm_id*10+1,"eventtype":"admit","careunit":"Emergency Department","intime":admit_time,"outtime":admit_time},
        {"hadm_id":hadm_id,"transfer_id":hadm_id*10+2,"eventtype":"transfer","careunit":"CCU","intime":admit_time,"outtime":admit_time},
    ]
    return {
        "admission": adm, "patient": adm, "admissions": [adm],
        "diagnoses": diagnoses, "diagnoses_icd": diagnoses,
        "procedures": procedures, "procedures_icd": procedures,
        "icustays": icustays, "transfers": transfers,
        "microbiologyevents": [
            {"hadm_id":hadm_id,"micro_specimen_id":hadm_id*10+1,"spec_itemid":70012,
             "spec_type_desc":"BLOOD CULTURE","org_itemid":None,"org_name":None,
             "charttime":admit_time,"test_name":"BLOOD CULTURE","interpretation":"No growth after 5 days"}
        ], "omr": [],
        "labevents":[],"prescriptions":[],"pharmacy":[],"poe":[],
        "chartevents":[],"inputevents":[],"outputevents":[],"procedureevents":[],
    }


def _overlay_identity(hadm_id: int, data: dict) -> dict:
    """Stamp the authoritative de-identified identity from active_patients onto a
    display payload. active_patients.patient_name is the SINGLE SOURCE OF TRUTH —
    MIMIC / ETL / synthetic names must never override it, so the patient's name
    cannot change or get lost across the ward → discharge handoff. Cheap indexed
    PK lookup; applied on every /display response (incl. cache hits) so a re-admit
    or status change can never serve a stale identity."""
    if not isinstance(data, dict) or data.get("error"):
        return data
    from .cloud_sql_db import get_engine as _ge
    from sqlalchemy import text as _text
    name = code = None
    try:
        with _ge().connect() as conn:
            row = conn.execute(_text(
                "SELECT patient_name, patient_code FROM active_patients WHERE hadm_id=:h"
            ), {"h": hadm_id}).fetchone()
        if row:
            name, code = row[0], row[1]
    except Exception:
        pass
    # Never emit a misleading placeholder like "Demo Patient" — fall back to a
    # de-identified label tied to this hadm_id.
    name = name or code or f"HADM-{hadm_id}"
    data["patient_name"] = name
    data["full_name"] = name
    for _k in ("admission", "patient"):
        if isinstance(data.get(_k), dict):
            data[_k]["patient_name"] = name
            data[_k]["full_name"] = name
    if isinstance(data.get("admissions"), list):
        for _a in data["admissions"]:
            if isinstance(_a, dict):
                _a["patient_name"] = name
                _a["full_name"] = name
    return data


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
    # BQ fetch is triggered once from billing generate-cost-estimate only.
    # Startup backfill is disabled to avoid slow BQ calls on every server restart.
    pass


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
    """Resolve display data, then stamp the authoritative de-identified identity
    from active_patients (single source of truth) so the patient name can never
    change or get lost across the ward → discharge handoff."""
    data = await _resolve_patient_display(hadm_id)
    return await run_in_threadpool(_overlay_identity, hadm_id, data)


async def _resolve_patient_display(hadm_id: int):
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

    # Fast path for demo/synthetic patients: skip BQ ETL, return synthetic display immediately
    if status == "failed":
        log.info(f"[display] {hadm_id} data_fetch_status=failed → synthetic display (no BQ retry)")
        fb = await run_in_threadpool(_synth_display, hadm_id)
        _display_memory_cache[hadm_id] = fb
        return fb

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
            log.warning(f"[display] ETL failed for {hadm_id}: {result['error']} — using synthetic fallback")
            fb = await run_in_threadpool(_synth_display, hadm_id)
            _display_memory_cache[hadm_id] = fb
            return fb
        data = await run_in_threadpool(csr.read_display_data, hadm_id)
        if "error" in data:
            fb = await run_in_threadpool(_synth_display, hadm_id)
            _display_memory_cache[hadm_id] = fb
            return fb
        _display_memory_cache[hadm_id] = data
        return data

    # Tier 3: patient not yet in active directory → run display ETL (BQ fetch, ~5 s)
    try:
        await _ensure_in_active_directory(hadm_id)
    except Exception as e:
        log.warning(f"[display] _ensure_in_active_directory failed for {hadm_id}: {e} — synthetic fallback")
        fb = await run_in_threadpool(_synth_display, hadm_id)
        _display_memory_cache[hadm_id] = fb
        return fb
    data = await run_in_threadpool(csr.read_display_data, hadm_id)
    if "error" in data:
        log.warning(f"[display] read_display_data failed for {hadm_id}: {data['error']} — synthetic fallback")
        fb = await run_in_threadpool(_synth_display, hadm_id)
        _display_memory_cache[hadm_id] = fb
        return fb
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
                if not rows:
                    _synth_tabs_set = {"labevents","chartevents","prescriptions","pharmacy","poe","fluids","procedureevents"}
                    if tab_name in _synth_tabs_set:
                        fallback = _synth_tab(hadm_id, tab_name)
                        if fallback:
                            log.info(f"[tab] synthetic fallback (sql-fetched-empty) {hadm_id}/{tab_name} ({len(fallback)} rows)")
                            sql_data = {tab_name: fallback}
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
            # BigQuery unavailable — try synth fallback first, then serve Cloud SQL or empty
            _synth_tabs_ex = {"labevents","chartevents","prescriptions","pharmacy","poe","fluids","procedureevents"}
            if tab_name in _synth_tabs_ex:
                fallback = _synth_tab(hadm_id, tab_name)
                if fallback:
                    log.info(f"[tab] synthetic fallback (bq-exc) {hadm_id}/{tab_name} ({len(fallback)} rows)")
                    fb_data = {tab_name: fallback}
                    _tab_memory_cache[_cache_key] = fb_data
                    fut.set_result(fb_data)
                    return fb_data
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

        # Synthetic fallback — for demo patients with no BQ/SQL data, auto-populate plausible rows
        _synth_tabs = {"labevents","chartevents","prescriptions","pharmacy","poe","fluids","procedureevents"}
        if tab_name in _synth_tabs:
            tab_key = next(iter(data), tab_name)
            if not data.get(tab_key):
                fallback = _synth_tab(hadm_id, tab_name)
                if fallback:
                    log.info(f"[tab] synthetic fallback for {hadm_id}/{tab_name} ({len(fallback)} rows)")
                    data = {tab_key: fallback}

        _tab_memory_cache[_cache_key] = data
        fut.set_result(data)
        return data

    except Exception as exc:
        if not fut.done():
            fut.set_exception(exc)
        raise
    finally:
        _tab_in_flight.pop(_cache_key, None)


# ── Billing-triggered full ETL prefetch ──────────────────────────────────────

@app.post("/api/patient/{hadm_id}/prefetch-all")
async def prefetch_all_tabs(hadm_id: int):
    """
    Called by billing.html after generate-cost-estimate.
    Runs the full BQ ETL (all clinical tabs with row limits) and writes to Cloud SQL.
    Sets data_fetch_status='fetched' when done so ward board shows vitals and
    upload.html reads from Cloud SQL without hitting BQ again.
    """
    from sqlalchemy import text as _t

    engine = await run_in_threadpool(get_engine)

    def _set_status(s: str):
        with engine.begin() as c:
            c.execute(_t("UPDATE active_patients SET data_fetch_status=:s WHERE hadm_id=:h"),
                      {"s": s, "h": hadm_id})

    def _run_full_etl():
        current = csr.get_fetch_status(hadm_id)
        if current == "fetched":
            log.info(f"[prefetch-all] hadm_id={hadm_id} already fetched — skipping BQ ETL")
            return {"skipped": True, "status": "fetched"}
        _set_status("fetching")
        result = fetch_and_store_patient(hadm_id, engine, display_only=False)
        if "error" in result and not result.get("skipped"):
            _set_status("failed")
            return result
        # Set 'partial' — ward board keeps showing loader until ward backend's
        # sync-vitals endpoint runs sync_patient_from_mimic and sets 'fetched'.
        _set_status("partial")
        return result

    result = await run_in_threadpool(_run_full_etl)
    if "error" in result and not result.get("skipped"):
        raise HTTPException(status_code=500, detail=result["error"])

    # Bust tab memory cache so next request reads freshly written Cloud SQL data
    for tab in ["prescriptions","labevents","pharmacy","poe","chartevents","fluids","procedureevents","outputevents"]:
        _tab_memory_cache.pop((hadm_id, tab), None)

    # Server-side trigger of the ward EWS vitals sync so ews_* (vitals/labs/meds +
    # NEWS2) is populated even if the browser tab closes after this call — the load
    # no longer depends on billing.html's fire-and-forget chain. Idempotent: the
    # ward sync only flips status 'partial'/'fetching'/'pending' → 'fetched'.
    ews_synced = False
    ward_base = os.environ.get("WARD_API_BASE", "http://localhost:7806")
    try:
        import httpx
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)
        ) as _c:
            _r = await _c.post(f"{ward_base}/api/patients/{hadm_id}/sync-vitals")
            ews_synced = (_r.status_code == 200 and (_r.json() or {}).get("status") == "ok")
    except Exception as _e:
        log.warning(f"[prefetch-all] ward EWS sync trigger failed for {hadm_id}: {_e}")

    return {"status": "fetched", "hadm_id": hadm_id, "ews_synced": ews_synced,
            "counts": result.get("counts", {})}


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
