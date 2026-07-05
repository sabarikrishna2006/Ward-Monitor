import os
import asyncio
import hashlib
import logging
import time
import smtplib
import secrets
import urllib.parse
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import csv
import io
import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, BackgroundTasks
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv

# Cloud SQL App DB — all app-level tables (users, encounters, summaries, etc.)
from . import cloud_sql_app_db as gdb

# Data server URL — BigQuery + Cloud SQL data layer (local dev: 7016)
DATA_SERVER = os.environ.get("DATA_SERVER_URL", "http://127.0.0.1:7016")

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'), override=True)

app = FastAPI(title="Discharge Summary AI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

@app.on_event("startup")
async def startup_event():
    from sqlalchemy import text as _text
    from .cloud_sql_db import get_engine as _get_engine

    _migration_013 = """
        ALTER TABLE rejection_log
            ADD COLUMN IF NOT EXISTS files_ready_at TIMESTAMPTZ;

        ALTER TABLE app_encounters
            DROP CONSTRAINT IF EXISTS app_encounters_status_check;

        ALTER TABLE app_encounters
            ADD CONSTRAINT app_encounters_status_check CHECK (
                status IN (
                    'Pending Ingestion','Processing','Data Incomplete',
                    'Ready for Review','Awaiting Confirmation',
                    'Verifying Claims','Awaiting Review','Signed Off',
                    'Revision Requested','Files Ready','Amendment Requested'
                )
            );
    """
    try:
        with _get_engine().begin() as _conn:
            for _stmt in [s.strip() for s in _migration_013.split(";") if s.strip()]:
                _conn.execute(_text(_stmt))
        log.info("Migration 013 applied (or already up to date)")
    except Exception as _e:
        log.warning(f"Migration 013 skipped: {_e}")

    # Migration 002 — error_log table + tier3_rolling_7d view (3-Tier Accuracy Framework)
    _migration_002_table = """
        CREATE TABLE IF NOT EXISTS error_log (
            id              SERIAL      PRIMARY KEY,
            hadm_id         VARCHAR(20),
            summary_version VARCHAR(10),
            nabh_section    VARCHAR(10),
            error_tier      SMALLINT    NOT NULL CHECK (error_tier IN (1, 2, 3)),
            ai_output       TEXT,
            correct_value   TEXT,
            error_category  VARCHAR(50),
            source_present  BOOLEAN,
            attending_id    VARCHAR(40),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_error_log_tier    ON error_log (error_tier);
        CREATE INDEX IF NOT EXISTS idx_error_log_hadm    ON error_log (hadm_id);
        CREATE INDEX IF NOT EXISTS idx_error_log_created ON error_log (created_at DESC)
    """
    _migration_002_view = """
        DROP VIEW IF EXISTS tier3_rolling_7d;
        CREATE VIEW tier3_rolling_7d AS
        SELECT
            COUNT(*) FILTER (WHERE el.error_tier = 3)   AS tier3_count,
            COUNT(*)                                     AS total_errors,
            COALESCE((
                SELECT COUNT(*)
                FROM app_summaries
                WHERE created_at >= NOW() - INTERVAL '7 days'
            ), 0)                                        AS total_summaries,
            ROUND(
                COUNT(*) FILTER (WHERE el.error_tier = 3)::numeric
                / NULLIF((
                    SELECT COUNT(*)
                    FROM app_summaries
                    WHERE created_at >= NOW() - INTERVAL '7 days'
                ), 0) * 100,
            1)                                           AS tier3_rate_pct
        FROM error_log el
        WHERE el.created_at >= NOW() - INTERVAL '7 days'
    """
    try:
        with _get_engine().begin() as _conn:
            for _stmt in [s.strip() for s in _migration_002_table.split(";") if s.strip()]:
                _conn.execute(_text(_stmt))
            _conn.execute(_text(_migration_002_view))
        log.info("Migration 002 applied (error_log table + tier3_rolling_7d view)")
    except Exception as _e:
        log.warning(f"Migration 002 skipped: {_e}")

    # Migration 014 — billing_records table
    _migration_014 = """
        CREATE TABLE IF NOT EXISTS billing_records (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            hadm_id         BIGINT NOT NULL UNIQUE,
            encounter_id    UUID,

            payment_mode    VARCHAR(20),
            insurance_co    VARCHAR(120),
            policy_number   VARCHAR(60),
            preauth_number  VARCHAR(60),
            preauth_amount  BIGINT,
            copay_pct       FLOAT,
            room_rent_limit BIGINT,

            selected_band   VARCHAR(10),
            floor_est       BIGINT,
            expected_est    BIGINT,
            ceiling_est     BIGINT,

            actual_charges  BIGINT,
            insurance_paid  BIGINT,
            advance_paid    BIGINT,
            balance_due     BIGINT,

            payment_ref          VARCHAR(120),
            payment_mode_final   VARCHAR(20),

            billing_phase   VARCHAR(30) NOT NULL DEFAULT 'initial_estimate',

            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_billing_hadm    ON billing_records(hadm_id);
        CREATE INDEX IF NOT EXISTS idx_billing_phase   ON billing_records(billing_phase);
    """
    try:
        with _get_engine().begin() as _conn:
            for _stmt in [s.strip() for s in _migration_014.split(";") if s.strip()]:
                _conn.execute(_text(_stmt))
        log.info("Migration 014 applied (or already up to date)")
    except Exception as _e:
        log.warning(f"Migration 014 skipped: {_e}")

    _migration_015 = """
        ALTER TABLE billing_records ADD COLUMN IF NOT EXISTS hbp_code         VARCHAR(20);
        ALTER TABLE billing_records ADD COLUMN IF NOT EXISTS hbp_package_name VARCHAR(200);
        ALTER TABLE billing_records ADD COLUMN IF NOT EXISTS hbp_rate         BIGINT;
        ALTER TABLE billing_records ADD COLUMN IF NOT EXISTS ward_type        VARCHAR(20);
        ALTER TABLE billing_records ADD COLUMN IF NOT EXISTS is_ab_beneficiary BOOLEAN DEFAULT FALSE;
        ALTER TABLE billing_records ADD COLUMN IF NOT EXISTS ab_scheme        VARCHAR(50);
        ALTER TABLE billing_records ADD COLUMN IF NOT EXISTS line_items       JSONB
    """
    try:
        with _get_engine().begin() as _conn:
            for _stmt in [s.strip() for s in _migration_015.split(";") if s.strip()]:
                _conn.execute(_text(_stmt))
        log.info("Migration 015 applied (or already up to date)")
    except Exception as _e:
        log.warning(f"Migration 015 skipped: {_e}")

    # Migration 016 — CE4 reconciliation: actual line items + variance
    _migration_016 = """
        ALTER TABLE billing_records ADD COLUMN IF NOT EXISTS actual_line_items    JSONB;
        ALTER TABLE billing_records ADD COLUMN IF NOT EXISTS reconciliation_notes TEXT;
        ALTER TABLE billing_records ADD COLUMN IF NOT EXISTS variance_pct         FLOAT
    """
    try:
        with _get_engine().begin() as _conn:
            for _stmt in [s.strip() for s in _migration_016.split(";") if s.strip()]:
                _conn.execute(_text(_stmt))
        log.info("Migration 016 applied (or already up to date)")
    except Exception as _e:
        log.warning(f"Migration 016 skipped: {_e}")

    # Migration 017 — expected discharge, scheme/insurance breakdown columns
    _migration_017 = """
        ALTER TABLE billing_records ADD COLUMN IF NOT EXISTS expected_discharge_date DATE;
        ALTER TABLE billing_records ADD COLUMN IF NOT EXISTS expected_los_days        INTEGER;
        ALTER TABLE billing_records ADD COLUMN IF NOT EXISTS actual_los_days          INTEGER;
        ALTER TABLE billing_records ADD COLUMN IF NOT EXISTS patient_pays_estimate    BIGINT;
        ALTER TABLE billing_records ADD COLUMN IF NOT EXISTS govt_pays                BIGINT;
        ALTER TABLE billing_records ADD COLUMN IF NOT EXISTS room_rent_excess         BIGINT;
        ALTER TABLE billing_records ADD COLUMN IF NOT EXISTS scheme_note              TEXT
    """
    try:
        with _get_engine().begin() as _conn:
            for _stmt in [s.strip() for s in _migration_017.split(";") if s.strip()]:
                _conn.execute(_text(_stmt))
        log.info("Migration 017 applied (or already up to date)")
    except Exception as _e:
        log.warning(f"Migration 017 skipped: {_e}")

    _migration_018 = """
        ALTER TABLE app_summaries ADD COLUMN IF NOT EXISTS gap_t1 INTEGER DEFAULT 0;
        ALTER TABLE app_summaries ADD COLUMN IF NOT EXISTS gap_t2 INTEGER DEFAULT 0;
        ALTER TABLE app_summaries ADD COLUMN IF NOT EXISTS gap_t3 INTEGER DEFAULT 0
    """
    try:
        with _get_engine().begin() as _conn:
            for _stmt in [s.strip() for s in _migration_018.split(";") if s.strip()]:
                _conn.execute(_text(_stmt))
        log.info("Migration 018 applied (or already up to date)")
    except Exception as _e:
        log.warning(f"Migration 018 skipped: {_e}")

    _migration_019 = """
        ALTER TABLE app_summaries ADD COLUMN IF NOT EXISTS dl_flags INTEGER DEFAULT NULL
    """
    try:
        with _get_engine().begin() as _conn:
            _conn.execute(_text(_migration_019))
        log.info("Migration 019 applied (or already up to date)")
    except Exception as _e:
        log.warning(f"Migration 019 skipped: {_e}")

    _migration_020_stmts = [
        """CREATE TABLE IF NOT EXISTS summary_versions (
               id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
               summary_id    UUID NOT NULL REFERENCES app_summaries(id) ON DELETE CASCADE,
               encounter_id  UUID NOT NULL,
               hadm_id       BIGINT NOT NULL,
               version_num   INTEGER NOT NULL,
               content       TEXT NOT NULL,
               sections_json JSONB,
               saved_by      UUID,
               saved_by_name TEXT,
               save_type     VARCHAR(20) NOT NULL DEFAULT 'draft',
               created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
               UNIQUE (encounter_id, version_num)
           )""",
        "CREATE INDEX IF NOT EXISTS idx_sv_encounter ON summary_versions(encounter_id)",
        "ALTER TABLE app_summaries ADD COLUMN IF NOT EXISTS draft_saved_at TIMESTAMPTZ",
        "ALTER TABLE app_summaries ADD COLUMN IF NOT EXISTS draft_edits    JSONB",
        "ALTER TABLE app_summaries ADD COLUMN IF NOT EXISTS doc_version    INTEGER DEFAULT 0",
    ]
    try:
        with _get_engine().begin() as _conn:
            for _stmt in _migration_020_stmts:
                _conn.execute(_text(_stmt))
        log.info("Migration 020 applied (or already up to date)")
    except Exception as _e:
        log.warning(f"Migration 020 skipped: {_e}")

    try:
        with _get_engine().begin() as _conn:
            _conn.execute(_text(
                "ALTER TABLE app_summaries ADD COLUMN IF NOT EXISTS gap_rows JSONB"
            ))
        log.info("Migration 021 applied (or already up to date)")
    except Exception as _e:
        log.warning(f"Migration 021 skipped: {_e}")

    _migration_022_stmts = [
        "ALTER TABLE app_encounters ADD COLUMN IF NOT EXISTS rejection_count INTEGER DEFAULT 0",
        "ALTER TABLE app_summaries  ADD COLUMN IF NOT EXISTS llm_edits_count INTEGER DEFAULT 0",
    ]
    try:
        with _get_engine().begin() as _conn:
            for _stmt in _migration_022_stmts:
                _conn.execute(_text(_stmt))
        log.info("Migration 022 applied (or already up to date)")
    except Exception as _e:
        log.warning(f"Migration 022 skipped: {_e}")

    # ── Seed insurance data for all patients ──────────────────────────────────
    # Ensures every patient in active_patients has insurance_co + payment_mode
    # in billing_records so the billing dashboard always shows real DB values.
    try:
        import random as _ins_rng
        _INSURERS = ['Star Health', 'HDFC Ergo', 'ICICI Lombard',
                     'New India Assurance', 'Bajaj Allianz', 'Niva Bupa', 'United India']
        _MODES    = ['Cashless', 'Cashless', 'Cashless', 'Reimbursement', 'Self-pay']

        def _seeded_insurance(hadm_id):
            r = _ins_rng.Random(hadm_id * 13 + 7)
            mode = _MODES[r.randint(0, len(_MODES) - 1)]
            if mode == 'Self-pay':
                return None, 'Self-pay'
            return _INSURERS[r.randint(0, len(_INSURERS) - 1)], mode

        with _get_engine().connect() as _conn:
            # Get patients needing insurance seeding — skip AB beneficiaries (PM-JAY/CGHS/ESI)
            _pts = _conn.execute(_text("""
                SELECT ap.hadm_id
                FROM active_patients ap
                LEFT JOIN billing_records br ON br.hadm_id = ap.hadm_id
                WHERE (br.hadm_id IS NULL OR br.insurance_co IS NULL)
                  AND (br.is_ab_beneficiary IS NULL OR br.is_ab_beneficiary = FALSE)
                LIMIT 5000
            """)).fetchall()

        _to_seed = [row[0] for row in _pts]
        if _to_seed:
            with _get_engine().begin() as _conn:
                for _hid in _to_seed:
                    _ins_co, _ins_mode = _seeded_insurance(_hid)
                    _conn.execute(_text("""
                        INSERT INTO billing_records (hadm_id, billing_phase, insurance_co, payment_mode)
                        VALUES (:h, 'initial_estimate', :ic, :im)
                        ON CONFLICT (hadm_id) DO UPDATE
                          SET insurance_co  = EXCLUDED.insurance_co,
                              payment_mode  = EXCLUDED.payment_mode
                        WHERE billing_records.insurance_co IS NULL
                    """), {"h": _hid, "ic": _ins_co, "im": _ins_mode})
            log.info(f"Insurance seeded for {len(_to_seed)} patients")
        else:
            log.info("Insurance already seeded for all patients")
    except Exception as _e:
        log.warning(f"Insurance seeding skipped: {_e}")

    _migration_021 = """
        CREATE TABLE IF NOT EXISTS amendment_log (
            id                SERIAL PRIMARY KEY,
            encounter_id      UUID,
            hadm_id           INTEGER,
            amendment_ref     TEXT,
            from_version      TEXT DEFAULT 'v1.0',
            to_version        TEXT DEFAULT 'v1.1',
            reason            TEXT,
            section           TEXT,
            details           TEXT,
            doc_name          TEXT,
            submitted_by_name TEXT,
            status            TEXT DEFAULT 'Pending Re-sign',
            created_at        TIMESTAMPTZ DEFAULT NOW()
        )
    """
    try:
        with _get_engine().begin() as _conn:
            for _stmt in [s.strip() for s in _migration_021.split(";") if s.strip()]:
                _conn.execute(_text(_stmt))
        log.info("Migration 021 applied (or already up to date)")
    except Exception as _e:
        log.warning(f"Migration 021 skipped: {_e}")

    # Migration 022 — add source_file_id to all ap_* upload tables.
    # Each statement runs in its own transaction so one missing table
    # doesn't roll back the others (was the bug: all in one txn).
    _migration_022_stmts = [
        "ALTER TABLE ap_prescriptions      ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40)",
        "ALTER TABLE ap_labevents           ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40)",
        "ALTER TABLE ap_microbiologyevents  ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40)",
        "ALTER TABLE ap_chartevents         ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40)",
        "ALTER TABLE ap_icustays            ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40)",
        "ALTER TABLE ap_transfers           ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40)",
        "ALTER TABLE ap_pharmacy            ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40)",
        "ALTER TABLE ap_poe                 ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40)",
        "ALTER TABLE ap_diagnoses           ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40)",
        "ALTER TABLE ap_procedures          ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40)",
        "ALTER TABLE ap_inputevents         ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40)",
        "ALTER TABLE ap_procedureevents     ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40)",
        "ALTER TABLE ap_outputevents        ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40)",
        "CREATE INDEX IF NOT EXISTS idx_rx_file_id    ON ap_prescriptions    (source_file_id) WHERE source_file_id IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_lab_file_id   ON ap_labevents         (source_file_id) WHERE source_file_id IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_micro_file_id ON ap_microbiologyevents(source_file_id) WHERE source_file_id IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_chart_file_id ON ap_chartevents       (source_file_id) WHERE source_file_id IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_poe_file_id   ON ap_poe               (source_file_id) WHERE source_file_id IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_pharm_file_id ON ap_pharmacy          (source_file_id) WHERE source_file_id IS NOT NULL",
    ]
    _m022_ok = 0
    for _stmt in _migration_022_stmts:
        try:
            with _get_engine().begin() as _conn:
                _conn.execute(_text(_stmt))
            _m022_ok += 1
        except Exception as _e:
            log.warning(f"Migration 022 stmt skipped ({_stmt[:60]}…): {_e}")
    log.info(f"Migration 022: {_m022_ok}/{len(_migration_022_stmts)} statements applied")

    # Migration 023 — display_id column for human-readable patient IDs (PT-YY-NNNN)
    try:
        with _get_engine().begin() as _conn:
            _conn.execute(_text(
                "ALTER TABLE app_encounters ADD COLUMN IF NOT EXISTS display_id VARCHAR(20) UNIQUE"
            ))
            # Backfill existing encounters that have no display_id
            _conn.execute(_text("""
                WITH numbered AS (
                    SELECT id,
                           CAST(EXTRACT(YEAR FROM COALESCE(created_at, NOW())) AS INT) % 100 AS yr,
                           ROW_NUMBER() OVER (
                               PARTITION BY CAST(EXTRACT(YEAR FROM COALESCE(created_at, NOW())) AS INT)
                               ORDER BY COALESCE(created_at, NOW())
                           ) AS rn
                    FROM app_encounters
                    WHERE display_id IS NULL
                )
                UPDATE app_encounters ae
                SET display_id = 'PT-' || LPAD(n.yr::text, 2, '0') || '-' || LPAD(n.rn::text, 4, '0')
                FROM numbered n
                WHERE ae.id = n.id
            """))
        log.info("Migration 023 applied (display_id column + backfill)")
    except Exception as _e:
        log.warning(f"Migration 023 skipped: {_e}")

    # Migration 024 — Super Admin backend: module toggles, NEWS2 thresholds, drug-lab rules
    _migration_024_stmts = [
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS module_toggles JSONB",
        "ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS news2_thresholds JSONB",
        """UPDATE app_settings SET module_toggles = '{
            "module_a_discharge_summary": true,
            "module_b_cost_estimator": true,
            "module_c_early_warning": true,
            "module_d_drug_lab_engine": true,
            "llm_integration": true,
            "dpdpa_consent_gate": true,
            "push_notifications": true
        }'::jsonb WHERE id = 1 AND module_toggles IS NULL""",
        """UPDATE app_settings SET news2_thresholds = '{
            "spo2":  {"label": "SpO₂",            "low": 88,   "high": null, "action": "< 90% → Escalate"},
            "rr":    {"label": "Respiratory Rate", "low": 8,    "high": 25,   "action": "> 20 → Alert"},
            "hr":    {"label": "Heart Rate",        "low": 40,   "high": 130,  "action": "< 50 or > 120 → Alert"},
            "sbp":   {"label": "Systolic BP",       "low": 90,   "high": null, "action": "< 90 → Escalate"},
            "temp":  {"label": "Temperature",       "low": 35.0, "high": 39.0, "action": "< 35.5 or > 38.5 → Alert"},
            "avpu":  {"label": "AVPU",               "low": null, "high": null, "action": "Any V,P,U → Escalate"},
            "news2": {"label": "NEWS2 Score",       "low": null, "high": 7,    "action": "> 5 → Doctor alert"}
        }'::jsonb WHERE id = 1 AND news2_thresholds IS NULL""",
        """CREATE TABLE IF NOT EXISTS drug_lab_rules (
            id                 SERIAL PRIMARY KEY,
            rule_code          VARCHAR(20) UNIQUE NOT NULL,
            agent_a            VARCHAR(120),
            agent_b            VARCHAR(120) NOT NULL,
            interaction_type   VARCHAR(10) NOT NULL CHECK (interaction_type IN ('DDI','DLI','LI')),
            severity           VARCHAR(5)  NOT NULL CHECK (severity IN ('T1','T2')),
            action_required    TEXT NOT NULL,
            evidence           TEXT,
            is_active          BOOLEAN NOT NULL DEFAULT TRUE,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_dlr_active ON drug_lab_rules(is_active) WHERE is_active = TRUE",
        """INSERT INTO drug_lab_rules (rule_code, agent_a, agent_b, interaction_type, severity, action_required, evidence) VALUES
            ('R-001','Warfarin','Aspirin','DDI','T1','Hold + Co-sign required','ACCP 2022'),
            ('R-002','Digoxin','K+ < 3.0 mEq/L','DLI','T1','Alert attending immediately','ESC Heart Failure Guidelines 2023'),
            ('R-003','ACE Inhibitor','K+ supplement','DDI','T2','Monitor K+ every 48h','ESC Heart Failure Guidelines 2023'),
            ('R-004','Statins','Amiodarone','DDI','T2','Myopathy risk - CK monitoring','ACCP 2022'),
            ('R-005','Heparin','NSAID','DDI','T1','Bleeding risk - hold NSAID','ACCP 2022'),
            ('R-006','Beta-blocker','Verapamil','DDI','T1','Heart block risk - ECG monitoring','ESC Heart Failure Guidelines 2023'),
            ('R-007','Clopidogrel','Omeprazole','DDI','T2','CYP2C19 interaction - switch PPI','ACCP 2022'),
            ('R-008','Vancomycin','Creatinine > 1.5','DLI','T2','Renal dose adjustment required','ICMR'),
            ('R-009','Metformin','Contrast dye','DDI','T1','Hold 48h pre/post contrast','ESC Heart Failure Guidelines 2023'),
            ('R-010','Amiodarone','Warfarin','DDI','T2','INR monitoring - target 2.0-3.0','ACCP 2022'),
            ('R-011','Furosemide','K+ < 3.2 mEq/L','DLI','T2','K+ replacement - 40 mEq/day','ESC Heart Failure Guidelines 2023'),
            ('R-012',NULL,'Troponin > 0.4 ug/L','LI','T1','STEMI protocol - cath lab alert','ESC Heart Failure Guidelines 2023'),
            ('R-013','Haloperidol','QTc > 460ms','DLI','T1','Hold haloperidol - ECG monitoring','FDA')
        ON CONFLICT (rule_code) DO NOTHING""",
    ]
    _m024_ok = 0
    for _stmt in _migration_024_stmts:
        try:
            with _get_engine().begin() as _conn:
                _conn.execute(_text(_stmt))
            _m024_ok += 1
        except Exception as _e:
            log.warning(f"Migration 024 stmt skipped ({_stmt[:60]}…): {_e}")
    log.info(f"Migration 024: {_m024_ok}/{len(_migration_024_stmts)} statements applied")

@app.on_event("shutdown")
async def shutdown_event():
    await _data_client.aclose()

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
        headers={"Access-Control-Allow-Origin": "*"},
    )

GEMINI_KEY      = os.environ.get("GEMINI_API_KEY", "")
SMTP_FROM_EMAIL = os.environ.get("SMTP_FROM_EMAIL", "")
SMTP_APP_PASS   = os.environ.get("SMTP_APP_PASSWORD", "")

gemini_client = None
GEMINI_MODEL  = "gemini-2.5-flash"
# Prompt versions — bump these when you change Pass 1 or Pass 2 system prompts
PASS1_VERSION = "1.1"
PASS2_VERSION = "1.1"
if GEMINI_KEY:
    try:
        from google import genai as _genai
        gemini_client = _genai.Client(api_key=GEMINI_KEY)
        log.info(f"Gemini client initialized (model: {GEMINI_MODEL})")
    except Exception as e:
        log.warning(f"Gemini setup failed: {e}")


# ── Auth ──────────────────────────────────────────────────────────────────────
import bcrypt as _bcrypt

class LoginRequest(BaseModel):
    hospital_email: str
    password: str
    role: Optional[str] = None

class RegisterRequest(BaseModel):
    full_name: str
    hospital_email: str
    password: str
    role: str  # "doctor" or "admin"
    department: Optional[str] = None
    phone: Optional[str] = None

class ForgotPasswordRequest(BaseModel):
    hospital_email: str

_ROLE_MAP = {"doctor": "Doctor", "admin": "Admin Staff", "Doctor": "Doctor", "Admin Staff": "Admin Staff"}

def _check_password(plain: str, stored: str) -> bool:
    if not stored:
        return False
    try:
        return _bcrypt.checkpw(plain.encode(), stored.encode())
    except Exception:
        # fallback for plain-text passwords already in DB
        return plain == stored

@app.post("/api/auth/login")
def login(req: LoginRequest):
    if req.role:
        # Explicit role — look up that role only
        db_role = _ROLE_MAP.get(req.role, req.role)
        candidates = [gdb.get_user_by_email_role(req.hospital_email, db_role)]
    else:
        # Auto-detect — try both roles, use whichever password matches
        candidates = [
            gdb.get_user_by_email_role(req.hospital_email, "Doctor"),
            gdb.get_user_by_email_role(req.hospital_email, "Admin Staff"),
        ]
    user = None
    for candidate in candidates:
        if not candidate:
            continue
        stored_hash = candidate.get("password_hash", "")
        log.info(f"Login check for {req.hospital_email} ({candidate.get('role')}), hash: {stored_hash[:10] if stored_hash else 'EMPTY'}")
        if _check_password(req.password, stored_hash):
            user = candidate
            # Upgrade plain-text password to bcrypt on successful login
            if stored_hash and not stored_hash.startswith("$2"):
                try:
                    new_hash = _bcrypt.hashpw(req.password.encode(), _bcrypt.gensalt()).decode()
                    gdb.update_user(candidate["id"], {"password_hash": new_hash})
                    log.info(f"Upgraded plain-text password to bcrypt for {candidate['id']}")
                except Exception as e:
                    log.warning(f"Password upgrade failed: {e}")
            break
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {
        "status": "success",
        "token": "dummy_session_token_123",
        "user": {"id": user["id"], "email": user["hospital_email"], "role": "doctor" if user["role"]=="Doctor" else "admin", "full_name": user.get("full_name", "")},
    }

@app.post("/api/auth/register")
def register(req: RegisterRequest):
    db_role = _ROLE_MAP.get(req.role, req.role)
    if gdb.get_user_by_email_role(req.hospital_email, db_role):
        raise HTTPException(status_code=409, detail="Email already registered for this role")
    hashed = _bcrypt.hashpw(req.password.encode(), _bcrypt.gensalt()).decode()
    created = gdb.create_user(
        email=req.hospital_email,
        password_hash=hashed,
        role=db_role,
        full_name=req.full_name,
    )
    return {
        "status": "success",
        "user": {"id": created["id"], "email": created["hospital_email"], "role": req.role, "full_name": created.get("full_name", "")},
    }

def _send_reset_email(to_email: str, full_name: str, role: str, token: str):
    if not SMTP_FROM_EMAIL or not SMTP_APP_PASS:
        log.warning("SMTP not configured — skipping email send")
        return
    reset_link = f"http://localhost:5183/?reset_token={token}&email={urllib.parse.quote(to_email)}"
    role_label = "Doctor" if role == "Doctor" else "Admin Staff"
    body_html = f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;padding:32px 24px;background:#f9fafb;border-radius:10px">
      <div style="font-size:22px;font-weight:700;color:#2A6F77;margin-bottom:4px">Discharge Summary AI</div>
      <div style="font-size:12px;color:#6B7280;margin-bottom:28px">Apollo Hospitals · Cardiac &amp; Surgical Wing</div>
      <h2 style="font-size:18px;color:#111827;margin-bottom:8px">Password Reset Request</h2>
      <p style="color:#374151;font-size:14px;line-height:1.6">Hi <strong>{full_name}</strong>,</p>
      <p style="color:#374151;font-size:14px;line-height:1.6">
        We received a password reset request for your <strong>{role_label}</strong> account
        (<code style="background:#F3F4F6;padding:2px 6px;border-radius:4px">{to_email}</code>).
      </p>
      <a href="{reset_link}" style="display:inline-block;margin:20px 0;padding:12px 28px;background:#2A6F77;color:#fff;text-decoration:none;border-radius:7px;font-size:14px;font-weight:600">
        Reset My Password
      </a>
      <p style="color:#6B7280;font-size:12px;margin-top:20px">
        This link expires in 1 hour. If you didn't request this, ignore this email — your account is safe.
      </p>
      <hr style="border:none;border-top:1px solid #E5E7EB;margin:24px 0"/>
      <p style="color:#9CA3AF;font-size:11px">Discharge Summary AI · PHI local · HIPAA-aligned</p>
    </div>"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[DS·AI] Password reset for {to_email}"
    msg["From"]    = f"Discharge Summary AI <{SMTP_FROM_EMAIL}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(body_html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
        srv.login(SMTP_FROM_EMAIL, SMTP_APP_PASS)
        srv.sendmail(SMTP_FROM_EMAIL, to_email, msg.as_string())
    log.info(f"Reset email sent to {to_email}")

@app.post("/api/auth/forgot-password")
def forgot_password(req: ForgotPasswordRequest, background_tasks: BackgroundTasks):
    # Try both roles
    user = gdb.get_user_by_email_role(req.hospital_email, "Doctor") or \
           gdb.get_user_by_email_role(req.hospital_email, "Admin Staff")
    if not user:
        raise HTTPException(status_code=404, detail="Email not registered. Contact your admin.")
    token  = secrets.token_urlsafe(32)
    expiry = int(time.time()) + 3600
    # Store token separately — never touch the user record here to avoid
    # overwriting a just-reset password_hash via stale read-modify-write
    gdb.create_reset_token(user["id"], token, expiry)
    background_tasks.add_task(
        _send_reset_email,
        user["hospital_email"], user.get("full_name", "User"), user["role"], token
    )
    return {"status": "success", "message": "Reset link sent."}


class ResetPasswordRequest(BaseModel):
    email: str
    token: str
    new_password: str

@app.post("/api/auth/reset-password")
def reset_password(req: ResetPasswordRequest):
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    token_data = gdb.get_reset_token(req.token)
    if not token_data:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    if time.time() > float(token_data["expiry"]):
        gdb.delete_reset_token(req.token)
        raise HTTPException(status_code=400, detail="Reset link has expired. Please request a new one.")
    user = gdb.get_user_by_id(token_data["user_id"])
    if not user or user.get("hospital_email") != req.email:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    # Delete token immediately (single-use)
    gdb.delete_reset_token(req.token)
    hashed = _bcrypt.hashpw(req.new_password.encode(), _bcrypt.gensalt()).decode()
    log.info(f"Resetting password for user {user['id']} ({req.email})")
    result = gdb.update_user(user["id"], {"password_hash": hashed})
    if not result:
        raise HTTPException(status_code=500, detail="Failed to save new password. Please try again.")
    verify = gdb.get_user_by_id(user["id"])
    if not verify or verify.get("password_hash") != hashed:
        log.error(f"Password update did NOT persist for {user['id']}")
        raise HTTPException(status_code=500, detail="Password update did not persist. Please try again.")
    log.info(f"Password reset verified for user {user['id']}")
    return {"status": "success", "message": "Password updated successfully"}


# ── Debug: direct password set (no token required) ────────────────────────────
class DirectResetRequest(BaseModel):
    email: str
    new_password: str

@app.post("/api/auth/direct-reset")
def direct_reset(req: DirectResetRequest):
    """Force-set a password directly. Use only for recovery when reset email is broken."""
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    user = gdb.get_user_by_email_role(req.email, "Doctor") or \
           gdb.get_user_by_email_role(req.email, "Admin Staff")
    if not user:
        raise HTTPException(status_code=404, detail="Email not found")
    hashed = _bcrypt.hashpw(req.new_password.encode(), _bcrypt.gensalt()).decode()
    result = gdb.update_user(user["id"], {"password_hash": hashed})
    if not result:
        raise HTTPException(status_code=500, detail="Write failed")
    verify = gdb.get_user_by_id(user["id"])
    ok = verify and verify.get("password_hash") == hashed
    log.info(f"Direct reset for {req.email} ({user['role']}) — persisted: {ok}")
    return {"status": "ok" if ok else "write_failed", "role": user["role"], "persisted": ok}


# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.get("/api/dashboard")
def get_dashboard_stats():
    all_enc = gdb.list_encounters()
    now = datetime.utcnow()
    month_prefix = now.strftime("%Y-%m")
    open_cases    = sum(1 for e in all_enc if e.get("status") != "Signed Off")
    ready_to_send = sum(1 for e in all_enc if e.get("status") == "Ready for Review")
    signed_month  = sum(1 for e in all_enc if e.get("status") == "Signed Off"
                        and (e.get("updated_at") or "").startswith(month_prefix))

    # Avg generation time from app_summaries.total_latency_s (only non-null, successful runs)
    avg_gen_s = None
    try:
        from app.cloud_sql_db import get_engine
        from sqlalchemy import text as _text
        with get_engine().connect() as conn:
            row = conn.execute(_text(
                "SELECT AVG(total_latency_s) FROM app_summaries WHERE total_latency_s IS NOT NULL AND total_latency_s > 0"
            )).fetchone()
            if row and row[0] is not None:
                avg_gen_s = round(float(row[0]), 1)
    except Exception:
        pass

    return {
        "cards": {
            "open_cases":      open_cases,
            "ready_to_send":   ready_to_send,
            "signed_month":    signed_month,
            "avg_gen_s":       avg_gen_s,
        },
        "system_health": [gdb.get_system_health()],
    }


# ── Billing Dashboard ─────────────────────────────────────────────────────────
@app.get("/api/billing/dashboard")
def billing_dashboard():
    """
    Two-phase billing dashboard:
      Phase 1 (Admission)  — active encounters needing initial cost estimate
      Phase 4 (Discharge)  — Signed Off encounters needing CE4 reconciliation
    """
    from sqlalchemy import text as _text
    from .cloud_sql_db import get_engine as _get_engine

    _COLS = """
        ap.hadm_id, ap.subject_id, ap.gender, ap.anchor_age,
        ap.patient_name,
        ap.admit_time, ap.discharge_time, ap.los_days,
        ap.primary_diagnosis_title,
        br.insurance_co, br.payment_mode,
        ae.id          AS encounter_id,
        ae.status      AS encounter_status,
        ae.discharge_type,
        ae.created_at  AS enc_created_at,
        ae.updated_at  AS enc_updated_at,
        br.billing_phase     AS billing_phase,
        br.expected_est      AS expected_est,
        br.actual_charges    AS actual_charges,
        br.is_ab_beneficiary AS is_ab_beneficiary,
        br.ab_scheme         AS ab_scheme
    """
    with _get_engine().connect() as conn:
        admission_rows = conn.execute(_text(f"""
            SELECT {_COLS}
            FROM active_patients ap
            JOIN app_encounters ae ON ae.hadm_id = ap.hadm_id
            LEFT JOIN billing_records br ON br.hadm_id = ap.hadm_id
            WHERE ae.status IN (
                'Pending Ingestion','Processing','Files Ready',
                'Ready for Review','Awaiting Review',
                'Awaiting Confirmation','Verifying Claims','Revision Requested'
            )
            UNION ALL
            SELECT {_COLS}
            FROM active_patients ap
            JOIN app_encounters ae ON ae.hadm_id = ap.hadm_id
            LEFT JOIN billing_records br ON br.hadm_id = ap.hadm_id
            WHERE ae.status = 'Signed Off'
              AND br.billing_phase = 'amendment_pending'
            ORDER BY enc_created_at DESC LIMIT 100
        """)).fetchall()

        discharge_rows = conn.execute(_text(f"""
            SELECT {_COLS}, au.full_name AS signed_by_name
            FROM active_patients ap
            JOIN app_encounters ae ON ae.hadm_id = ap.hadm_id
            LEFT JOIN billing_records br ON br.hadm_id = ap.hadm_id
            LEFT JOIN app_summaries aps ON aps.encounter_id = ae.id
            LEFT JOIN app_users au ON au.id = aps.signed_by
            WHERE ae.status = 'Signed Off'
              AND (br.billing_phase IS NULL
                   OR br.billing_phase NOT IN ('amendment_pending','final_bill_generated','claim_submitted','tpa_settled','paid'))
            ORDER BY ae.updated_at DESC LIMIT 100
        """)).fetchall()

        final_bill_rows = conn.execute(_text(f"""
            SELECT {_COLS}, au.full_name AS signed_by_name
            FROM active_patients ap
            JOIN app_encounters ae ON ae.hadm_id = ap.hadm_id
            LEFT JOIN billing_records br ON br.hadm_id = ap.hadm_id
            LEFT JOIN app_summaries aps ON aps.encounter_id = ae.id
            LEFT JOIN app_users au ON au.id = aps.signed_by
            WHERE ae.status = 'Signed Off'
              AND br.billing_phase = 'final_bill_generated'
            ORDER BY br.updated_at DESC LIMIT 50
        """)).fetchall()

    def _fmt(dt):
        if not dt:
            return ""
        try:
            from datetime import datetime as _dt
            d = dt if not isinstance(dt, str) else _dt.fromisoformat(dt.replace("Z", ""))
            return d.strftime("%d %b %Y")
        except Exception:
            return str(dt)[:10]

    def _to_action(p, phase):
        bp = p.get("billing_phase") or ""
        if phase == "final_bill":
            status = "Final Bill Overdue"
        elif phase == "discharge":
            status = "Reconciliation Due"
        elif bp == "amendment_pending":
            status = "Amendment Requested"
        else:
            status = "Estimate Pending"
        return {
            "hadm_id":        p["hadm_id"],
            "mrn":            f"PT-{p['hadm_id']}",
            "subject_id":     p["subject_id"],
            "patient_name":   p.get("patient_name") or None,
            "admit_date":     _fmt(p.get("admit_time")),
            "discharge_date": _fmt(p.get("discharge_time")),
            "insurance_co":   p.get("insurance_co") or "",
            "payment_mode":   p.get("payment_mode") or "",
            "encounter_id":   p.get("encounter_id"),
            "phase":          phase,
            "billing_phase":  bp,
            "billing_status": status,
            "expected_est":       p.get("expected_est"),
            "actual_charges":     p.get("actual_charges"),
            "is_ab_beneficiary":  bool(p.get("is_ab_beneficiary")),
            "ab_scheme":          p.get("ab_scheme") or "",
            "signed_by_name":     p.get("signed_by_name") or None,
        }

    admission_patients   = [dict(r._mapping) for r in admission_rows]
    discharge_patients   = [dict(r._mapping) for r in discharge_rows]
    final_bill_patients  = [dict(r._mapping) for r in final_bill_rows]

    # Final bill overdue first, then reconciliation due, then estimate pending
    actions = (
        [_to_action(p, "final_bill") for p in final_bill_patients] +
        [_to_action(p, "discharge")  for p in discharge_patients]  +
        [_to_action(p, "admission")  for p in admission_patients]
    )

    # Phase 5 — post-discharge: billing_records in late phases
    with _get_engine().connect() as conn:
        p5_rows = conn.execute(_text("""
            SELECT br.hadm_id, br.billing_phase, br.balance_due,
                   br.insurance_co, br.payment_mode,
                   br.expected_est, br.actual_charges,
                   br.expected_los_days, br.hbp_rate, br.ward_type,
                   br.is_ab_beneficiary, br.ab_scheme,
                   ap.subject_id, ap.gender, ap.anchor_age,
                   ap.primary_diagnosis_title,
                   ap.admit_time, ap.discharge_time,
                   COALESCE((SELECT SUM(i.los) FROM ap_icustays i WHERE i.hadm_id = br.hadm_id), 0) AS icu_days,
                   COALESCE((SELECT COUNT(*) FROM ap_procedures p WHERE p.hadm_id = br.hadm_id), 0) AS proc_count
            FROM billing_records br
            JOIN active_patients ap ON ap.hadm_id = br.hadm_id
            WHERE br.billing_phase IN ('claim_submitted','tpa_settled','paid')
            ORDER BY br.updated_at DESC LIMIT 50
        """)).fetchall()

    def _p5_amounts(r):
        """Compute estimated and actual gross charges for a post-discharge patient."""
        from datetime import datetime as _dt5
        admit_dt5  = r.get("admit_time")
        disc_dt5   = r.get("discharge_time")
        actual_los5 = 7
        if admit_dt5 and disc_dt5:
            try:
                a5 = _dt5.fromisoformat(str(admit_dt5).replace("Z","")) if isinstance(admit_dt5,str) else admit_dt5
                d5 = _dt5.fromisoformat(str(disc_dt5).replace("Z",""))  if isinstance(disc_dt5, str) else disc_dt5
                actual_los5 = max(1, (d5 - a5).days)
            except Exception:
                pass
        # Expected LOS always less than actual (CE1 underestimates) — seeded offset
        exp_los5 = r.get("expected_los_days") or 0
        if not exp_los5 or exp_los5 >= actual_los5:
            import random as _r5
            rng5 = _r5.Random(r["hadm_id"])
            off5 = rng5.choice([-4, -3, -2])
            exp_los5 = max(1, actual_los5 + off5)
        hbp5       = r.get("hbp_rate") or 40600
        ward5      = WARD_DAILY_RATES.get(r.get("ward_type") or "Semi-private Ward", 4500)
        is_ab5     = bool(r.get("is_ab_beneficiary"))
        scheme5    = (r.get("ab_scheme") or "").upper()
        if is_ab5 and ("PM-JAY" in scheme5 or "PMJAY" in scheme5):
            smult5 = 1
        elif is_ab5 and "CGHS" in scheme5:
            smult5 = 4
        elif is_ab5 and "ESI" in scheme5:
            smult5 = 3.5
        else:
            smult5 = _PRIVATE_MULTIPLIER
        # CE1-style estimated complexity (based on expected LOS)
        extra_est5  = max(exp_los5 - 14, 0)
        est_comp5   = 1.0 + min(extra_est5, 86) / 86 * 0.28
        est_gross5  = round(hbp5 * smult5 * est_comp5 + exp_los5 * ward5)
        # CE4-style actual complexity (actual LOS + ICU/proc premiums → always higher)
        icu5        = float(r.get("icu_days") or 0)
        proc5       = int(r.get("proc_count") or 0)
        extra_act5  = max(actual_los5 - 14, 0)
        act_comp5   = (1.0 + min(extra_act5, 86) / 86 * 0.28
                       + min(icu5 / max(actual_los5, 1), 0.5) * 0.20
                       + min(proc5 / 5.0, 1.0) * 0.12)
        act_gross5  = round(hbp5 * smult5 * act_comp5 + actual_los5 * ward5)
        return (
            r.get("expected_est")   or est_gross5,
            r.get("actual_charges") or act_gross5,
        )

    phase5_rows_dicts = [dict(row._mapping) for row in p5_rows]
    phase5 = []
    for r in phase5_rows_dicts:
        est5, act5 = _p5_amounts(r)
        phase5.append({
            "hadm_id":        r["hadm_id"],
            "mrn":            f"PT-{r['hadm_id']}",
            "subject_id":     r["subject_id"],
            "gender":         r.get("gender", ""),
            "age":            r.get("anchor_age", ""),
            "admit_date":     _fmt(r.get("admit_time")),
            "diagnosis":      (r.get("primary_diagnosis_title") or "")[:60],
            "phase":          "post_discharge",
            "billing_phase":  r["billing_phase"],
            "billing_status": "Final Bill Overdue",
            "balance_due":    r.get("balance_due"),
            "expected_est":   est5,
            "actual_charges": act5,
            "insurance_co":   r.get("insurance_co", ""),
        })

    bills_settled_count = 0
    with _get_engine().connect() as conn:
        row = conn.execute(_text(
            "SELECT COUNT(*) FROM billing_records WHERE billing_phase = 'paid'"
        )).fetchone()
        if row:
            bills_settled_count = row[0]

    return {
        "stats": {
            "pending_estimates":       sum(1 for p in admission_patients if p.get("billing_phase") not in ("estimate_shared", "estimate_confirmed", "reconciliation_pending")),
            "awaiting_reconciliation": len(discharge_patients),
            "final_bills_pending":     len(final_bill_patients),
            "bills_settled":           bills_settled_count,
        },
        "pending_actions":   actions,
        "post_discharge":    phase5,
    }


# ── PM-JAY Package Reference Data ────────────────────────────────────────────
# Source: Assam AT-AL AMRITA BHIYAN PM-JAY Package Master + NHA HBP 2.2 costing framework
# Private hospital multiplier (×12) calibrated so MC011A × 12 ≈ ₹4.87L (matches prototype)

PMJAY_CARDIOLOGY = {
    "MC011A": {"name": "PTCA with Diagnostic Angiogram",            "rate": 40600, "template": "interventional"},
    "MC003A": {"name": "Balloon Dilatation – Coarctation of Aorta", "rate": 38600, "template": "interventional"},
    "MC007A": {"name": "ASD Device Closure",                         "rate": 36900, "template": "structural"},
    "MC005A": {"name": "Balloon Mitral Valvotomy",                   "rate": 35700, "template": "interventional"},
    "MC016A": {"name": "Double Chamber Permanent Pacemaker",         "rate": 33000, "template": "device"},
    "MC002A": {"name": "Catheter directed Thrombolysis – DVT",       "rate": 30800, "template": "interventional"},
    "MC017A": {"name": "Peripheral Angioplasty",                      "rate": 34500, "template": "interventional"},
    "MC020A": {"name": "Systemic Thrombolysis / Medical Management",  "rate": 17900, "template": "medical"},
}

ICD_TO_PMJAY = {
    # Coronary / ischaemic
    "I21": "MC011A", "I22": "MC011A", "I23": "MC011A", "I24": "MC011A", "I25": "MC011A",
    # Cardiomyopathy / heart failure
    "I42": "MC011A", "I43": "MC011A", "I50": "MC011A",
    # Arrhythmia / conduction
    "I44": "MC016A", "I45": "MC016A", "I46": "MC016A", "I47": "MC016A", "I48": "MC016A", "I49": "MC016A",
    # Valve disease
    "I05": "MC005A", "I06": "MC005A", "I07": "MC005A", "I08": "MC005A",  # Rheumatic valve
    "I34": "MC005A", "I36": "MC005A",                                      # Non-rheumatic mitral/tricuspid
    "I35": "MC007A", "I37": "MC007A",                                      # Aortic/pulmonary valve
    # Pericardial / myocarditis
    "I30": "MC020A", "I31": "MC020A", "I32": "MC020A", "I33": "MC020A", "I40": "MC020A", "I41": "MC020A",
    # Vascular / DVT / PE
    "I26": "MC002A", "I27": "MC002A", "I28": "MC002A",
    "I70": "MC017A", "I71": "MC017A", "I72": "MC017A", "I73": "MC017A", "I74": "MC017A",
    # Hypertension / other circulatory
    "I10": "MC020A", "I11": "MC020A", "I12": "MC020A", "I13": "MC020A", "I15": "MC020A",
    # Non-cardiac — default to medical management (MC020A)
    # Respiratory
    "J06": "MC020A", "J09": "MC020A", "J10": "MC020A", "J11": "MC020A", "J12": "MC020A",
    "J13": "MC020A", "J14": "MC020A", "J15": "MC020A", "J18": "MC020A",
    "J44": "MC020A", "J45": "MC020A", "J80": "MC020A", "J96": "MC020A",
    # Sepsis / infectious
    "A40": "MC020A", "A41": "MC020A", "B34": "MC020A",
    # Renal
    "N17": "MC020A", "N18": "MC020A", "N19": "MC020A",
    # GI
    "K25": "MC020A", "K26": "MC020A", "K70": "MC020A", "K72": "MC020A", "K92": "MC020A",
    # Neurological
    "G93": "MC020A",
    # Haematology
    "D62": "MC020A", "D65": "MC020A",
    # Musculoskeletal / rheumatic
    "M05": "MC020A", "M06": "MC020A", "M32": "MC020A",
}

WARD_DAILY_RATES = {
    "General Ward":     2500,
    "Semi-private Ward": 4500,
    "Private Room":     8000,
    "ICU":             15000,
}

# NHA HBP 2.2 costing framework — % of non-room budget per line item
_LINE_ITEM_TEMPLATES = {
    "interventional": [
        ("Cardiac Procedure / Surgery",   0.38),
        ("Medicines & Consumables",        0.24),
        ("Diagnostics & Investigations",   0.12),
        ("ICU / HDU Charges",              0.10),
        ("Nursing & Ward Services",        0.08),
        ("Specialist Consultation",        0.05),
        ("Physiotherapy & Rehab",          0.02),
        ("Miscellaneous",                  0.01),
    ],
    "structural": [
        ("Cardiac Procedure / Surgery",   0.38),
        ("Medicines & Consumables",        0.24),
        ("Diagnostics & Investigations",   0.12),
        ("ICU / HDU Charges",              0.10),
        ("Nursing & Ward Services",        0.08),
        ("Specialist Consultation",        0.05),
        ("Physiotherapy & Rehab",          0.02),
        ("Miscellaneous",                  0.01),
    ],
    "device": [
        ("Device / Implant Cost",          0.42),
        ("Procedure Charges",              0.20),
        ("Medicines & Consumables",        0.16),
        ("Diagnostics & Investigations",   0.10),
        ("ICU / HDU Charges",              0.06),
        ("Nursing & Ward Services",        0.04),
        ("Miscellaneous",                  0.02),
    ],
    "medical": [
        ("Medicines & Consumables",        0.34),
        ("Diagnostics & Investigations",   0.19),
        ("ICU / HDU Charges",              0.14),
        ("Nursing & Ward Services",        0.13),
        ("Specialist Consultation",        0.08),
        ("Procedures & Interventions",     0.06),
        ("Physiotherapy & Rehab",          0.04),
        ("Miscellaneous",                  0.02),
    ],
}

_PRIVATE_MULTIPLIER = 12

class GenerateEstimateRequest(BaseModel):
    hadm_id:           Optional[int] = None
    ward_type:         str  = "Semi-private Ward"
    los_days:          int  = 7
    hbp_code:          Optional[str]  = None
    icd_override:      Optional[str]  = None   # frontend dropdown selection
    is_ab_beneficiary: bool = False
    ab_scheme:         Optional[str]  = None
    patient_name:      Optional[str]  = None   # deterministic synthetic name from billing UI
    # Insurance fields — used to compute patient-facing liability in the estimate
    payment_mode:      Optional[str]  = None
    copay_pct:         Optional[float]= None
    room_rent_limit:   Optional[int]  = None
    preauth_amount:    Optional[int]  = None

@app.post("/api/billing/generate-estimate")
def generate_billing_estimate(req: GenerateEstimateRequest):
    import json as _json
    from sqlalchemy import text as _text
    from .cloud_sql_db import get_engine as _get_engine

    # 1. Resolve HBP code — priority: explicit hbp_code > icd_override > DB lookup
    hbp_code = req.hbp_code
    if not hbp_code:
        icd = (req.icd_override or "").strip()
        if not icd and req.hadm_id is not None:
            # Fall back to patient's actual diagnosis code from DB
            with _get_engine().connect() as conn:
                row = conn.execute(
                    _text("SELECT primary_diagnosis_code FROM active_patients WHERE hadm_id = :h"),
                    {"h": req.hadm_id}
                ).fetchone()
            icd = (row[0] or "").strip() if row else ""
        prefix = icd[:3].upper()
        if icd and icd[0].isdigit():
            # ICD-9-CM (numeric codes) — use medical management
            hbp_code = "MC020A"
        else:
            # ICD-10 — map prefix; default to PTCA for unmapped cardiac codes
            hbp_code = ICD_TO_PMJAY.get(prefix, "MC011A")

    pkg = PMJAY_CARDIOLOGY.get(hbp_code, PMJAY_CARDIOLOGY["MC011A"])

    # 2. Cost calculation
    actual_los  = req.los_days
    est_los     = min(actual_los, 14)          # estimate LOS capped at 14 days
    ward_rate   = WARD_DAILY_RATES.get(req.ward_type, 4500)

    # Complexity multiplier: actual LOS > 14 → higher-acuity patient → costlier clinical care
    extra_days  = max(actual_los - 14, 0)
    complexity  = 1.0 + min(extra_days, 86) / 86 * 0.28

    # Clinical base (procedures, medicines, diagnostics — EXCLUDING room)
    # Room is ADDITIVE on top so ward type changes the total, not just redistributes
    clinical    = round(pkg["rate"] * _PRIVATE_MULTIPLIER * complexity)
    room_cost   = est_los * ward_rate
    expected    = clinical + room_cost

    floor_est   = round(expected * 0.82)
    ceiling_est = round(expected * 1.28)

    # 3. Build line items — room first, then template % applied to clinical base
    template = _LINE_ITEM_TEMPLATES.get(pkg["template"], _LINE_ITEM_TEMPLATES["interventional"])
    room_label = f"Room Charges ({est_los}d × ₹{ward_rate:,})"
    line_items = [{"name": room_label, "amount": room_cost, "pct": round(room_cost / expected * 100, 1)}]
    for name, pct in template:
        amt = round(clinical * pct)
        line_items.append({"name": name, "amount": amt, "pct": round(amt / expected * 100, 1)})

    # ── Scheme / insurance liability ──────────────────────────────────────────
    govt_pays: Optional[int]  = None
    patient_pays_estimate: Optional[int] = None
    room_rent_excess_est   = 0
    scheme_note: Optional[str] = None

    scheme_str = (req.ab_scheme or "").upper()
    ward_rate_used = WARD_DAILY_RATES.get(req.ward_type, 4500)

    if req.is_ab_beneficiary and scheme_str:
        if "PM-JAY" in scheme_str or "PMJAY" in scheme_str:
            govt_pays             = pkg["rate"]
            patient_pays_estimate = 0
            scheme_note = (
                f"PM-JAY covers ₹{pkg['rate']:,} (HBP package rate {hbp_code}). "
                f"Patient liability: ₹0"
            )
        elif "CGHS" in scheme_str:
            cghs_clinical = round(pkg["rate"] * 4 * complexity)
            cghs_total    = cghs_clinical + room_cost
            govt_pays     = cghs_total
            # Patient pays ~15% of private rate (excess above CGHS ceiling + non-covered items)
            patient_pays_estimate = round(expected * 0.15)
            scheme_note = (
                f"CGHS rate applied (~4× PM-JAY). "
                f"CGHS covers ₹{cghs_total:,}. "
                f"Patient pays excess/non-covered items (~15% of private rate = ₹{patient_pays_estimate:,})"
            )
        elif "ESI" in scheme_str:
            esi_clinical = round(pkg["rate"] * 3.5 * complexity)
            esi_total    = esi_clinical + room_cost
            govt_pays    = esi_total
            patient_pays_estimate = 0
            scheme_note = (
                f"ESI covers full cost. "
                f"ESI reimburses ₹{esi_total:,}. "
                f"Patient liability: ₹0"
            )
        elif "HARYANA" in scheme_str:
            haryana_clinical = round(pkg["rate"] * 3 * complexity)
            haryana_total    = haryana_clinical + room_cost
            govt_pays        = haryana_total
            patient_pays_estimate = round(expected * 0.10)
            scheme_note = (
                f"Haryana Govt Scheme covers ₹{haryana_total:,}. "
                f"Patient pays ~10% of private rate = ₹{patient_pays_estimate:,}"
            )
        else:
            patient_pays_estimate = expected
    else:
        # Private — compute cashless insurance breakdown
        pay_mode = (req.payment_mode or "").lower()
        if pay_mode == "cashless" and req.copay_pct is not None:
            if req.room_rent_limit:
                room_rent_excess_est = max(0, (ward_rate_used - req.room_rent_limit) * est_los)
            copay_amount      = round(expected * req.copay_pct / 100)
            max_ins_cover     = expected - copay_amount
            insurance_covers  = min(max_ins_cover, req.preauth_amount) if req.preauth_amount else max_ins_cover
            patient_pays_estimate = expected - insurance_covers + room_rent_excess_est
        else:
            # Reimbursement / self-pay — patient pays full gross upfront
            patient_pays_estimate = expected

    # Provision patient into active_patients so they appear on Sabari's ward board.
    # Map billing ward_type → ward_location used by the ward board filter.
    _ward_loc  = "GENERAL_WARD" if req.ward_type == "General Ward" else "CCU"
    _ward_name = "General Ward" if _ward_loc == "GENERAL_WARD" else "Ward 4B"

    # Deterministic synthetic name — same first-name x surname seed as billing.html JS _bilName()
    def _synth_name(hadm_id: int) -> str:
        _FIRST_M = ['Rajesh','Mohan','Dinesh','Arun','Suresh','Vijay','Sanjay','Ramesh','Deepak','Nitin',
                    'Ashok','Prakash','Anil','Manoj','Rakesh','Vinod','Sunil','Ravi','Ajay','Amit']
        _FIRST_F = ['Priya','Kavita','Sunita','Anjali','Leela','Rekha','Suman','Anita','Meena','Geeta',
                    'Pooja','Neha','Divya','Shalini','Radha','Usha','Lata','Nisha','Swati','Kiran']
        _LAST = ['Kumar','Singh','Joshi','Verma','Patel','Malhotra','Gupta','Sharma','Rao','Jain',
                 'Iyer','Menon','Nair','Desai','Varma','Devi','Reddy','Chatterjee','Mehta','Kapoor',
                 'Choudhary','Pillai','Krishnan','Bose','Agarwal','Bhatia','Saxena','Trivedi','Bhosale','Kulkarni']

        def _to_i32(x) -> int:
            # Replicates JS ToInt32 (truncate, wrap to 32-bit signed) — needed because
            # the JS reference impl (seeded/_bilSeeded in the frontend) loses precision
            # through float multiplication at each step; matching bit-for-bit requires
            # doing the same float math here, not exact-integer Python math.
            xi = int(x) & 0xFFFFFFFF
            return xi - 0x100000000 if xi >= 0x80000000 else xi

        def _seed(n: int, mod: int) -> int:
            h = _to_i32(n)
            h = _to_i32((h >> 16) ^ h)
            h = float(h) * 0x45d9f3b
            h = _to_i32(h)
            h = _to_i32((h >> 16) ^ h)
            h = float(h) * 0x45d9f3b
            h = _to_i32(h)
            h = _to_i32((h >> 16) ^ h)
            return abs(h) % mod

        hid     = int(hadm_id)
        is_male = _seed(hid, 2) == 0
        first   = _FIRST_M[_seed(hid, len(_FIRST_M))] if is_male else _FIRST_F[_seed(hid * 31 + 7, len(_FIRST_F))]
        last    = _LAST[_seed(hid * 31 + 17, len(_LAST))]
        return f"{first} {last}"

    ward_admitted = False
    if req.hadm_id is not None:
        try:
            with _get_engine().begin() as _conn:
                # data_fetch_status='pending': BQ hasn't run yet — ward board shows "Data Loading"
                # until billing.html's prefetch-all call completes and sets it to 'fetched'.
                _conn.execute(_text("""
                    INSERT INTO active_patients (hadm_id, subject_id, status, ward_location, ward,
                                                 data_fetch_status, primary_diagnosis_title,
                                                 patient_name, admit_time)
                    VALUES (:h, :h, 'active', :wloc, :wname, 'pending', :diag, :pname, NOW())
                    ON CONFLICT (hadm_id) DO UPDATE
                        SET status = CASE WHEN active_patients.status IN ('signed_off','archived')
                                          THEN 'active'
                                          ELSE active_patients.status END,
                            ward_location = EXCLUDED.ward_location,
                            ward          = EXCLUDED.ward,
                            data_fetch_status = CASE
                                WHEN active_patients.data_fetch_status IN ('fetched','fetching','partial')
                                THEN active_patients.data_fetch_status
                                ELSE 'pending' END,
                            patient_name = COALESCE(active_patients.patient_name, EXCLUDED.patient_name),
                            primary_diagnosis_title = COALESCE(active_patients.primary_diagnosis_title, EXCLUDED.primary_diagnosis_title),
                            updated_at = NOW()
                """), {"h": req.hadm_id, "diag": pkg["name"], "wloc": _ward_loc, "wname": _ward_name,
                       "pname": req.patient_name or _synth_name(req.hadm_id)})
            ward_admitted = True
            # Also ensure app_encounters row exists so billing dashboard shows patient
            try:
                if not gdb.get_encounter_by_hadm(req.hadm_id):
                    gdb.create_encounter(req.hadm_id, status="Pending Ingestion")
            except Exception as _ee:
                log.warning("billing→encounter auto-create failed for hadm %s: %s", req.hadm_id, _ee)
        except Exception as _wp:
            log.warning("billing→ward provision failed for hadm %s: %s", req.hadm_id, _wp)

    return {
        "hbp_code":             hbp_code,
        "hbp_package_name":     pkg["name"],
        "hbp_rate":             pkg["rate"],
        "ward_type":            req.ward_type,
        "los_days":             est_los,
        "actual_los_days":      actual_los,
        "complexity":           round(complexity, 3),
        "floor_est":            floor_est,
        "expected_est":         expected,
        "ceiling_est":          ceiling_est,
        "line_items":           line_items,
        "pmjay_reference":      f"NHA HBP 2.2 · {hbp_code} · PM-JAY rate ₹{pkg['rate']:,} · Private ×{_PRIVATE_MULTIPLIER}" + (f" · complexity ×{round(complexity,2)}" if complexity > 1.0 else ""),
        # Scheme / insurance breakdown
        "govt_pays":            govt_pays,
        "patient_pays_estimate":patient_pays_estimate,
        "room_rent_excess":     room_rent_excess_est,
        "scheme_note":          scheme_note,
        "ward_admitted":        ward_admitted,
    }


# ── Billing Records CRUD ──────────────────────────────────────────────────────

class BillingRecordUpsert(BaseModel):
    encounter_id:       Optional[str]  = None
    payment_mode:       Optional[str]  = None
    insurance_co:       Optional[str]  = None
    policy_number:      Optional[str]  = None
    preauth_number:     Optional[str]  = None
    preauth_amount:     Optional[int]  = None
    copay_pct:          Optional[float]= None
    room_rent_limit:    Optional[int]  = None
    selected_band:      Optional[str]  = None
    floor_est:          Optional[int]  = None
    expected_est:       Optional[int]  = None
    ceiling_est:        Optional[int]  = None
    actual_charges:     Optional[int]  = None
    insurance_paid:     Optional[int]  = None
    advance_paid:       Optional[int]  = None
    balance_due:        Optional[int]  = None
    payment_ref:        Optional[str]  = None
    payment_mode_final: Optional[str]  = None
    billing_phase:      Optional[str]  = None
    # PM-JAY estimate fields (migration 015)
    hbp_code:           Optional[str]  = None
    hbp_package_name:   Optional[str]  = None
    hbp_rate:           Optional[int]  = None
    ward_type:          Optional[str]  = None
    is_ab_beneficiary:  Optional[bool] = None
    ab_scheme:          Optional[str]  = None
    line_items:         Optional[Any]  = None  # list of {name, amount, pct}
    # CE4 reconciliation fields (migration 016)
    actual_line_items:      Optional[Any] = None  # list of {name, amount} — entered by billing staff
    reconciliation_notes:   Optional[str] = None
    # Migration 017 — expected discharge, scheme/insurance breakdown
    expected_discharge_date: Optional[str]  = None
    expected_los_days:       Optional[int]  = None
    actual_los_days:         Optional[int]  = None
    patient_pays_estimate:   Optional[int]  = None
    govt_pays:               Optional[int]  = None
    room_rent_excess:        Optional[int]  = None
    scheme_note:             Optional[str]  = None

@app.get("/api/billing/records/{hadm_id}")
def get_billing_record(hadm_id: int):
    from sqlalchemy import text as _text
    from .cloud_sql_db import get_engine as _get_engine
    with _get_engine().connect() as conn:
        row = conn.execute(
            _text("SELECT * FROM billing_records WHERE hadm_id = :h"),
            {"h": hadm_id}
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No billing record for this patient")
    return dict(row._mapping)

@app.get("/api/billing/live-charges/{hadm_id}")
def get_live_charges(hadm_id: int):
    """Live bill tracker — uses real MIMIC meds/procedures/labs when available, synthetic fallback otherwise."""
    import json as _json, random as _random
    from datetime import datetime as _dt, timedelta as _td
    from sqlalchemy import text as _text
    from .cloud_sql_db import get_engine as _get_engine

    _rng = _random.Random(hadm_id)

    with _get_engine().connect() as conn:
        br = conn.execute(_text(
            "SELECT billing_phase, expected_est AS total_estimate, line_items FROM billing_records WHERE hadm_id = :h"
        ), {"h": hadm_id}).fetchone()
        pt = conn.execute(_text(
            "SELECT patient_name, anchor_age, gender, admit_time, primary_diagnosis_title FROM active_patients WHERE hadm_id = :h"
        ), {"h": hadm_id}).fetchone()

        # Real MIMIC data for this patient
        meds = conn.execute(_text(
            "SELECT drug, starttime, dose_val_rx, dose_unit_rx, route FROM ap_prescriptions"
            " WHERE hadm_id = :h AND drug IS NOT NULL ORDER BY starttime LIMIT 80"
        ), {"h": hadm_id}).fetchall()
        procs = conn.execute(_text(
            "SELECT long_title, chartdate FROM ap_procedures"
            " WHERE hadm_id = :h AND long_title IS NOT NULL ORDER BY chartdate LIMIT 30"
        ), {"h": hadm_id}).fetchall()
        labs = conn.execute(_text(
            "SELECT charttime FROM ap_labevents"
            " WHERE hadm_id = :h AND charttime IS NOT NULL ORDER BY charttime LIMIT 50"
        ), {"h": hadm_id}).fetchall()

    br_data = dict(br._mapping) if br else {}
    try:
        line_items = _json.loads(br_data["line_items"]) if br_data.get("line_items") else []
    except Exception:
        line_items = []

    estimate_total = br_data.get("total_estimate") or 0

    # Admission start time
    admit_base = _dt.now() - _td(days=3)
    if pt and pt[3]:
        try:
            admit_base = _dt.fromisoformat(str(pt[3])[:19])
        except Exception:
            pass

    charges = []
    has_real_data = bool(meds or procs or labs)

    if has_real_data:
        # ── Use real MIMIC data ────────────────────────────────────────────
        _LAB_NAMES = [
            "CBC + Differential", "Serum Electrolytes", "Liver Function Test",
            "Renal Function Test", "Coagulation Profile", "Serum Troponin I",
            "Blood Culture", "ABG Analysis", "Urine Culture", "ECG 12-Lead",
            "Chest X-Ray PA View", "2D Echocardiogram", "CT Scan with Contrast",
            "Serum Lactate", "Lipid Profile", "HbA1c", "Thyroid Function Test",
        ]

        for m in meds:
            drug = (m[0] or "Medication").title()
            cost = _rng.randint(180, 2800)
            try:
                t = _dt.fromisoformat(str(m[1])[:19])
            except Exception:
                t = admit_base + _td(hours=_rng.randint(1, 72))
            detail_parts = []
            if m[2]: detail_parts.append(f"{m[2]} {(m[3] or '').strip()}")
            if m[4]: detail_parts.append(m[4])
            charges.append({
                "type":     "medication",
                "name":     drug,
                "detail":   " · ".join(detail_parts) if detail_parts else "Medication",
                "time":     t.strftime("%Y-%m-%d %H:%M"),
                "cost":     cost,
                "category": "Medications",
            })

        for p in procs:
            title = (p[0] or "Procedure")[:70]
            cost = _rng.randint(4000, 28000)
            try:
                t = _dt.fromisoformat(str(p[1])[:10]) + _td(hours=_rng.randint(7, 20), minutes=_rng.randint(0, 59))
            except Exception:
                t = admit_base + _td(hours=_rng.randint(6, 72))
            charges.append({
                "type":     "procedure",
                "name":     title,
                "detail":   "Procedure",
                "time":     t.strftime("%Y-%m-%d %H:%M"),
                "cost":     cost,
                "category": "Procedures",
            })

        for i, lab in enumerate(labs):
            cost = _rng.randint(350, 4000)
            try:
                t = _dt.fromisoformat(str(lab[0])[:19])
            except Exception:
                t = admit_base + _td(hours=_rng.randint(1, 72))
            charges.append({
                "type":     "procedure",
                "name":     _LAB_NAMES[i % len(_LAB_NAMES)],
                "detail":   "Investigation",
                "time":     t.strftime("%Y-%m-%d %H:%M"),
                "cost":     cost,
                "category": "Investigations",
            })

    else:
        # ── Synthetic fallback from estimate line_items ────────────────────
        if not line_items and estimate_total > 0:
            est = estimate_total
            line_items = [
                {"name": "Room & Nursing",    "amount": round(est * 0.28)},
                {"name": "Medications",       "amount": round(est * 0.22)},
                {"name": "Investigations",    "amount": round(est * 0.18)},
                {"name": "Procedures",        "amount": round(est * 0.14)},
                {"name": "Consumables",       "amount": round(est * 0.10)},
                {"name": "ICU / HDU Charges", "amount": round(est * 0.08)},
            ]
        _MED_POOLS = {
            "Consumables":       ["IV Cannula 18G", "Syringe 5ml", "IV Set", "Sterile Gloves", "Wound Dressing", "Foley Catheter"],
            "Investigations":    ["CBC + Differential", "Serum Electrolytes", "Liver Function Test", "Renal Function Test", "Serum Troponin I", "Blood Culture", "ABG Analysis", "ECG 12-Lead", "Chest X-Ray PA View", "2D Echocardiogram"],
            "Procedures":        ["Central Line Insertion", "Arterial Line Placement", "Endotracheal Intubation", "Pleural Tap", "Cardiac Monitoring Setup"],
            "Medications":       ["Furosemide 40mg IV", "Metoprolol 25mg PO", "Heparin Infusion 25000U", "Amiodarone 200mg IV", "Aspirin 75mg PO", "Atorvastatin 40mg PO", "Pantoprazole 40mg IV", "Paracetamol 500mg PO"],
        }
        cursor = admit_base
        for item in line_items:
            name = item.get("name", "Service")
            amt  = item.get("amount", 0)
            if not amt:
                continue
            pool = _MED_POOLS.get(name, [])
            n_events = min(8, max(1, amt // 3000))
            unit_cost = amt // n_events
            for _ in range(n_events):
                cursor = cursor + _td(hours=_rng.randint(1, 18), minutes=_rng.randint(0, 59))
                sub_name = _rng.choice(pool) if pool else name
                charges.append({
                    "type":     "procedure" if name in ("Investigations", "Procedures", "Surgery") else "medication",
                    "name":     sub_name,
                    "detail":   name,
                    "time":     cursor.strftime("%Y-%m-%d %H:%M"),
                    "cost":     unit_cost + _rng.randint(-200, 200) if unit_cost > 300 else unit_cost,
                    "category": name,
                })

    charges.sort(key=lambda x: x["time"])
    running = 0
    for c in charges:
        running += c["cost"]
        c["running_total"] = running

    return {
        "hadm_id":             hadm_id,
        "patient_name":        (pt[0] if pt else None),
        "anchor_age":          (pt[1] if pt else None),
        "gender":              (pt[2] if pt else None),
        "admit_time":          (str(pt[3])[:10] if pt and pt[3] else None),
        "diagnosis":           (pt[4] if pt else None),
        "billing_phase":       br_data.get("billing_phase"),
        "estimate_total":      estimate_total,
        "estimate_line_items": line_items,
        "charges":             charges,
        "total_charged":       running,
    }


@app.post("/api/billing/records/{hadm_id}")
def upsert_billing_record(hadm_id: int, req: BillingRecordUpsert):
    import json as _json
    from sqlalchemy import text as _text
    from .cloud_sql_db import get_engine as _get_engine
    data = {k: v for k, v in req.dict().items() if v is not None}
    if "line_items" in data and isinstance(data["line_items"], (list, dict)):
        data["line_items"] = _json.dumps(data["line_items"])
    # CE4 actual line items — auto-compute actual_charges and variance_pct
    if "actual_line_items" in data and isinstance(data["actual_line_items"], list):
        act_items = data["actual_line_items"]
        actual_total = sum(int(item.get("amount", 0)) for item in act_items)
        if "actual_charges" not in data:
            data["actual_charges"] = actual_total
        # Compute variance_pct against whichever estimate band was selected
        with _get_engine().connect() as _vc:
            _br = _vc.execute(_text(
                "SELECT selected_band, floor_est, expected_est, ceiling_est FROM billing_records WHERE hadm_id = :h"
            ), {"h": hadm_id}).fetchone()
        if _br:
            _band = _br[0] or "expected"
            _est = {"floor": _br[1], "expected": _br[2], "ceiling": _br[3]}.get(_band) or _br[2] or 0
            if _est and _est > 0:
                data["variance_pct"] = round((actual_total - _est) / _est * 100, 2)
        data["actual_line_items"] = _json.dumps(act_items)
    data["hadm_id"] = hadm_id
    with _get_engine().begin() as conn:
        existing = conn.execute(
            _text("SELECT id FROM billing_records WHERE hadm_id = :h"), {"h": hadm_id}
        ).fetchone()
        if existing:
            if data:
                set_parts = [f"{k} = :{k}" for k in data if k != "hadm_id"]
                conn.execute(
                    _text(f"UPDATE billing_records SET {', '.join(set_parts)}, updated_at = NOW() WHERE hadm_id = :hadm_id"),
                    data
                )
        else:
            cols = ", ".join(data.keys())
            vals = ", ".join(f":{k}" for k in data.keys())
            conn.execute(_text(f"INSERT INTO billing_records ({cols}) VALUES ({vals})"), data)
        row = conn.execute(
            _text("SELECT * FROM billing_records WHERE hadm_id = :h"), {"h": hadm_id}
        ).fetchone()
    # Ensure app_encounters row exists so billing dashboard JOIN finds this patient
    try:
        existing_enc = gdb.get_encounter_by_hadm(hadm_id)
        if not existing_enc:
            gdb.create_encounter(hadm_id, status="Pending Ingestion")
    except Exception as _ee:
        log.warning("billing upsert — encounter auto-create failed for %s: %s", hadm_id, _ee)
    return dict(row._mapping)

@app.get("/api/billing/patient/{hadm_id}")
def get_billing_patient(hadm_id: int):
    """Patient details for CE1 pre-fill — active_patients + encounter + billing_record."""
    import random as _random
    from datetime import timedelta as _td, date as _date, datetime as _dt
    from sqlalchemy import text as _text
    from .cloud_sql_db import get_engine as _get_engine
    with _get_engine().connect() as conn:
        row = conn.execute(_text("""
            SELECT ap.hadm_id, ap.subject_id, ap.gender, ap.anchor_age,
                   ap.admit_time, ap.discharge_time, ap.los_days,
                   ap.primary_diagnosis_title, ap.primary_diagnosis_code,
                   ae.id AS encounter_id, ae.status AS enc_status,
                   ae.discharge_type,
                   br.id AS billing_id, br.billing_phase,
                   br.payment_mode, br.insurance_co, br.policy_number,
                   br.preauth_number, br.preauth_amount, br.copay_pct,
                   br.room_rent_limit, br.selected_band,
                   br.floor_est, br.expected_est, br.ceiling_est,
                   br.actual_charges, br.insurance_paid, br.advance_paid, br.balance_due,
                   br.expected_discharge_date, br.expected_los_days
            FROM active_patients ap
            LEFT JOIN app_encounters   ae ON ae.hadm_id = ap.hadm_id
            LEFT JOIN billing_records  br ON br.hadm_id = ap.hadm_id
            WHERE ap.hadm_id = :h
        """), {"h": hadm_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Patient not found")
        # Primary procedure — prefer ICD-9 (version=9), fall back to any
        proc_row = conn.execute(_text("""
            SELECT icd_code, icd_version, long_title
            FROM ap_procedures
            WHERE hadm_id = :h
            ORDER BY seq_num ASC, CASE WHEN icd_version = 9 THEN 0 ELSE 1 END ASC
            LIMIT 1
        """), {"h": hadm_id}).fetchone()

    result = dict(row._mapping)

    # Use previously saved expected_discharge if available, otherwise compute
    saved_expected = result.get("expected_discharge_date")
    if saved_expected:
        expected_discharge = str(saved_expected)[:10]
        expected_los = result.get("expected_los_days")
    else:
        actual_discharge = result.get("discharge_time")
        expected_discharge = None
        expected_los = None
        if actual_discharge:
            rng = _random.Random(hadm_id)
            offset = rng.choice([-4, -3, -2])  # CE1 underestimates LOS by 2-4 days
            if isinstance(actual_discharge, str):
                actual_dt = _dt.fromisoformat(actual_discharge.replace("Z", ""))
            else:
                actual_dt = actual_discharge
            expected_dt = actual_dt + _td(days=offset)
            expected_discharge = expected_dt.date().isoformat()
            admit_time = result.get("admit_time")
            if admit_time:
                admit_date = (
                    _dt.fromisoformat(admit_time.replace("Z", "")).date()
                    if isinstance(admit_time, str) else
                    admit_time.date() if hasattr(admit_time, "date") else admit_time
                )
                exp_date = _date.fromisoformat(expected_discharge)
                expected_los = max(1, (exp_date - admit_date).days)

    result["expected_discharge"] = expected_discharge
    result["expected_los"] = expected_los
    result["primary_procedure_icd"] = proc_row[0] if proc_row else None
    result["primary_procedure_version"] = proc_row[1] if proc_row else None
    result["primary_procedure_title"] = proc_row[2] if proc_row else None

    return result


@app.get("/api/billing/reconciliation/{hadm_id}")
def get_billing_reconciliation(hadm_id: int):
    """CE4 data: discharge summary info + estimated line items + any saved actuals."""
    import json as _json
    from sqlalchemy import text as _text
    from .cloud_sql_db import get_engine as _get_engine

    with _get_engine().connect() as conn:
        row = conn.execute(_text("""
            SELECT
                ap.hadm_id, ap.anchor_age, ap.gender,
                ap.admit_time, ap.discharge_time, ap.los_days,
                ap.primary_diagnosis_title, ap.primary_diagnosis_code,
                ae.id        AS encounter_id,
                ae.status    AS enc_status,
                br.billing_phase,
                br.selected_band,
                br.floor_est, br.expected_est, br.ceiling_est,
                br.hbp_code, br.hbp_package_name, br.hbp_rate,
                br.ward_type, br.is_ab_beneficiary, br.ab_scheme,
                br.line_items,
                br.actual_line_items,
                br.actual_charges,
                br.variance_pct,
                br.reconciliation_notes,
                br.insurance_paid,
                br.advance_paid,
                br.balance_due,
                br.expected_discharge_date,
                br.expected_los_days,
                br.insurance_co, br.payment_mode, br.copay_pct, br.room_rent_limit, br.preauth_amount,
                asumm.sections_json,
                asumm.signed_at,
                au.full_name AS signed_by_name
            FROM active_patients ap
            JOIN  app_encounters  ae    ON ae.hadm_id    = ap.hadm_id
            LEFT JOIN billing_records  br    ON br.hadm_id    = ap.hadm_id
            LEFT JOIN app_summaries    asumm ON asumm.encounter_id = ae.id
            LEFT JOIN app_users        au    ON au.id           = asumm.signed_by
            WHERE ap.hadm_id = :h
        """), {"h": hadm_id}).fetchone()
        # ICU days and procedure count for actual complexity calculation
        icu_row = conn.execute(_text(
            "SELECT COALESCE(SUM(los), 0) FROM ap_icustays WHERE hadm_id = :h"
        ), {"h": hadm_id}).fetchone()
        proc_count_row = conn.execute(_text(
            "SELECT COUNT(*) FROM ap_procedures WHERE hadm_id = :h"
        ), {"h": hadm_id}).fetchone()
        # Primary procedure for display (ICD-9 preferred)
        proc_row = conn.execute(_text("""
            SELECT icd_code, icd_version, long_title
            FROM ap_procedures WHERE hadm_id = :h
            ORDER BY seq_num ASC, CASE WHEN icd_version = 9 THEN 0 ELSE 1 END ASC
            LIMIT 1
        """), {"h": hadm_id}).fetchone()
        # Prescriptions fallback for discharge medications
        rx_rows = conn.execute(_text("""
            SELECT drug, dose_val_rx, dose_unit_rx, route
            FROM ap_prescriptions
            WHERE hadm_id = :h AND drug IS NOT NULL AND drug != ''
            ORDER BY stoptime DESC NULLS LAST LIMIT 10
        """), {"h": hadm_id}).fetchall()

    if not row:
        raise HTTPException(status_code=404, detail="Patient not found")

    r = dict(row._mapping)

    def _parse_json_col(v):
        if v is None:
            return None
        if isinstance(v, (list, dict)):
            return v
        try:
            return _json.loads(v)
        except Exception:
            return None

    sections      = _parse_json_col(r.get("sections_json")) or {}
    line_items    = _parse_json_col(r.get("line_items"))    or []
    actual_items  = _parse_json_col(r.get("actual_line_items"))

    def _sec_text(key):
        v = sections.get(key)
        if v is None:
            return ""
        if isinstance(v, dict):
            return v.get("text", "") or ""
        return str(v)

    def _fmt_date(dt):
        if not dt:
            return None
        try:
            from datetime import datetime as _dt
            d = _dt.fromisoformat(str(dt).replace("Z", "")) if isinstance(dt, str) else dt
            return d.strftime("%d %b %Y")
        except Exception:
            return str(dt)[:10]

    def _fmt_datetime(dt):
        if not dt:
            return None
        try:
            from datetime import datetime as _dt
            d = _dt.fromisoformat(str(dt).replace("Z", "")) if isinstance(dt, str) else dt
            return d.strftime("%d %b %Y, %H:%M")
        except Exception:
            return str(dt)[:16]

    icu_days    = float(icu_row[0]) if icu_row else 0.0
    proc_count  = int(proc_count_row[0]) if proc_count_row else 0

    # Compute actual LOS from real admit/discharge timestamps
    admit_dt = r.get("admit_time")
    disc_dt  = r.get("discharge_time")
    actual_los = r.get("los_days") or 0
    if admit_dt and disc_dt:
        try:
            from datetime import datetime as _dt
            a = _dt.fromisoformat(str(admit_dt).replace("Z", "")) if isinstance(admit_dt, str) else admit_dt
            d = _dt.fromisoformat(str(disc_dt).replace("Z", ""))  if isinstance(disc_dt, str)  else disc_dt
            actual_los = max(1, (d - a).days)
        except Exception:
            pass

    # Expected LOS — from saved billing record (set at CE1 time)
    expected_los_days = r.get("expected_los_days")
    if not expected_los_days:
        # CE1 was never run — recompute the same seeded offset get_billing_patient would have used
        import random as _random
        from datetime import timedelta as _td2, datetime as _dt2
        if admit_dt and disc_dt:
            try:
                rng = _random.Random(hadm_id)
                offset = rng.choice([-4, -3, -2])  # CE1 underestimates LOS by 2-4 days
                a_ref = _dt2.fromisoformat(str(admit_dt).replace("Z", "")) if isinstance(admit_dt, str) else admit_dt
                d_ref = _dt2.fromisoformat(str(disc_dt).replace("Z", ""))  if isinstance(disc_dt, str)  else disc_dt
                exp_ref = d_ref + _td2(days=offset)
                expected_los_days = max(1, (exp_ref.date() - a_ref.date()).days)
            except Exception:
                expected_los_days = actual_los
        else:
            expected_los_days = actual_los
    # If a saved expected_los is >= actual (CE1 overestimated), clamp so actual always > estimated
    if expected_los_days >= actual_los:
        import random as _random2
        rng2 = _random2.Random(hadm_id)
        off2 = rng2.choice([-7, -6, -5, -4, -3])
        expected_los_days = max(1, actual_los + off2)
    los_diff = actual_los - expected_los_days

    # Billing params
    _no_ce1       = not r.get("hbp_code") or not (r.get("expected_est") or 0)
    ward_type_val = r.get("ward_type") or "Semi-private Ward"
    ward_rate_val = WARD_DAILY_RATES.get(ward_type_val, 4500)
    is_ab_val     = bool(r.get("is_ab_beneficiary"))
    ab_scheme_raw = r.get("ab_scheme") or ""
    ab_scheme_val = ab_scheme_raw.upper()
    # Determine if the scheme is one we actually implement (no silent defaults)
    _known_ab = (
        "PM-JAY" in ab_scheme_val or "PMJAY" in ab_scheme_val or
        "CGHS"   in ab_scheme_val or
        "ESI"    in ab_scheme_val or
        "HARYANA" in ab_scheme_val
    )
    is_known_ab = is_ab_val and _known_ab

    if is_known_ab and ("PM-JAY" in ab_scheme_val or "PMJAY" in ab_scheme_val):
        _scheme_mult = 1
    elif is_known_ab and "CGHS" in ab_scheme_val:
        _scheme_mult = 4
    elif is_known_ab and "ESI" in ab_scheme_val:
        _scheme_mult = 3.5
    elif is_known_ab and "HARYANA" in ab_scheme_val:
        _scheme_mult = 3
    else:
        _scheme_mult = _PRIVATE_MULTIPLIER

    if _no_ce1:
        # CE1 was never run — derive HBP code from the patient's actual diagnosis
        _diag        = (r.get("primary_diagnosis_code") or "").strip()
        _prefix      = _diag[:3].upper()
        hbp_code_val = ("MC020A" if (_diag and _diag[0].isdigit())
                        else ICD_TO_PMJAY.get(_prefix, "MC020A"))
        _pkg_recon   = PMJAY_CARDIOLOGY.get(hbp_code_val, PMJAY_CARDIOLOGY["MC020A"])
        hbp_rate_val = _pkg_recon["rate"]
    else:
        hbp_code_val = r.get("hbp_code")
        _pkg_recon   = PMJAY_CARDIOLOGY.get(hbp_code_val, PMJAY_CARDIOLOGY["MC011A"])
        hbp_rate_val = r.get("hbp_rate") or _pkg_recon["rate"]

    _tmpl_recon = _LINE_ITEM_TEMPLATES.get(_pkg_recon["template"], _LINE_ITEM_TEMPLATES["interventional"])

    # ── CE1-style estimated total ──────────────────────────────────────────────
    extra_days_est = max(expected_los_days - 14, 0)
    est_complexity = 1.0 + min(extra_days_est, 86) / 86 * 0.28
    est_clinical   = round(hbp_rate_val * _scheme_mult * est_complexity)
    est_room_ce1   = expected_los_days * ward_rate_val
    est_gross_ce1  = est_clinical + est_room_ce1
    est_room_label_ce1 = f"Room Charges ({expected_los_days}d × ₹{ward_rate_val:,})"
    computed_estimate_items = [
        {"name": est_room_label_ce1, "amount": est_room_ce1, "pct": round(est_room_ce1 / est_gross_ce1 * 100, 1)}
    ]
    for _name, _pct in _tmpl_recon:
        _amt_est = round(est_clinical * _pct)
        computed_estimate_items.append({"name": _name, "amount": _amt_est, "pct": round(_amt_est / est_gross_ce1 * 100, 1)})

    # ── Auto-save estimate to billing_records if CE1 was never run ────────────
    if _no_ce1:
        _floor_auto   = round(est_gross_ce1 * 0.82)
        _ceiling_auto = round(est_gross_ce1 * 1.28)
        try:
            with _get_engine().begin() as _conn:
                _conn.execute(_text("""
                    INSERT INTO billing_records (
                        hadm_id, billing_phase,
                        hbp_code, hbp_package_name, hbp_rate,
                        ward_type, selected_band,
                        expected_est, floor_est, ceiling_est,
                        expected_los_days
                    ) VALUES (
                        :h, 'reconciliation',
                        :code, :name, :rate,
                        :ward, 'expected',
                        :exp, :floor, :ceil, :los
                    )
                    ON CONFLICT (hadm_id) DO UPDATE SET
                        hbp_code         = COALESCE(billing_records.hbp_code,          EXCLUDED.hbp_code),
                        hbp_package_name = COALESCE(billing_records.hbp_package_name,  EXCLUDED.hbp_package_name),
                        hbp_rate         = COALESCE(billing_records.hbp_rate,           EXCLUDED.hbp_rate),
                        ward_type        = COALESCE(billing_records.ward_type,          EXCLUDED.ward_type),
                        expected_est     = COALESCE(NULLIF(billing_records.expected_est, 0), EXCLUDED.expected_est),
                        floor_est        = COALESCE(NULLIF(billing_records.floor_est,    0), EXCLUDED.floor_est),
                        ceiling_est      = COALESCE(NULLIF(billing_records.ceiling_est,  0), EXCLUDED.ceiling_est),
                        expected_los_days= COALESCE(billing_records.expected_los_days,  EXCLUDED.expected_los_days)
                """), {
                    "h": hadm_id, "code": hbp_code_val,
                    "name": _pkg_recon["name"], "rate": hbp_rate_val,
                    "ward": ward_type_val,
                    "exp": est_gross_ce1, "floor": _floor_auto, "ceil": _ceiling_auto,
                    "los": expected_los_days,
                })
            log.info(f"CE4 auto-generated estimate for hadm {hadm_id}: {hbp_code_val} ₹{est_gross_ce1:,}")
        except Exception as _ae:
            log.warning(f"CE4 auto-estimate save failed for hadm {hadm_id}: {_ae}")

    # ── CE4 actual total: seeded 6–16 % over the ORIGINAL CE1 estimate ────────
    # Use saved expected_est (what billing staff actually generated at CE1).
    # This ensures actual is always 6-16% above what was quoted to the patient,
    # regardless of scheme/multiplier differences between CE1 and CE4 time.
    import random as _vrng_mod
    _vrng_inst    = _vrng_mod.Random(hadm_id * 17 + 3)
    _variance_pct = _vrng_inst.uniform(0.06, 0.16)
    _saved_ce1    = r.get("expected_est") or 0
    _base_for_actual = _saved_ce1 if _saved_ce1 > 0 else est_gross_ce1
    actual_gross  = round(_base_for_actual * (1 + _variance_pct))
    actual_room   = actual_los * ward_rate_val
    # Clinical pool = actual_gross minus room; clamp so room never exceeds gross
    actual_clinical_pool = max(actual_gross - actual_room, round(actual_gross * 0.30))
    actual_room_label = f"Room Charges ({actual_los}d × ₹{ward_rate_val:,})"
    computed_actual_items = [
        {"name": actual_room_label, "amount": actual_room, "pct": round(actual_room / actual_gross * 100, 1)}
    ]
    for _name, _pct in _tmpl_recon:
        _amt = round(actual_clinical_pool * _pct)
        computed_actual_items.append({"name": _name, "amount": _amt, "pct": round(_amt / actual_gross * 100, 1)})

    # Scheme-aware final patient payment on actual charges
    pay_mode_recon  = (r.get("payment_mode") or "").lower()
    ins_co_recon    = r.get("insurance_co") or ""
    copay_pct_recon = r.get("copay_pct") or 0
    rrlt_recon      = r.get("room_rent_limit") or 0
    preauth_recon   = r.get("preauth_amount") or 0

    if is_known_ab and ("PM-JAY" in ab_scheme_val or "PMJAY" in ab_scheme_val):
        patient_final     = 0
        govt_final        = hbp_rate_val
        hospital_writeoff = max(0, actual_gross - hbp_rate_val)
        scheme_summary    = f"PM-JAY package rate ₹{hbp_rate_val:,} — Patient pays ₹0. Hospital write-off: ₹{hospital_writeoff:,}"
    elif is_known_ab and "CGHS" in ab_scheme_val:
        cghs_covers   = round(actual_gross * 0.85)
        patient_final = round(actual_gross * 0.15)
        govt_final    = cghs_covers
        scheme_summary = f"CGHS covers ₹{cghs_covers:,}. Patient pays ~15% (excess + non-covered) = ₹{patient_final:,}"
    elif is_known_ab and "ESI" in ab_scheme_val:
        patient_final  = 0
        govt_final     = actual_gross
        scheme_summary = f"ESI reimburses ₹{actual_gross:,}. Patient pays ₹0"
    elif is_known_ab and "HARYANA" in ab_scheme_val:
        _state_rate    = hbp_rate_val or actual_gross
        patient_final  = 0
        govt_final     = _state_rate
        scheme_summary = f"Haryana State Scheme covers ₹{_state_rate:,}. Patient pays ₹0"
    elif pay_mode_recon == "cashless":
        copay_pct_eff  = copay_pct_recon or 10   # default 10% copay if not set at CE1
        rr_excess      = max(0, (ward_rate_val - rrlt_recon) * actual_los) if rrlt_recon else 0
        copay_amt      = round(actual_gross * copay_pct_eff / 100)
        ins_covers     = min(actual_gross - copay_amt, preauth_recon) if preauth_recon else (actual_gross - copay_amt)
        patient_final  = copay_amt + rr_excess
        govt_final     = None
        ins_label      = ins_co_recon.split()[0] if ins_co_recon else "Insurance"
        scheme_summary = f"{ins_label} (Cashless) covers ₹{ins_covers:,}. Patient copay {copay_pct_eff}%: ₹{patient_final:,}"
    elif pay_mode_recon == "reimbursement":
        ins_covers_reim = round(actual_gross * 0.80)
        ins_label       = ins_co_recon.split()[0] if ins_co_recon else "Insurer"
        patient_final   = actual_gross   # patient pays full now, claims later
        govt_final      = None
        scheme_summary  = f"Reimbursement — Patient pays ₹{actual_gross:,} now. Claim up to ₹{ins_covers_reim:,} from {ins_label}."
    else:
        patient_final  = actual_gross
        govt_final     = None
        scheme_summary = "Self-pay — Patient pays full amount"

    # Discharge medications: prefer s11 from full summary; fall back to prescriptions DB
    from .cims_drug_map import indianise_drug_name as _id_billing
    _s11 = _sec_text("s11").strip()
    if _s11 and "no medications" not in _s11.lower() and len(_s11) > 20:
        _discharge_meds_text = _s11
    elif rx_rows:
        _rx_lines = []
        for _i, _rx in enumerate([dict(_r._mapping) for _r in rx_rows]):
            _line = f"{_i+1}. {_id_billing((_rx.get('drug') or '').strip())}"
            if _rx.get('dose_val_rx'):
                _line += f" {_rx['dose_val_rx']} {_rx.get('dose_unit_rx') or ''}".rstrip()
            if _rx.get('route'):
                _line += f" — {_rx['route']}"
            _rx_lines.append(_line)
        _discharge_meds_text = "\n".join(_rx_lines)
    else:
        _discharge_meds_text = _s11

    band      = r.get("selected_band") or "expected"
    est_total = r.get("expected_est") or (est_gross_ce1 if _no_ce1 else 0)
    if band == "floor":
        est_total = r.get("floor_est") or (round(est_gross_ce1 * 0.82) if _no_ce1 else est_total)
    elif band == "ceiling":
        est_total = r.get("ceiling_est") or (round(est_gross_ce1 * 1.28) if _no_ce1 else est_total)

    signed_at   = r.get("signed_at")
    signed_str  = _fmt_datetime(signed_at) if signed_at else None
    signed_name = r.get("signed_by_name") or ""

    return {
        "patient": {
            "hadm_id":   hadm_id,
            "mrn":       f"PT-{hadm_id}",
            "age":       r.get("anchor_age"),
            "gender":    r.get("gender"),
            "ward_type": r.get("ward_type"),
        },
        "discharge": {
            # s13 = Discharge Diagnosis, s10 = Procedures, s11 = Discharge Medications
            # No character truncation — CE4 uses AI distillation via /api/billing/ce4-distill
            "final_diagnosis": (_sec_text("s13") or r.get("primary_diagnosis_title") or "").strip(),
            "procedures":      _sec_text("s10").strip(),
            "discharge_meds":  _discharge_meds_text,
            "admit_date":      _fmt_date(admit_dt),
            "discharge_date":  _fmt_date(disc_dt),
            "actual_los":      actual_los,
            "signed_by":       signed_name,
            "signed_at":       signed_str or "",
        },
        "estimate": {
            "hbp_code":         hbp_code_val,
            "hbp_package_name": _pkg_recon["name"],
            "hbp_rate":         hbp_rate_val,
            "floor_est":        r.get("floor_est") or (round(est_gross_ce1 * 0.82) if _no_ce1 else None),
            "expected_est":     r.get("expected_est") or (est_gross_ce1 if _no_ce1 else None),
            "ceiling_est":      r.get("ceiling_est") or (round(est_gross_ce1 * 1.28) if _no_ce1 else None),
            "selected_band":    band,
            "est_total":        est_total,
            "line_items":       line_items,
            "auto_generated":   _no_ce1,
        },
        "ab_info": {
            "is_ab_beneficiary": bool(r.get("is_ab_beneficiary")),
            "ab_scheme":         r.get("ab_scheme") or "",
            "hbp_rate":          hbp_rate_val,
        },
        "actuals_saved": {
            "actual_line_items":    actual_items,
            "actual_charges":       r.get("actual_charges"),
            "variance_pct":         r.get("variance_pct"),
            "reconciliation_notes": r.get("reconciliation_notes") or "",
            "insurance_paid":       r.get("insurance_paid"),
            "advance_paid":         r.get("advance_paid"),
        } if actual_items is not None else None,
        "reconciliation": {
            "expected_los":         expected_los_days,
            "actual_los":           actual_los,
            "los_diff":             los_diff,
            "actual_complexity":    round(1 + _variance_pct, 3),
            "icu_days":             round(icu_days, 1),
            "procedure_count":      proc_count,
            "actual_gross":           actual_gross,
            "computed_actual_items":  computed_actual_items,
            "computed_estimate_items":computed_estimate_items,
            "patient_pay_final":    patient_final,
            "govt_pay_final":       govt_final,
            "scheme_summary":       scheme_summary,
            "insurance_co":         ins_co_recon,
            "payment_mode":         pay_mode_recon,
            # Primary procedure for display
            "primary_procedure_icd":   proc_row[0] if proc_row else None,
            "primary_procedure_title": proc_row[2] if proc_row else None,
            "primary_diagnosis_code":  r.get("primary_diagnosis_code"),
            "primary_diagnosis_title": r.get("primary_diagnosis_title"),
        },
    }


@app.get("/api/billing/ce4-distill/{hadm_id}")
def ce4_distill(hadm_id: int):
    """
    Call Gemini to produce billing-focused summaries of final diagnosis,
    procedures performed, and discharge medications.  Falls back to raw
    section text if Gemini is unavailable.
    """
    import json as _json
    from sqlalchemy import text as _text
    from .cloud_sql_db import get_engine as _get_engine

    with _get_engine().connect() as conn:
        # Primary diagnosis
        primary_row = conn.execute(_text(
            "SELECT primary_diagnosis_code, primary_diagnosis_title FROM active_patients WHERE hadm_id = :h"
        ), {"h": hadm_id}).fetchone()

        # All diagnoses (up to 20)
        dx_rows = conn.execute(_text("""
            SELECT seq_num, icd_code, icd_version, long_title
            FROM ap_diagnoses WHERE hadm_id = :h
            ORDER BY seq_num ASC LIMIT 20
        """), {"h": hadm_id}).fetchall()

        # All procedures (up to 20)
        proc_rows = conn.execute(_text("""
            SELECT seq_num, icd_code, icd_version, long_title, chartdate
            FROM ap_procedures WHERE hadm_id = :h
            ORDER BY seq_num ASC LIMIT 20
        """), {"h": hadm_id}).fetchall()

        # Discharge medications — prescriptions active at discharge (up to 25)
        med_rows = conn.execute(_text("""
            SELECT drug, prod_strength, dose_val_rx, dose_unit_rx, route
            FROM ap_prescriptions
            WHERE hadm_id = :h AND drug IS NOT NULL
            ORDER BY stoptime DESC NULLS LAST LIMIT 25
        """), {"h": hadm_id}).fetchall()

        # Existing LLM sections (fallback)
        summ_row = conn.execute(_text("""
            SELECT asumm.sections_json
            FROM app_encounters ae
            JOIN app_summaries asumm ON asumm.encounter_id = ae.id
            WHERE ae.hadm_id = :h
            LIMIT 1
        """), {"h": hadm_id}).fetchone()

    sections = {}
    if summ_row and summ_row[0]:
        try:
            sections = _json.loads(summ_row[0]) if isinstance(summ_row[0], str) else (summ_row[0] or {})
        except Exception:
            sections = {}

    def _sec_text(key):
        v = sections.get(key)
        if v is None:
            return ""
        if isinstance(v, dict):
            return v.get("text", "") or ""
        return str(v)

    primary_code  = primary_row[0] if primary_row else ""
    primary_title = primary_row[1] if primary_row else ""

    dx_text   = "\n".join(f"{r[0]}. [{r[1]}] {r[3] or '(no title)'}" for r in dx_rows) or primary_title
    proc_text = "\n".join(
        f"{r[0]}. [{r[1]}] {r[3] or '(no title)'}" + (f" — {str(r[4])[:10]}" if r[4] else "")
        for r in proc_rows
    ) or "No procedures recorded"
    presc_text = "\n".join(
        f"- {r[0]}" + (f" {r[1]}" if r[1] else "") + (f" — {r[4]}" if r[4] else "")
        for r in med_rows
    ) or ""

    # Discharge meds: always use s11 (doctor-signed discharge summary) verbatim.
    # Fall back to raw prescriptions only if s11 is absent or too short.
    _s11 = _sec_text("s11").strip()
    _s11_valid = bool(_s11 and "no medications" not in _s11.lower() and len(_s11) > 20)
    _preferred_meds = _s11 if _s11_valid else (presc_text or "No medications recorded")

    if not gemini_client:
        # No Gemini key — return existing sections or raw text, untruncated
        return {
            "final_diagnosis": _sec_text("s13") or dx_text,
            "procedures":      _sec_text("s10") or proc_text,
            "discharge_meds":  _preferred_meds,
            "source":          "raw",
        }

    # Gemini distills diagnosis + procedures from ICD codes; meds come straight from s11.
    prompt = f"""You are summarising a hospital admission for BILLING RECONCILIATION (not clinical notes).
Be concise, factual, and billing-relevant.

PATIENT: {primary_code} — {primary_title}

ALL DIAGNOSES:
{dx_text}

ALL PROCEDURES:
{proc_text}

Produce EXACTLY two billing-focused summaries:

1. FINAL DIAGNOSIS — Start with the primary diagnosis. Add up to 3 most clinically and billing-significant secondary diagnoses (complications or major co-morbidities that justify cost). Format: "PRIMARY: [name]; [secondary 1]; [secondary 2]". No codes needed.

2. PROCEDURES PERFORMED — Pick the 3–5 most significant billable procedures (surgeries, major interventions, device placements). Skip routine nursing, nutrition, or documentation-only entries. Format: numbered list, one procedure per line, name only.

Respond ONLY with valid JSON, nothing else:
{{"final_diagnosis": "...", "procedures": "1. ...\\n2. ..."}}"""

    raw_text, err = _call_gemini(prompt, thinking_budget=0)

    if err or not raw_text:
        log.warning(f"CE4 distill Gemini error for hadm {hadm_id}: {err}")
        return {
            "final_diagnosis": _sec_text("s13") or dx_text,
            "procedures":      _sec_text("s10") or proc_text,
            "discharge_meds":  _preferred_meds,
            "source":          "raw_fallback",
        }

    try:
        # Strip markdown fences if Gemini wraps in ```json
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = _json.loads(cleaned)
        return {
            "final_diagnosis": result.get("final_diagnosis", ""),
            "procedures":      result.get("procedures", ""),
            "discharge_meds":  _preferred_meds,   # always from s11, never re-summarised
            "source":          "gemini",
        }
    except Exception as _pe:
        log.warning(f"CE4 distill JSON parse error for hadm {hadm_id}: {_pe}")
        return {
            "final_diagnosis": _sec_text("s13") or dx_text,
            "procedures":      _sec_text("s10") or proc_text,
            "discharge_meds":  _preferred_meds,
            "source":          "raw_fallback",
        }


# ── Encounters ────────────────────────────────────────────────────────────────
class NewEncounterRequest(BaseModel):
    hadm_id: int
    full_name: Optional[str] = ""
    ward: Optional[str] = ""
    admission_date: Optional[str] = ""
    assigned_doctor_id: Optional[str] = None

_DCM_SEED_HADM_IDS = [25434637, 20553493, 28113079, 24339216, 28855911,
                      29950776, 26972341, 26935676, 24823642, 23149252]

@app.post("/api/seed/cardiology")
async def seed_cardiology_encounters():
    """Create Pending Ingestion encounters for top 10 DCM ICU patients if not already present."""
    results = []
    for hadm_id in _DCM_SEED_HADM_IDS:
        existing = gdb.get_encounter_by_hadm(hadm_id)
        if existing:
            results.append({"hadm_id": hadm_id, "status": "exists", "enc_id": existing["id"]})
        else:
            enc = gdb.create_encounter(hadm_id, status="Pending Ingestion")
            results.append({"hadm_id": hadm_id, "status": "created", "enc_id": enc["id"]})
    # Also trigger data_server to seed active_patients display data (fire-and-forget)
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{DATA_SERVER}/api/seed/cardiology", timeout=2.0)
    except Exception:
        pass
    return {"seeded": results}


@app.post("/api/encounters")
def create_encounter(req: NewEncounterRequest):
    existing = gdb.get_encounter_by_hadm(req.hadm_id)
    if existing:
        return {"status": "success", "encounter_id": existing["id"]}
    enc = gdb.create_encounter(req.hadm_id, status="Pending Ingestion")
    return {"status": "success", "encounter_id": enc["id"]}

@app.get("/api/encounters")
def list_encounters(status: str = None, assigned_to: str = None, exclude_status: str = None):
    return gdb.list_encounters(status=status, assigned_to=assigned_to, exclude_status=exclude_status)

@app.get("/api/active_patients")
def list_active_patients():
    """All patients loaded into Cloud SQL (active_patients), joined with encounter status if any."""
    from sqlalchemy import text as _text
    from .cloud_sql_db import get_engine as _get_engine
    with _get_engine().connect() as conn:
        rows = conn.execute(_text("""
            SELECT ap.hadm_id, ap.subject_id, ap.gender, ap.anchor_age,
                   ap.race, ap.marital_status, ap.admission_type,
                   ap.admission_location, ap.discharge_location,
                   ap.admit_time, ap.discharge_time, ap.los_days,
                   ap.primary_diagnosis_code, ap.primary_diagnosis_title,
                   ap.principal_drg_description, ap.drg_severity,
                   ap.data_fetch_status, ap.status AS patient_status,
                   ae.id            AS encounter_id,
                   ae.status        AS encounter_status,
                   ae.assigned_to   AS assigned_to,
                   ae.discharge_type
            FROM active_patients ap
            LEFT JOIN app_encounters ae ON ae.hadm_id = ap.hadm_id
            WHERE ap.data_fetch_status IN ('fetched', 'partial', 'fetching')
            ORDER BY ap.admit_time DESC NULLS LAST
            LIMIT 500
        """)).fetchall()
    return [dict(r._mapping) for r in rows]

@app.get("/api/summaries")
def list_summaries():
    summaries = gdb.list_summaries()
    # Join each summary with its encounter (hadm_id, status, assigned_to)
    enc_index = {e["id"]: e for e in gdb.list_encounters()}
    for s in summaries:
        enc = enc_index.get(s.get("encounter_id"), {})
        s["hadm_id"]    = enc.get("hadm_id")
        s["enc_status"] = enc.get("status")
        s["assigned_to"]= enc.get("assigned_to")
        s.pop("clinical_context", None)  # strip heavy field from list response
    return summaries


# ── Column aliases for flexible CSV headers ────────────────────────────────────
def _norm(row: dict, *keys):
    """Return first matching key from row (case-insensitive, space≡underscore)."""
    low = {k.lower().strip().replace(" ", "_"): v for k, v in row.items()}
    for k in keys:
        nk = k.lower().replace(" ", "_")
        if nk in low:
            v = low[nk]
            return v if v not in ("", None) else None
    return None

def _ts(val):
    """Normalise a date/time string to ISO format or None."""
    if not val:
        return None
    try:
        from dateutil import parser as dtp
        return dtp.parse(str(val)).isoformat()
    except Exception:
        return str(val) if val else None

def _float(val):
    try:
        return float(val)
    except Exception:
        return None

def _int(val):
    try:
        return int(float(val))
    except Exception:
        return None


def _bg_enrich_and_index(hadm_id: int, file_type: str, file_id: str, batch: list):
    """Background task: enrich row titles, write ap_* table, invalidate cache."""
    async def _enrich():
        nonlocal batch
        if file_type in ("procedures", "diagnoses"):
            batch = await _enrich_icd(batch, file_type)
        elif file_type == "labs":
            batch = await _enrich_labevents(batch)
    try:
        asyncio.run(_enrich())
    except Exception as exc:
        log.warning(f"[INGEST-BG] enrichment error for {file_type}: {exc}")
    # Re-store with enriched titles so uploaded_clinical_data endpoint returns them
    gdb.store_clinical_rows(hadm_id, file_type, file_id, batch)
    # Write to ap_* structured table (used by lazy tab data server queries)
    _write_upload_ap_table(file_type, file_id, hadm_id, batch)
    # Invalidate data_server cache so next lazyLoad fetch returns updated data
    _ds_tab = _INGEST_KEY_TO_DS_TAB.get(file_type)
    _invalidate_ds_cache(hadm_id, _ds_tab)
    log.info(f"[INGEST-BG-DONE] HADM {hadm_id} | {file_type} | {len(batch)} rows indexed")


@app.post("/api/encounters/{hadm_id}/ingest_file")
async def ingest_file(
    hadm_id: int,
    background_tasks: BackgroundTasks,
    file_type: str = Form(...),   # "labs" | "meds" | "notes" | "diagnoses" | "procedures" | "icu" | "microbiology"
    file: UploadFile = File(...),
):
    """
    Parse an uploaded CSV and insert rows into the correct MIMIC table.
    Also records the file in uploaded_files.
    Enrichment + ap_* table write run in background so response returns fast.
    """
    log.info(f"[INGEST-START] HADM {hadm_id} | {file_type} | {file.filename}")
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = list(csv.DictReader(io.StringIO(text)))
    if not reader:
        raise HTTPException(400, "CSV is empty or has no header row")

    subject_id = hadm_id  # placeholder subject_id

    # Resolve or create encounter
    enc = gdb.get_encounter_by_hadm(hadm_id)
    if enc:
        enc_id = enc["id"]
    else:
        enc = gdb.create_encounter(hadm_id, status="Pending Ingestion")
        enc_id = enc["id"]

    # Do NOT auto-advance to "Files Ready" here — the resident must explicitly click
    # "Submit — All Files Uploaded" which calls /mark_files_ready. This prevents a single
    # partial upload from notifying ward admin before all required files are present.

    inserted = 0
    errors: list = []

    # Base for auto-generated PKs: microseconds since epoch
    _pk_base = int(time.time() * 1_000_000)

    _type_label = {
        "labs":          "Labs",
        "meds":          "Medications",
        "notes":         "Clinical Notes",
        "diagnoses":     "Diagnoses",
        "procedures":    "Procedures",
        "icu":           "ICU Events",
        "microbiology":  "Microbiology",
        "transfers":     "Transfers",
        "icustays":      "ICU Stays",
    }.get(file_type, "Other")

    file_rec = gdb.create_file_record(
        encounter_id=enc_id,
        file_type=_type_label,
        file_name=file.filename,
        file_size=len(content),
    )
    file_id: str = file_rec["id"]

    # ── Build batch rows for Cloud SQL ───────────────────────────────────────
    batch: list = []

    if file_type == "labs":
        for i, r in enumerate(reader):
            batch.append({
                "labevent_id":     _pk_base + i,
                "hadm_id":         hadm_id,
                "subject_id":      subject_id,
                "source_file_id":  file_id,
                "itemid":          _int(_norm(r, "itemid", "item_id")),
                "charttime":       _ts(_norm(r, "charttime", "chart_time", "datetime", "date", "time", "timestamp")),
                "value":           _norm(r, "value", "result", "result_value"),
                "valuenum":        _float(_norm(r, "valuenum", "value_num", "numeric_value", "result_numeric")),
                "valueuom":        _norm(r, "valueuom", "unit", "units", "uom"),
                "flag":            _norm(r, "flag", "abnormal_flag", "status"),
                "ref_range_lower": _float(_norm(r, "ref_range_lower", "normal_low", "ref_low", "lower_limit")),
                "ref_range_upper": _float(_norm(r, "ref_range_upper", "normal_high", "ref_high", "upper_limit")),
                "priority":        _norm(r, "priority"),
                "comments":        _norm(r, "comments", "comment", "notes"),
            })

    elif file_type == "meds":
        for r in reader:
            batch.append({
                "hadm_id":        hadm_id,
                "subject_id":     subject_id,
                "source_file_id": file_id,
                "drug":           _norm(r, "drug", "medication", "drug_name", "medicine", "name"),
                "drug_type":      _norm(r, "drug_type", "type", "category") or "MAIN",
                "starttime":      _ts(_norm(r, "starttime", "start_time", "start_date", "start")),
                "stoptime":       _ts(_norm(r, "stoptime",  "stop_time",  "stop_date",  "end", "end_date")),
                "dose_val_rx":    _norm(r, "dose_val_rx", "dose", "dosage", "dose_value"),
                "dose_unit_rx":   _norm(r, "dose_unit_rx", "dose_unit", "unit", "units"),
                "route":          _norm(r, "route", "administration_route"),
                "prod_strength":  _norm(r, "prod_strength", "strength", "concentration"),
                "form_rx":        _norm(r, "form_rx", "form", "formulation"),
            })

    elif file_type == "notes":
        for i, r in enumerate(reader):
            batch.append({
                "note_id":        f"upl_{hadm_id}_{_pk_base}_{i}",
                "hadm_id":        hadm_id,
                "subject_id":     subject_id,
                "source_file_id": file_id,
                "note_type":  _norm(r, "note_type", "type", "category", "note_category") or "Discharge summary",
                "charttime":  _ts(_norm(r, "charttime", "chart_time", "datetime", "date")),
                "text":       _norm(r, "text", "note", "content", "note_text") or "",
            })

    elif file_type == "diagnoses":
        for i, r in enumerate(reader):
            batch.append({
                "hadm_id":        hadm_id,
                "subject_id":     subject_id,
                "source_file_id": file_id,
                "seq_num":        _int(_norm(r, "seq_num", "sequence", "priority", "rank")) or (i + 1),
                "icd_code":    _norm(r, "icd_code", "icd", "code", "diagnosis_code", "dx_code"),
                "icd_version": _int(_norm(r, "icd_version", "version")) or 10,
                "long_title":  _norm(r, "long_title", "description", "diagnosis_name", "title", "name", "long_description"),
            })

    elif file_type == "procedures":
        for i, r in enumerate(reader):
            batch.append({
                "hadm_id":        hadm_id,
                "subject_id":     subject_id,
                "source_file_id": file_id,
                "seq_num":        _int(_norm(r, "seq_num", "sequence", "priority", "rank")) or (i + 1),
                "icd_code":    _norm(r, "icd_code", "icd", "code", "procedure_code", "proc_code"),
                "icd_version": _int(_norm(r, "icd_version", "version")) or 10,
                "chartdate":   _norm(r, "chartdate", "date", "procedure_date"),
                "long_title":  _norm(r, "long_title", "description", "procedure_name", "title", "name", "long_description"),
            })

    elif file_type == "icu":
        for r in reader:
            batch.append({
                "hadm_id":        hadm_id,
                "subject_id":     subject_id,
                "source_file_id": file_id,
                "itemid":     _int(_norm(r, "itemid", "item_id")),
                "charttime":  _ts(_norm(r, "charttime", "chart_time", "datetime", "date", "time")),
                "value":      _norm(r, "value", "result"),
                "valuenum":   _float(_norm(r, "valuenum", "value_num", "numeric_value")),
                "valueuom":   _norm(r, "valueuom", "unit", "units"),
                "warning":    _int(_norm(r, "warning", "alert")) or 0,
            })

    elif file_type == "microbiology":
        for i, r in enumerate(reader):
            batch.append({
                "microevent_id":  _pk_base + i,
                "hadm_id":        hadm_id,
                "subject_id":     subject_id,
                "source_file_id": file_id,
                "charttime":      _ts(_norm(r, "charttime", "chart_time", "datetime", "date")),
                "spec_type_desc": _norm(r, "spec_type_desc", "specimen", "specimen_type", "sample_type"),
                "test_name":      _norm(r, "test_name", "test", "organism", "culture"),
                "org_name":       _norm(r, "org_name", "organism", "organism_name", "pathogen"),
                "ab_name":        _norm(r, "ab_name", "antibiotic", "drug"),
                "interpretation": _norm(r, "interpretation", "result", "sensitivity", "susceptibility"),
                "comments":       _norm(r, "comments", "comment", "notes"),
            })

    elif file_type == "transfers":
        for i, r in enumerate(reader):
            batch.append({
                "transfer_id":    _pk_base + i,
                "hadm_id":        hadm_id,
                "subject_id":     subject_id,
                "source_file_id": file_id,
                "careunit":  _norm(r, "careunit", "care_unit", "unit"),
                "eventtype": _norm(r, "eventtype", "event_type", "event"),
                "intime":    _ts(_norm(r, "intime", "in_time", "start", "starttime")),
                "outtime":   _ts(_norm(r, "outtime", "out_time", "end", "endtime")),
            })

    elif file_type == "icustays":
        for i, r in enumerate(reader):
            batch.append({
                "stay_id":        _int(_norm(r, "stay_id")) or (_pk_base + i),
                "hadm_id":        hadm_id,
                "subject_id":     subject_id,
                "source_file_id": file_id,
                "first_careunit": _norm(r, "first_careunit", "first_care_unit", "careunit", "unit"),
                "last_careunit":  _norm(r, "last_careunit",  "last_care_unit",  "careunit", "unit"),
                "intime":  _ts(_norm(r, "intime",  "in_time",  "start")),
                "outtime": _ts(_norm(r, "outtime", "out_time", "end")),
                "los":     _float(_norm(r, "los", "length_of_stay")),
            })

    elif file_type == "pharmacy":
        for r in reader:
            batch.append({
                "hadm_id":        hadm_id,
                "subject_id":     subject_id,
                "source_file_id": file_id,
                "medication":  _norm(r, "medication", "drug", "med_name"),
                "frequency":   _norm(r, "frequency", "freq"),
                "route":       _norm(r, "route"),
                "status":      _norm(r, "status"),
                "starttime":   _ts(_norm(r, "starttime", "start_time", "start")),
                "stoptime":    _ts(_norm(r, "stoptime",  "stop_time",  "stop")),
                "duration":    _float(_norm(r, "duration")),
                "duration_interval": _norm(r, "duration_interval", "duration_unit"),
            })

    elif file_type == "poe":
        for i, r in enumerate(reader):
            batch.append({
                "hadm_id":        hadm_id,
                "subject_id":     subject_id,
                "source_file_id": file_id,
                "poe_id":      _norm(r, "poe_id") or f"upl_{hadm_id}_{_pk_base}_{i}",
                "poe_seq":     _int(_norm(r, "poe_seq", "seq")),
                "ordertime":   _ts(_norm(r, "ordertime", "order_time", "datetime", "date")),
                "order_type":  _norm(r, "order_type", "type"),
                "order_subtype": _norm(r, "order_subtype", "subtype"),
                "order_status":  _norm(r, "order_status", "status"),
            })

    elif file_type == "fluids":
        for r in reader:
            batch.append({
                "hadm_id":        hadm_id,
                "subject_id":     subject_id,
                "source_file_id": file_id,
                "itemid":     _int(_norm(r, "itemid", "item_id")),
                "label":      _norm(r, "label", "item", "name"),
                "amount":     _float(_norm(r, "amount", "volume", "value")),
                "amountuom":  _norm(r, "amountuom", "amount_uom", "unit"),
                "rate":       _float(_norm(r, "rate")),
                "rateuom":    _norm(r, "rateuom", "rate_uom", "rate_unit"),
                "starttime":  _ts(_norm(r, "starttime", "start_time", "datetime", "date")),
                "endtime":    _ts(_norm(r, "endtime",   "end_time")),
            })

    elif file_type == "vitals":
        for r in reader:
            batch.append({
                "hadm_id":        hadm_id,
                "subject_id":     subject_id,
                "source_file_id": file_id,
                "itemid":    _int(_norm(r, "itemid", "item_id")),
                "label":     _norm(r, "label", "parameter", "vital", "name"),
                "value":     _norm(r, "value", "result"),
                "valuenum":  _float(_norm(r, "valuenum", "value_num", "numeric_value")),
                "valueuom":  _norm(r, "valueuom", "unit", "uom"),
                "warning":   _int(_norm(r, "warning", "alert")),
                "charttime": _ts(_norm(r, "charttime", "chart_time", "datetime", "date")),
            })


    else:
        raise HTTPException(400, f"Unknown file_type: {file_type}")

    if batch:
        # Critical path: write raw rows immediately so uploaded_clinical_data responds fast
        gdb.store_clinical_rows(hadm_id, file_type, file_id, batch)
        inserted = len(batch)
        gdb.update_file_record(file_id, {"indexed_status": True})
        # Defer: enrichment (ICD/lab titles) + ap_* table write + cache invalidation
        background_tasks.add_task(_bg_enrich_and_index, hadm_id, file_type, file_id, batch)

    log.info(f"[INGEST] HADM {hadm_id} | {file_type} | {inserted} rows | {file.filename} | file_id={file_id}")
    return {"status": "ok", "hadm_id": hadm_id, "file_type": file_type, "rows_inserted": inserted, "errors": errors, "file_id": file_id, "encounter_id": enc_id}


# Tables whose source_file_id column has been verified this server session.
# Populated lazily so the first upload self-heals without a restart.
_ap_col_verified: set = set()

# ── Upload write-back: ap_* Cloud SQL tables ──────────────────────────────────
# Maps file_type → (ap_table_name, columns_to_insert)
# Tables skipped (fluids/datetime): NOT NULL FK to ap_icustays.stay_id that uploaded rows can't satisfy
_UPLOAD_AP_TABLES: dict = {
    "labs":        ("ap_labevents",          ["labevent_id", "hadm_id", "subject_id", "source_file_id",
                                               "itemid", "charttime", "value", "valuenum", "valueuom",
                                               "flag", "ref_range_lower", "ref_range_upper", "priority", "comments"]),
    "meds":        ("ap_prescriptions",      ["hadm_id", "subject_id", "source_file_id",
                                               "drug", "drug_type", "starttime", "stoptime",
                                               "dose_val_rx", "dose_unit_rx", "route", "prod_strength", "form_rx"]),
    "diagnoses":   ("ap_diagnoses",          ["hadm_id", "subject_id", "source_file_id",
                                               "seq_num", "icd_code", "icd_version", "long_title"]),
    "procedures":  ("ap_procedures",         ["hadm_id", "subject_id", "source_file_id",
                                               "seq_num", "icd_code", "icd_version", "chartdate", "long_title"]),
    "icu":         ("ap_chartevents",        ["hadm_id", "subject_id", "source_file_id",
                                               "itemid", "charttime", "value", "valuenum", "valueuom", "warning"]),
    "vitals":      ("ap_chartevents",        ["hadm_id", "subject_id", "source_file_id",
                                               "itemid", "label", "charttime", "value", "valuenum", "valueuom", "warning"]),
    "microbiology":("ap_microbiologyevents", ["microevent_id", "hadm_id", "subject_id", "source_file_id",
                                               "charttime", "spec_type_desc", "test_name", "org_name",
                                               "ab_name", "interpretation", "comments"]),
    "transfers":   ("ap_transfers",          ["transfer_id", "hadm_id", "subject_id", "source_file_id",
                                               "careunit", "eventtype", "intime", "outtime"]),
    "icustays":    ("ap_icustays",           ["stay_id", "hadm_id", "subject_id", "source_file_id",
                                               "first_careunit", "last_careunit", "intime", "outtime", "los"]),
    "pharmacy":    ("ap_pharmacy",           ["pharmacy_id", "hadm_id", "subject_id", "source_file_id",
                                               "medication", "frequency", "route", "status",
                                               "starttime", "stoptime", "duration", "duration_interval"]),
    "poe":         ("ap_poe",               ["poe_id", "hadm_id", "subject_id", "source_file_id",
                                              "poe_seq", "ordertime", "order_type", "order_subtype", "order_status"]),
}

# Tables that have a natural PK column (not BIGSERIAL) for ON CONFLICT DO NOTHING
_AP_PK_COL: dict = {
    "ap_labevents":          "labevent_id",
    "ap_microbiologyevents": "microevent_id",
    "ap_transfers":          "transfer_id",
    "ap_icustays":           "stay_id",
    "ap_poe":                "poe_id",
    "ap_pharmacy":           "pharmacy_id",
}


def _write_upload_ap_table(file_type: str, file_id: str, hadm_id: int, batch: list) -> int:
    """Insert uploaded batch directly into the corresponding ap_* table."""
    from .cloud_sql_db import get_engine
    from sqlalchemy import text as sqla_text

    cfg = _UPLOAD_AP_TABLES.get(file_type)
    if not cfg or not batch:
        return 0

    table_name, cols = cfg
    pk_col = _AP_PK_COL.get(table_name)

    rows = []
    for i, src in enumerate(batch):
        row = {c: src.get(c) for c in cols}
        # ap_pharmacy has a BIGINT PK not present in the batch — generate it
        if table_name == "ap_pharmacy" and not row.get("pharmacy_id"):
            row["pharmacy_id"] = int(hashlib.md5(f"{file_id}_{i}".encode()).hexdigest()[:15], 16)
        rows.append(row)

    col_str  = ", ".join(cols)
    ph_str   = ", ".join(f":{c}" for c in cols)
    if pk_col:
        sql = f"INSERT INTO {table_name} ({col_str}) VALUES ({ph_str}) ON CONFLICT ({pk_col}) DO NOTHING"
    else:
        sql = f"INSERT INTO {table_name} ({col_str}) VALUES ({ph_str}) ON CONFLICT DO NOTHING"

    engine = get_engine()
    # Ensure source_file_id column exists — self-healing, cached per session
    if table_name not in _ap_col_verified:
        try:
            with engine.begin() as conn:
                conn.execute(sqla_text(
                    f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40)"
                ))
            _ap_col_verified.add(table_name)
        except Exception as _ce:
            log.warning(f"[AP-INSERT] could not ensure source_file_id on {table_name}: {_ce}")
    with engine.begin() as conn:
        conn.execute(sqla_text(f"DELETE FROM {table_name} WHERE hadm_id = :h AND source_file_id = :fid"),
                     {"h": hadm_id, "fid": file_id})
        conn.execute(sqla_text(sql), rows)
    inserted = len(rows)
    log.info(f"[AP-INSERT] {table_name} hadm={hadm_id} file={file_id} inserted={inserted}")
    return inserted


def _delete_upload_ap_table(file_type: str, file_id: str, hadm_id: int) -> int:
    """Delete rows from the ap_* table that came from a specific uploaded file."""
    from .cloud_sql_db import get_engine
    from sqlalchemy import text as sqla_text

    cfg = _UPLOAD_AP_TABLES.get(file_type)
    if not cfg:
        return 0

    table_name, _ = cfg
    engine = get_engine()
    with engine.begin() as conn:
        result = conn.execute(
            sqla_text(f"DELETE FROM {table_name} WHERE hadm_id = :h AND source_file_id = :fid"),
            {"h": hadm_id, "fid": file_id}
        )
    deleted = result.rowcount
    log.info(f"[AP-DELETE] {table_name} hadm={hadm_id} file={file_id} deleted={deleted}")
    return deleted


# ── Cache invalidation helper ─────────────────────────────────────────────────
# Maps ingest file_type key → data_server tab_name (for lazy-tab cache clear)
_INGEST_KEY_TO_DS_TAB: Dict[str, str] = {
    "labs":        "labevents",
    "meds":        "prescriptions",
    "pharmacy":    "pharmacy",
    "poe":         "poe",
    "fluids":      "fluids",
    "vitals":      "chartevents",
}


def _invalidate_ds_cache(hadm_id: int, tab: Optional[str] = None) -> None:
    """Synchronous fire-and-forget: clear data_server in-memory cache."""
    import httpx as _h
    try:
        url = f"{DATA_SERVER}/api/patient/{hadm_id}/cache"
        if tab:
            url += f"?tab={tab}"
        _h.delete(url, timeout=2.0)
    except Exception:
        pass


# ── Delete uploaded file + its data ───────────────────────────────────────────
_INGEST_KEY_TO_TABLE = {
    "labs":         "labevents",
    "meds":         "prescriptions",
    "notes":        "noteevents",
    "diagnoses":    "diagnoses_icd",
    "procedures":   "procedures_icd",
    "icu":          "chartevents",
    "microbiology": "microbiologyevents",
    "transfers":    "transfers",
    "icustays":     "icustays",
    "pharmacy":     "pharmacy",
    "poe":          "poe",
    "fluids":       "inputevents",
    "vitals":       "chartevents",
}

@app.delete("/api/encounters/{hadm_id}/clinical_rows/{file_type}")
async def purge_clinical_rows(hadm_id: int, file_type: str):
    """Purge ALL uploaded clinical rows for a hadm_id + file_type (orphan cleanup)."""
    ft_key = _DISPLAY_LABEL_TO_KEY.get(file_type.lower().strip(), file_type.lower().strip())
    deleted = await run_in_threadpool(gdb.purge_all_clinical_rows, hadm_id, ft_key)
    log.info(f"[PURGE] HADM {hadm_id} type={ft_key} deleted={deleted} blobs")
    return {"status": "ok", "hadm_id": hadm_id, "file_type": ft_key, "blobs_deleted": deleted}

@app.post("/api/encounters/{hadm_id}/mark_files_ready")
async def mark_files_ready(hadm_id: int, request: Request):
    """Resident submits corrected/amendment files.

    Revision Requested  → Files Ready   (ward admin must still trigger regen)
    Amendment Requested → Awaiting Review (no regen needed; doctor re-signs)
    """
    enc = gdb.get_encounter_by_hadm(hadm_id)
    if not enc:
        raise HTTPException(status_code=404, detail="Encounter not found")
    prev_status = enc.get("status", "")
    if prev_status not in ("Revision Requested", "Files Ready", "Amendment Requested"):
        return {"status": "ok", "enc_status": prev_status}

    is_amendment = prev_status == "Amendment Requested"

    # Stamp rejection log files_ready_at for Revision flow
    if not is_amendment:
        try:
            rl = gdb.get_latest_rejection_log_with_user(enc["id"])
            if rl and not rl.get("files_ready_at"):
                gdb.update_rejection_log(rl["id"], {"files_ready_at": datetime.utcnow().isoformat()})
        except Exception:
            pass

    # Both revision and amendment → Files Ready so ward admin triggers regen/re-review
    new_status = "Files Ready"
    gdb.update_encounter(enc["id"], {"status": new_status})

    action = "AMENDMENT_FILES_SUBMITTED" if is_amendment else "REVISION_FILES_RESUBMITTED"
    gdb.log_action(action, hadm_id=hadm_id, details={
        "prev_status": prev_status,
        "new_status":  new_status,
        "enc_id":      enc["id"],
    })

    return {"status": "ok", "enc_status": new_status}


@app.get("/api/encounters/{hadm_id}/uploaded_clinical_data")
async def get_uploaded_clinical_data(hadm_id: int):
    """Return all uploaded clinical rows for this admission, grouped by file type."""
    data = await run_in_threadpool(gdb.fetch_all_uploaded_clinical_data, hadm_id)
    # Return only file types that have rows
    return {k: v for k, v in data.items() if v}


_DISPLAY_LABEL_TO_KEY = {
    "labs": "labs", "lab": "labs", "labevents": "labs",
    "medications": "meds", "medication": "meds", "prescriptions": "meds",
    "clinical notes": "notes", "notes": "notes",
    "diagnoses": "diagnoses", "diagnoses (icd)": "diagnoses", "diagnoses_icd": "diagnoses",
    "procedures": "procedures", "procedures_icd": "procedures",
    "icu events": "icu", "icu": "icu", "chartevents": "icu",
    "microbiology": "microbiology",
    "transfers": "transfers",
    "icu stays": "icustays", "icustays": "icustays",
    "pharmacy": "pharmacy",
    "physician orders": "poe", "poe": "poe",
    "fluids i/o": "fluids", "fluids": "fluids",
    "vitals": "vitals",
    "datetime events": "datetime", "datetime": "datetime",
}

@app.delete("/api/uploaded_files/{file_id}")
async def delete_uploaded_file(file_id: str, file_type: str, hadm_id: int):
    """Delete clinical rows for this file_id then remove the file record."""
    file_type_key = _DISPLAY_LABEL_TO_KEY.get(file_type.lower().strip(), file_type.lower().strip())
    await run_in_threadpool(gdb.delete_clinical_rows, hadm_id, file_type_key, file_id)
    await run_in_threadpool(_delete_upload_ap_table, file_type_key, file_id, hadm_id)
    await run_in_threadpool(gdb.delete_file_record, file_id)
    # Clear data_server memory cache so next tab fetch reflects the deletion
    _ds_tab = _INGEST_KEY_TO_DS_TAB.get(file_type_key)
    await run_in_threadpool(_invalidate_ds_cache, hadm_id, _ds_tab)
    log.info(f"[DELETE] file_id={file_id} hadm_id={hadm_id} file_type={file_type} → key={file_type_key}")
    return {"status": "ok", "deleted_file_id": file_id, "purged_table": _INGEST_KEY_TO_TABLE.get(file_type_key), "purged_rows": "all"}


# ── Full data fetch from uploaded clinical rows ───────────────────────────────
def fetch_all_patient_data(hadm_id: int) -> Dict[str, Any]:
    """
    Fetch every uploaded clinical table for this hadm_id from Cloud SQL.
    Used for source=db (manually uploaded CSV files).
    """
    table_log: List[Dict] = []

    def _log(table: str, rows: list, cap: int = None):
        capped = cap is not None and len(rows) >= cap
        table_log.append({"table": table, "count": len(rows), "capped": capped, "cap": cap})
        log.info(f"[TABLE] {table:<28} → {len(rows):>5} records" + (f"  (cap {cap})" if capped else ""))
        return rows[:cap] if cap else rows

    clinical = gdb.fetch_all_uploaded_clinical_data(hadm_id)
    # Keys now match file_type (e.g. "procedures", "labs", "meds")

    diagnoses     = sorted(clinical.get("diagnoses", []),    key=lambda x: x.get("seq_num") or 99)
    procedures_icd= sorted(clinical.get("procedures", []),   key=lambda x: x.get("seq_num") or 99)
    microevents   = sorted(clinical.get("microbiology", []), key=lambda x: x.get("charttime") or "", reverse=True)
    prescriptions = _log("prescriptions", sorted(clinical.get("meds", []), key=lambda x: x.get("starttime") or "", reverse=True), cap=80)
    noteevents    = sorted(clinical.get("notes", []),         key=lambda x: x.get("charttime") or "", reverse=True)
    transfers     = sorted(clinical.get("transfers", []),     key=lambda x: x.get("intime") or "")
    labevents     = _log("labevents", sorted(clinical.get("labs", []), key=lambda x: x.get("charttime") or "", reverse=True), cap=30)
    icustays      = sorted(clinical.get("icustays", []),      key=lambda x: x.get("intime") or "")
    chartevents   = _log("chartevents", sorted(clinical.get("vitals", []) + clinical.get("icu", []), key=lambda x: x.get("charttime") or "", reverse=True), cap=80)
    outputevents: list = []
    inputevents:  list = []
    procevents:   list = []
    dtevents:     list = []
    ingredients:  list = []

    for tbl, rows in [
        ("diagnoses_icd", diagnoses), ("procedures_icd", procedures_icd),
        ("microbiologyevents", microevents),
        ("noteevents", noteevents), ("transfers", transfers),
        ("icustays", icustays), ("outputevents", outputevents),
        ("inputevents", inputevents), ("procedureevents", procevents),
        ("datetimeevents", dtevents), ("ingredientevents", ingredients),
    ]:
        _log(tbl, rows)

    enc = gdb.get_encounter_by_hadm(hadm_id)
    _log("encounters", [enc] if enc else [])

    uploaded_files = gdb.list_files_by_encounter(enc["id"]) if enc else []
    _log("uploaded_files", uploaded_files)

    # Build minimal admission/patient from first lab/diagnosis row
    adm = {"hadm_id": hadm_id}
    pat = {}

    total_tables  = len(table_log)
    total_records = sum(t["count"] for t in table_log)
    log.info(f"[DONE ] {total_tables} tables queried · {total_records} total records for HADM {hadm_id}")

    return {
        "table_log":       table_log,
        "admission":       adm,
        "patient":         pat,
        "diagnoses":       diagnoses,
        "procedures_icd":  procedures_icd,
        "labevents":       labevents,
        "microevents":     microevents,
        "prescriptions":   prescriptions,
        "noteevents":      noteevents,
        "transfers":       transfers,
        "icustays":        icustays,
        "chartevents":     chartevents,
        "inputevents":     inputevents,
        "outputevents":    outputevents,
        "procevents":      procevents,
        "dtevents":        dtevents,
        "ingredients":     ingredients,
        "encounter":       enc,
        "uploaded_files":  uploaded_files,
    }


# Fallback labels for common MIMIC-IV chartevents item IDs
_CHART_LABELS = {
    220045: "Heart Rate", 220050: "Arterial BP Systolic", 220051: "Arterial BP Diastolic",
    220052: "Arterial BP Mean", 220179: "Non-Invasive BP Systolic", 220180: "Non-Invasive BP Diastolic",
    220181: "Non-Invasive BP Mean", 220210: "Respiratory Rate", 220277: "SpO2",
    220739: "GCS - Eye Opening", 223900: "GCS - Verbal Response", 223901: "GCS - Motor Response",
    220734: "GCS Total", 223762: "Temperature Celsius", 223761: "Temperature Fahrenheit",
    226512: "Admission Weight (Kg)", 226730: "Height (cm)", 224684: "Tidal Volume Observed",
    224686: "Total PEEP Level", 223835: "FiO2 Set",
}


def _vitals_to_prose(chart_rows: list) -> str:
    """Convert chartevents rows into two compact prose lines (admission + discharge)."""
    from collections import defaultdict
    # Ordered priority list — first matching label wins per parameter slot.
    # Includes both short legacy names and full MIMIC-IV chartevents label strings.
    VITAL_ORDER = [
        ("Heart Rate",                              "/min"),
        ("Non-Invasive BP Systolic",                "mmHg"),
        ("Non-Invasive BP Diastolic",               "mmHg"),
        ("Non Invasive Blood Pressure systolic",    "mmHg"),
        ("Non Invasive Blood Pressure diastolic",   "mmHg"),
        ("Non Invasive Blood Pressure mean",        "mmHg"),
        ("Arterial BP Systolic",                    "mmHg"),
        ("Arterial BP Diastolic",                   "mmHg"),
        ("Arterial Blood Pressure systolic",        "mmHg"),
        ("Arterial Blood Pressure diastolic",       "mmHg"),
        ("Arterial Blood Pressure mean",            "mmHg"),
        ("Respiratory Rate",                        "/min"),
        ("SpO2",                                    "%"),
        ("O2 saturation pulseoxymetry",             "%"),
        ("O2 Delivery Device(s)",                   ""),
        ("Oxygen Flow Rate",                        "L/min"),
        ("Temperature Celsius",                     "°C"),
        ("Temperature Fahrenheit",                  "°F"),
        ("GCS Total",                               ""),
        ("GCS - Eye Opening",                       ""),
        ("GCS - Motor Response",                    ""),
        ("GCS - Verbal Response",                   ""),
    ]
    vbp: dict = defaultdict(list)
    for c in sorted(chart_rows, key=lambda x: x.get("charttime") or ""):
        label = (
            c.get("label")
            or _CHART_LABELS.get(int(c.get("itemid") or 0))
            or f"itemid={c.get('itemid')}"
        )
        vbp[label].append({
            "raw": str(c.get("value") or c.get("valuenum") or "?"),
            "uom": c.get("valueuom") or "",
        })
    listed_labels: set = set()

    def _pick(readings, default_uom):
        first = readings[0]
        v = first["raw"]
        u = first.get("uom") or default_uom
        return f"{v}{(' ' + u) if u else ''}"

    # Build admission snippet from first reading of each vital
    admit_parts = []
    for param, default_uom in VITAL_ORDER:
        readings = vbp.get(param)
        if not readings:
            continue
        listed_labels.add(param)
        admit_parts.append(f"{param} {_pick(readings, default_uom)}")
    # Catch-all: include any label not already listed (non-noise only)
    _NOISE = {"Ectopy Type 1", "Ectopy Type 2", "Ectopy Frequency", "Alarm Source"}
    for label, readings in sorted(vbp.items()):
        if label not in listed_labels and label not in _NOISE and readings:
            admit_parts.append(f"{label} {_pick(readings, '')}")

    # Build discharge snippet from last reading
    dc_parts = []
    for param, default_uom in VITAL_ORDER:
        readings = vbp.get(param)
        if not readings or len(readings) < 2:
            continue
        last = readings[-1]
        v = last["raw"]
        u = last.get("uom") or default_uom
        dc_parts.append(f"{param} {v}{(' ' + u) if u else ''}")
    lines_out = []
    if admit_parts:
        lines_out.append("Admission vitals: " + ", ".join(admit_parts) + ".")
    if dc_parts:
        lines_out.append("Discharge vitals: " + ", ".join(dc_parts) + ".")
    return "\n".join(lines_out) if lines_out else "Vital signs not recorded."


def _labs_to_prose(labs: list) -> str:
    """Convert raw lab rows into clinical prose sentences grouped by category."""
    from collections import defaultdict

    # Labels that are ABG/ICU metadata, not true lab results — skip entirely
    ARTEFACT_LABELS = {
        "intubated", "specimen type", "temperature", "oxygen",
        "calculated total co2", "alveolar-arterial gradient",
    }

    CATEGORIES = [
        ("CBC", ["hemoglobin", "hematocrit", "wbc", "white blood", "platelet", "red blood cell", "rbc", "mcv", "mch", "rdw", "neutrophil", "lymphocyte", "monocyte", "eosinophil", "basophil", "band", "blast"]),
        ("Renal/Electrolytes", ["creatinine", "urea", "bun", "sodium", "potassium", "chloride", "bicarbonate", "anion gap", "phosphat", "magnesium", "calcium", "uric acid"]),
        ("Liver Function", ["alt", "ast", "alp", "alkaline phosphatase", "bilirubin", "albumin", "total protein", "ggt", "ldh", "amylase", "lipase"]),
        ("Coagulation", ["inr", "fibrinogen", "d-dimer", "thrombin", " pt ", "ptt", "aptt"]),
        ("Glycaemic", ["glucose", "hba1c", "hemoglobin a1c"]),
        ("ABG/Lactate", ["ph", "pco2", "po2", "base excess", "lactate", "o2 saturation", "oxygen saturation", "fio2", "peep", "tidal"]),
        ("Cardiac Enzymes", ["troponin", "ck-mb", "bnp", "pro-bnp", "pro bnp"]),
        ("Thyroid", ["tsh", "free t4", "free t3", "thyroxine"]),
        ("Lipid Profile", ["cholesterol", "triglyceride", "ldl", "hdl", "vldl"]),
        ("Microbiology/Other", ["culture", "sensitivity", "organism", "bacteria"]),
    ]

    def _fmt(rec):
        v = rec.get("valuenum") if rec.get("valuenum") is not None else rec.get("value", "?")
        u = rec.get("valueuom") or ""
        return f"{v} {u}".strip()

    def _flag(recs):
        for r in recs:
            if r.get("flag"):
                return r.get("flag", "abnormal")
        return None

    by_test: dict = defaultdict(list)
    for l in sorted(labs, key=lambda x: x.get("charttime") or ""):
        label = l.get("label") or f"itemid={l.get('itemid')}"
        by_test[label].append(l)

    cat_buckets: dict = {c: [] for c, _ in CATEGORIES}
    cat_buckets["Other"] = []

    for label, recs in by_test.items():
        ll = " " + label.lower() + " "
        # skip pure metadata / artefact labels
        if any(art in ll.strip() for art in ARTEFACT_LABELS):
            continue
        placed = False
        for cat_name, keywords in CATEGORIES:
            if any(kw in ll for kw in keywords):
                cat_buckets[cat_name].append((label, recs))
                placed = True
                break
        if not placed:
            cat_buckets["Other"].append((label, recs))

    sentences = []
    for cat_name, _ in CATEGORIES + [("Other", [])]:
        items = cat_buckets.get(cat_name, [])
        if not items:
            continue
        parts = []
        for label, recs in sorted(items, key=lambda x: x[0]):
            first, last = recs[0], recs[-1]
            fv = _fmt(first)
            lv = _fmt(last)
            flag = _flag(recs)
            if len(recs) == 1:
                val_str = fv
            else:
                val_str = f"{fv}→{lv}"
            if flag:
                parts.append(f"{label} {val_str} ({flag})")
            else:
                parts.append(f"{label} {val_str}")
        if parts:
            sentences.append(f"{cat_name}: " + "; ".join(parts) + ".")
    return " ".join(sentences) if sentences else "No laboratory investigations available."


def _has_real_clinical_data(hadm_id: int) -> bool:
    """True if real MIMIC clinical rows exist for this admission. Used to block
    discharge-summary generation for patients with no loaded data, so a fabricated
    (synthetic-fallback) summary can never reach a doctor."""
    from .cloud_sql_db import get_engine as _get_engine
    from sqlalchemy import text as _t
    try:
        with _get_engine().connect() as conn:
            n = conn.execute(_t(
                "SELECT (SELECT COUNT(*) FROM ap_chartevents WHERE hadm_id=:h) + "
                "       (SELECT COUNT(*) FROM ap_labevents  WHERE hadm_id=:h)"
            ), {"h": hadm_id}).scalar()
        return bool(n and n > 0)
    except Exception:
        return False


def _ews_overlay_lines(hadm_id: int) -> list:
    """Pull EWS-generated clinical activity (NOT present in MIMIC) so it flows into
    the discharge summary with explicit ward provenance. Covers NEWS2 escalations,
    Drug-Lab safety actions (NABH DL2 trail), CCU->GW step-down, and the nurse
    observation window. Read-only on the shared Cloud SQL DB; degrades gracefully."""
    from .cloud_sql_db import get_engine as _get_engine
    from sqlalchemy import text as _text
    try:
        with _get_engine().connect() as conn:
            esc = conn.execute(_text("""
                SELECT escalated_at, news2_score, level, observations, interventions,
                       status, resolution_notes
                FROM ews_escalations WHERE hadm_id = :h ORDER BY escalated_at
            """), {"h": hadm_id}).fetchall()
            dl = conn.execute(_text("""
                SELECT recorded_at, rule_name, severity, action_taken, justification,
                       recorded_by, cosigned_by
                FROM ews_drug_lab_actions WHERE hadm_id = :h ORDER BY recorded_at
            """), {"h": hadm_id}).fetchall()
            tr = conn.execute(_text("""
                SELECT submitted_at, rationale, news2_at_submit, stable_window_hours,
                       target_ward, status, decided_by
                FROM ews_ccu_transfers WHERE hadm_id = :h ORDER BY submitted_at
            """), {"h": hadm_id}).fetchall()
            vit = conn.execute(_text("""
                SELECT COUNT(*), MIN(chart_time), MAX(chart_time),
                       MIN(spo2), MAX(heart_rate), MAX(resp_rate), MIN(sbp), MAX(temperature)
                FROM ews_vitals_timeseries WHERE hadm_id = :h
            """), {"h": hadm_id}).fetchone()
    except Exception as _e:
        return ["\n[WARD-GENERATED — EWS]", f"  EWS overlay unavailable ({_e})"]

    out = ["\n[WARD-GENERATED — EWS] — Early-warning ward activity "
           "(provenance: Foqal EWS, not MIMIC source data)"]
    if vit and vit[0]:
        out.append(f"  Ward observation window: {vit[0]} nurse-charted vital sets "
                   f"({str(vit[1])[:16]} → {str(vit[2])[:16]})")
        out.append(f"    Extremes — min SpO2 {vit[3]}, max HR {vit[4]}, max RR {vit[5]}, "
                   f"min SBP {vit[6]}, max Temp {vit[7]}")
    else:
        out.append("  Ward observation window: no nurse-charted vitals recorded")
    out.append(f"  NEWS2 escalations: {len(esc)}")
    for e in esc:
        out.append(f"    - {str(e[0])[:16]} NEWS2={e[1]} [{e[2]}] status={e[5]}")
        if e[3]: out.append(f"        Obs: {e[3]}")
        if e[4]: out.append(f"        Intervention: {e[4]}")
        if e[6]: out.append(f"        Resolution: {e[6]}")
    out.append(f"  Drug–Lab safety actions (NABH DL2): {len(dl)}")
    for d in dl:
        out.append(f"    - {str(d[0])[:16]} {d[1]} [{d[2]}] action={d[3]} by {d[5]}"
                   + (f", cosigned {d[6]}" if d[6] else ""))
        if d[4]: out.append(f"        Justification: {d[4]}")
    out.append(f"  CCU→GW step-down events: {len(tr)}")
    for t in tr:
        out.append(f"    - {str(t[0])[:16]} → {t[4]} NEWS2@submit={t[2]} "
                   f"stable {t[3]}h status={t[5]}" + (f" by {t[6]}" if t[6] else ""))
        if t[1]: out.append(f"        Rationale: {t[1]}")
    return out


def build_clinical_context(hadm_id: int, data: Dict[str, Any]) -> str:
    """
    Build a compact, clinically summarised context for the LLM.
    Key principle: summarise trends instead of dumping raw rows.
    """
    from collections import defaultdict
    adm = data.get("admission") or {}
    pat = data.get("patient") or {}
    lines = []

    # ── Patient & Admission ────────────────────────────────────────────────────
    admit_date = (adm.get("admittime") or "N/A")[:10]
    disch_date = (adm.get("dischtime") or "N/A")[:10]
    lines.append("[PATIENT & ADMISSION]")
    lines += [
        f"  Name:            {pat.get('full_name') or 'Not recorded'}",
        f"  Age / Gender:    {pat.get('anchor_age') or '?'} yrs / {pat.get('gender') or '?'}",
        f"  Blood Group:     {pat.get('blood_group') or 'Not recorded'}",
        f"  Ward:            {pat.get('ward') or 'Not recorded'}",
        f"  HADM ID:         {hadm_id}",
        f"  Admission Date:  {admit_date}",
        f"  Discharge Date:  {disch_date}",
        f"  Admission Type:  {adm.get('admission_type') or 'N/A'}",
        f"  From:            {adm.get('admission_location') or 'N/A'}",
        f"  Discharged To:   {adm.get('discharge_location') or 'N/A'}",
        f"  Marital Status:  {adm.get('marital_status') or 'N/A'}",
        f"  Expired in stay: {'YES' if adm.get('hospital_expire_flag') == 1 else 'No'}",
    ]

    # ── Diagnoses ─────────────────────────────────────────────────────────────
    diags = data.get("diagnoses") or []
    lines.append("\n[DIAGNOSES] — Working diagnosis & past medical history")
    if diags:
        lines.append(f"  {len(diags)} diagnoses documented:")
        for d in sorted(diags, key=lambda x: x.get("seq_num") or 99):
            title = d.get("long_title") or ""
            code  = d.get("icd_code") or ""
            tag   = "PRIMARY" if d.get("seq_num") == 1 else f"  #{d.get('seq_num','-')}"
            if title:
                lines.append(f"    {tag}: {title}")
            else:
                lines.append(f"    {tag}: [description not available — code {code}]")
    else:
        lines.append("  Data not available — Working diagnosis cannot be determined from source data.")

    # ── MIMIC Discharge Note (mimiciv_note module — Pass 1 primary document) ────
    discharge_note_text = data.get("discharge_note_text")
    if discharge_note_text:
        lines.append("\n[DISCHARGE NOTE — MIMIC-IV]")
        # Truncate to 8000 chars to stay within Pass 1 context budget
        note_excerpt = discharge_note_text[:8000]
        if len(discharge_note_text) > 8000:
            note_excerpt += "\n[... note truncated at 8000 chars ...]"
        lines.append(note_excerpt)

    # ── Clinical Notes ─────────────────────────────────────────────────────────
    notes = sorted(data.get("noteevents") or [], key=lambda n: n.get("charttime") or "")
    lines.append(f"\n[CLINICAL NOTES]")
    if notes:
        lines[-1] += f" — {len(notes)} notes, showing first 4"
        for n in notes[:4]:
            txt = (n.get("text") or "").strip()
            lines.append(f"  [{n.get('note_type','N/A')}]  {(n.get('charttime') or 'N/A')[:10]}")
            lines.append(f"  {txt[:1500]}{'...' if len(txt) > 1500 else ''}")
            lines.append("")
    else:
        lines.append("  Data not available")

    # ── Procedures ────────────────────────────────────────────────────────────
    procs = data.get("procedures_icd") or []
    lines.append("\n[PROCEDURES PERFORMED]")
    if procs:
        seen_p: set = set()
        proc_lines: list = []
        for p in sorted(procs, key=lambda x: x.get("chartdate") or "", reverse=True):
            title     = (p.get("long_title") or "").strip()
            code      = p.get("icd_code") or "?"
            version   = p.get("icd_version") or ""
            date      = p.get("chartdate") or "N/A"
            if title:
                key  = title
                line = f"  - {title}  (date: {date})"
            else:
                key  = f"{code}_{version}"
                line = f"  - Procedure [description not available — code {code}]  (date: {date})"
            if key not in seen_p:
                seen_p.add(key)
                proc_lines.append(line)
                if len(proc_lines) >= 10:
                    break
        lines.extend(proc_lines)
    else:
        lines.append("  Data not available")

    # ── ICU Procedures (procedureevents) ─────────────────────────────────────
    procevts = data.get("procevents") or []
    lines.append(f"\n[ICU PROCEDURE EVENTS]")
    if procevts:
        lines[-1] += f" — {len(procevts)} events"
        cats: set = set()
        for p in procevts:
            c = p.get("ordercategoryname") or p.get("ordercategorydescription") or ""
            if c:
                cats.add(c)
        for c in sorted(cats)[:10]:
            lines.append(f"  - {c}")
    else:
        lines.append("  Data not available")

    # ── Key ICU clinical timestamps (datetimeevents) ───────────────────────────
    dtevts = data.get("dtevents") or []
    lines.append(f"\n[ICU DATETIME EVENTS]")
    if dtevts:
        lines[-1] += f" — {len(dtevts)} events"
        seen_dt: dict = {}
        for d in sorted(dtevts, key=lambda x: x.get("charttime") or ""):
            label = d.get("label") or f"itemid={d.get('itemid')}"
            t     = (d.get("charttime") or "")[:16].replace("T", " ")
            val   = (str(d.get("value") or ""))[:10]
            if label not in seen_dt:
                seen_dt[label] = True
                lines.append(f"  {t} | {label}: {val}")
        if len(dtevts) > len(seen_dt):
            lines.append(f"  ({len(dtevts) - len(seen_dt)} duplicate readings omitted)")
    else:
        lines.append("  Data not available")

    # ── ICU Stays ─────────────────────────────────────────────────────────────
    icu = data.get("icustays") or []
    lines.append(f"\n[ICU STAYS]")
    if icu:
        lines[-1] += f" — {len(icu)} stay(s)"
        for s in icu:
            los_raw = s.get('los')
            los_str = f"{float(los_raw):.2f}" if los_raw is not None else "?"
            lines.append(
                f"  {s.get('first_careunit','?')} → {s.get('last_careunit','?')} | "
                f"LOS {los_str} days | "
                f"{(s.get('intime','N/A'))[:10]} to {(s.get('outtime','N/A'))[:10]}"
            )
    else:
        lines.append("  Data not available")

    # ── Ward movement timeline (transfers) ────────────────────────────────────
    trns = data.get("transfers") or []
    lines.append(f"\n[TRANSFERS / WARD MOVEMENT]")
    if trns:
        lines[-1] += f" — {len(trns)} events"
        for t in sorted(trns, key=lambda x: x.get("intime") or ""):
            unit    = t.get("careunit") or "N/A"
            etype   = (t.get("eventtype") or "").capitalize()
            intime  = (t.get("intime") or "N/A")[:10]
            outtime = (t.get("outtime") or "")[:10]
            lines.append(f"  {intime} | {etype}: {unit}" + (f" → {outtime}" if outtime else ""))
    else:
        lines.append("  Data not available")

    # ── Vital Signs (chartevents) ─────────────────────────────────────────────
    chart = data.get("chartevents") or []
    lines.append(f"\n[VITAL SIGNS]")
    if chart:
        lines.append(f"  {_vitals_to_prose(chart)}")
    else:
        lines.append("  Data not available — DO NOT WRITE ANY VITAL SIGN VALUES.")

    # ── Lab Results ───────────────────────────────────────────────────────────
    labs = data.get("labevents") or []
    lines.append(f"\n[LAB RESULTS]")
    if labs:
        lines[-1] += f" — {len(labs)} records"
        lines.append(f"  {_labs_to_prose(labs)}")
    else:
        lines.append("  Data not available — DO NOT WRITE ANY LAB VALUES.")

    # ── Microbiology ──────────────────────────────────────────────────────────
    micro = data.get("microevents") or []
    lines.append(f"\n[MICROBIOLOGY CULTURES]")
    if micro:
        cultures: dict = defaultdict(list)
        for m in micro:
            key = f"{(m.get('charttime') or '')[:10]} | {m.get('spec_type_desc','N/A')} | {m.get('org_name') or 'No growth'}"
            if m.get("ab_name"):
                cultures[key].append(f"    {m.get('ab_name')} → {m.get('interpretation','N/A')}")
            elif key not in cultures:
                cultures[key] = []
        for key, sens in cultures.items():
            lines.append(f"  {key}")
            lines += sens[:6]
    else:
        lines.append("  Data not available — DO NOT WRITE ANY CULTURE OR SENSITIVITY RESULTS.")

    # ── Medications (prescriptions) ───────────────────────────────────────────
    rxs = data.get("prescriptions") or []
    lines.append(f"\n[MEDICATIONS / PRESCRIPTIONS]")
    if rxs:
        lines[-1] += f" — {len(rxs)} records"
        # Include ALL routes (IV, oral, SC, etc.) — ICU patients have mostly IV medications
        seen_drugs: set = set()
        all_meds: list = []
        for p in sorted(rxs, key=lambda x: x.get("starttime") or "", reverse=True):
            drug  = (p.get("drug") or "Unknown").strip()
            dose  = f"{p.get('dose_val_rx','')} {p.get('dose_unit_rx','')}".strip() or "N/A"
            route = (p.get("route") or "").strip()
            start = (p.get("starttime") or "")[:10]
            stop  = (p.get("stoptime") or "")[:10]
            if drug not in seen_drugs:
                seen_drugs.add(drug)
                all_meds.append({"drug": drug, "dose": dose, "route": route, "start": start, "stop": stop})
            if len(all_meds) >= 30:
                break
        if all_meds:
            lines.append(f"  All medications ({len(all_meds)} unique drugs listed, most recent first):")
            for m in all_meds:
                date_range = f"{m['start']}" + (f" – {m['stop']}" if m['stop'] and m['stop'] != m['start'] else "")
                lines.append(f"    {m['drug']} | {m['dose']} | {m['route']} | {date_range}")
    else:
        lines.append("  Data not available — DO NOT LIST ANY DRUGS.")

    # ── ICU Fluids I/O ────────────────────────────────────────────────────────
    inputs  = data.get("inputevents")  or []
    outputs = data.get("outputevents") or []
    lines.append(f"\n[ICU FLUIDS I/O]")
    if inputs or outputs:
        lines[-1] += f" — {len(inputs)} input events, {len(outputs)} output events"
        if inputs:
            input_labels = {i.get("label") or f"itemid={i.get('itemid')}" for i in inputs}
            lines.append(f"  Input types: {', '.join(sorted(input_labels)[:8])}")
        if outputs:
            output_labels = {o.get("label") or f"itemid={o.get('itemid')}" for o in outputs}
            lines.append(f"  Output types: {', '.join(sorted(output_labels)[:6])}")
    else:
        lines.append("  Data not available")

    # ── ICU Nutrition / Ingredient Events ─────────────────────────────────────
    ings = data.get("ingredients") or []
    lines.append(f"\n[ICU NUTRITION / INGREDIENT EVENTS]")
    if ings:
        ing_map: dict = {}
        for i in sorted(ings, key=lambda x: x.get("starttime") or ""):
            label = i.get("label") or f"itemid={i.get('itemid')}"
            amt   = i.get("amount")
            uom   = i.get("amountuom") or ""
            if label not in ing_map and amt is not None:
                ing_map[label] = f"{amt} {uom}".strip()
        if ing_map:
            lines[-1] += f" — {len(ings)} events, {len(ing_map)} components"
            for lbl, val in list(ing_map.items())[:10]:
                lines.append(f"  {lbl}: {val}")
        else:
            lines.append("  Data not available")
    else:
        lines.append("  Data not available")

    # ── Pharmacy ──────────────────────────────────────────────────────────────
    pharmacy = data.get("pharmacy") or []
    lines.append(f"\n[PHARMACY DISPENSING]")
    if pharmacy:
        dispensed: dict = {}
        for p in sorted(pharmacy, key=lambda x: x.get("starttime") or ""):
            med  = (p.get("medication") or "Unknown").strip()
            freq = p.get("frequency") or ""
            d24  = p.get("doses_per_24_hrs")
            disp = p.get("dispensation") or ""
            if med not in dispensed:
                dispensed[med] = {"freq": freq, "d24": d24, "disp": disp}
        lines[-1] += f" — {len(pharmacy)} records, {len(dispensed)} medications"
        for med, info in list(dispensed.items())[:15]:
            parts = [med]
            if info["freq"]:
                parts.append(info["freq"])
            if info["d24"]:
                parts.append(f"{info['d24']} doses/24h")
            if info["disp"]:
                parts.append(f"dispensed: {info['disp']}")
            lines.append(f"  {' | '.join(parts)}")
    else:
        lines.append("  Data not available")

    # ── Physician Orders (POE) ────────────────────────────────────────────────
    poe = data.get("poe") or []
    lines.append(f"\n[PHYSICIAN ORDERS (POE)]")
    if poe:
        # Only skip purely administrative order types; include clinical ones (IV, Respiratory, Nutrition, etc.)
        poe_skip = {"Lab", "Blood Bank"}
        included = [p for p in poe if p.get("order_type") not in poe_skip]
        if included:
            lines[-1] += f" — {len(included)} orders"
            order_cats: dict = defaultdict(list)
            for p in sorted(included, key=lambda x: x.get("ordertime") or ""):
                otype  = p.get("order_type") or "Other"
                osub   = (p.get("order_subtype") or "").strip()
                otime  = (p.get("ordertime") or "")[:10]
                entry  = f"{otime} {osub}".strip() if osub else otime
                order_cats[otype].append(entry)
            for otype, items in sorted(order_cats.items()):
                sample = list(dict.fromkeys(items))[:5]
                lines.append(f"  {otype}: {'; '.join(sample)}" +
                              (f" (+{len(items)-5} more)" if len(items) > 5 else ""))
        else:
            lines.append(f"  {len(poe)} orders (lab/blood bank only)")
    else:
        lines.append("  Data not available")

    # ── Uploaded Files ────────────────────────────────────────────────────────
    uploaded_files = data.get("uploaded_files") or []
    lines.append(f"\n[UPLOADED FILES]")
    if uploaded_files:
        for f in uploaded_files:
            lines.append(f"  - {f.get('original_name') or f.get('file_type','unknown')}  ({f.get('file_type','')}, {f.get('row_count',0)} rows)")
    else:
        lines.append("  No files uploaded")

    # ── OMR outpatient measurements ───────────────────────────────────────────
    omr = data.get("omr") or []
    lines.append(f"\n[OUTPATIENT MEASUREMENTS (OMR)]")
    if omr:
        omr_map: dict = {}
        for o in sorted(omr, key=lambda x: x.get("chartdate") or ""):
            name = (o.get("result_name") or "").strip()
            val  = (o.get("result_value") or "").strip()
            if name and val:
                omr_map[name] = val
        if omr_map:
            lines[-1] += f" — {len(omr)} records"
            for name, val in list(omr_map.items())[:10]:
                lines.append(f"  {name}: {val}")
        else:
            lines.append("  Data not available")
    else:
        lines.append("  Data not available")

    # ── HCPCS Billed Items ────────────────────────────────────────────────────
    hcpcs = data.get("hcpcsevents") or []
    lines.append(f"\n[HCPCS BILLED ITEMS]")
    if hcpcs:
        hcpcs_set: set = set()
        for h in hcpcs:
            desc = h.get("short_description") or h.get("hcpcs_cd") or ""
            if desc:
                hcpcs_set.add(desc)
        lines[-1] += f" — {len(hcpcs)} events"
        for d in sorted(hcpcs_set)[:8]:
            lines.append(f"  - {d}")
    else:
        lines.append("  Data not available")

    # ── Ward-generated EWS overlay (escalations, drug-lab, step-down) ──────────
    # Makes the EWS clinical work flow end-to-end into the discharge summary.
    try:
        lines += _ews_overlay_lines(hadm_id)
    except Exception:
        pass

    return "\n".join(lines)


# ── MIMIC data routes — proxied to data server (port 7016) ───────────────────
# These thin wrappers keep the same URL surface so the frontend doesn't change.

# Short timeout for fast endpoints (admissions list, cache stats).
# Long timeout for patient display — first open triggers BigQuery fetch.
_data_client = httpx.AsyncClient(
    base_url=DATA_SERVER,
    timeout=httpx.Timeout(connect=5.0, read=300.0, write=10.0, pool=5.0),
)

# Pass 1 pre-computation cache — keyed by hadm_id.
# Stores {"pass1_json": str, "clinical_context": str} so generate_summary can skip Pass 1
# if the same clinical context is already extracted.
_pass1_cache: dict[int, dict] = {}


def _data_server_unavailable(exc: Exception):
    raise HTTPException(
        status_code=503,
        detail=f"Data server unavailable — try again in a moment. ({type(exc).__name__})",
    )


async def _enrich_icd(rows: list, table_type: str) -> list:
    """Call data server to fill in long_title for uploaded ICD rows missing descriptions."""
    if not rows:
        return rows
    needs_lookup = any(not r.get("long_title") and r.get("icd_code") for r in rows)
    if not needs_lookup:
        return rows
    try:
        r = await _data_client.post(
            "/api/icd/lookup",
            json={"rows": rows, "table_type": table_type},
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
        )
        if r.status_code == 200:
            return r.json().get("rows", rows)
    except Exception as exc:
        log.warning(f"ICD title enrichment failed ({table_type}): {exc}")
    return rows


async def _enrich_labevents(rows: list) -> list:
    """Call data server to fill in label/fluid/category for uploaded labevents rows missing a label."""
    if not rows:
        return rows
    needs_lookup = any(not r.get("label") and r.get("itemid") for r in rows)
    if not needs_lookup:
        return rows
    try:
        r = await _data_client.post(
            "/api/labitems/lookup",
            json={"rows": rows},
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
        )
        if r.status_code == 200:
            return r.json().get("rows", rows)
    except Exception as exc:
        log.warning(f"Lab item label enrichment failed: {exc}")
    return rows


@app.get("/api/hadm_ids")
async def get_all_hadm_ids():
    try:
        r = await _data_client.get("/api/hadm_ids")
        return r.json()
    except Exception as exc:
        _data_server_unavailable(exc)


@app.get("/api/cache/stats")
async def get_cache_stats():
    try:
        r = await _data_client.get("/api/cache/stats")
        return r.json()
    except Exception as exc:
        _data_server_unavailable(exc)

@app.get("/api/cache/patients")
async def get_cached_patients():
    try:
        r = await _data_client.get("/api/cache/patients")
        return r.json()
    except Exception:
        return {"active": []}


@app.get("/api/mimic/admissions")
async def get_mimic_admissions(page: int = 1, per_page: int = 20, search: str = ""):
    try:
        r = await _data_client.get(
            "/api/mimic/admissions",
            params={"page": page, "per_page": per_page, "search": search},
        )
        return r.json()
    except Exception as exc:
        _data_server_unavailable(exc)


@app.get("/api/encounters/{hadm_id}/patient_data")
async def get_patient_data(hadm_id: int, source: str = "bq"):
    if source == "db":
        data = fetch_all_patient_data(hadm_id)
        if "error" in data:
            raise HTTPException(status_code=404, detail=data["error"])
        encounter = gdb.get_encounter_by_hadm(hadm_id)
        if not encounter:
            encounter = gdb.create_encounter(hadm_id, status="Pending Ingestion")
        return {"hadm_id": hadm_id, "source": source, "encounter": encounter, **data}

    try:
        r = await _data_client.get(f"/api/patient/{hadm_id}/display")
    except Exception as exc:
        _data_server_unavailable(exc)
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail=r.json().get("detail", "Not found"))
    data = r.json()
    encounter = gdb.get_encounter_by_hadm(hadm_id)
    if not encounter:
        encounter = gdb.create_encounter(hadm_id, status="Pending Ingestion")

    # NOTE: uploaded clinical rows are NOT merged here.
    # The frontend fetches them separately via /uploaded_clinical_data and merges
    # with _uploaded=true tag so they can be identified, badged, and deleted.
    # Merging server-side would strip the tag and make uploaded rows look like MIMIC data.
    # generate_summary has its own separate merge for LLM context.

    return {"hadm_id": hadm_id, "source": source, "encounter": encounter, **data}


@app.get("/api/patient/{hadm_id}/tab/{tab_name}")
async def get_patient_tab(hadm_id: int, tab_name: str):
    try:
        r = await _data_client.get(f"/api/patient/{hadm_id}/tab/{tab_name}")
    except Exception as exc:
        _data_server_unavailable(exc)
        
    data = {}
    if r.status_code == 200:
        data = r.json()

    # Merge uploaded clinical files for this specific tab
    try:
        clinical = await run_in_threadpool(gdb.fetch_all_uploaded_clinical_data, hadm_id)
        if tab_name == "labevents" and clinical.get("labevents"):
            data["labevents"] = data.get("labevents", []) + clinical["labevents"]
            # Auto-fill label/fluid/category for uploaded lab rows missing a label
            data["labevents"] = await _enrich_labevents(data["labevents"])
        elif tab_name == "prescriptions" and clinical.get("prescriptions"):
            data["prescriptions"] = data.get("prescriptions", []) + clinical["prescriptions"]
        elif tab_name == "emar" and clinical.get("emar"):
            data["emar"] = data.get("emar", []) + clinical["emar"]
        elif tab_name == "chartevents" and clinical.get("chartevents"):
            data["chartevents"] = data.get("chartevents", []) + clinical["chartevents"]
    except Exception as exc:
        log.warning(f"Failed to merge uploaded clinical data for {hadm_id} tab {tab_name}: {exc}")

    if not data and r.status_code == 400:
        raise HTTPException(status_code=400, detail=r.json().get("detail"))
        
    return data


@app.get("/api/encounters/{hadm_id}/clinical_context")
async def get_clinical_context(hadm_id: int, source: str = "bq"):
    # Only return stored clinical_context — never re-fetch from BigQuery
    enc = gdb.get_encounter_by_hadm(hadm_id)
    if enc:
        summary = gdb.get_summary_by_encounter(enc["id"])
        if summary and summary.get("clinical_context"):
            ctx = summary["clinical_context"]
            return {
                "hadm_id": hadm_id, "source": "cached",
                "clinical_context": ctx,
                "table_log": [],
                "char_count": len(ctx),
            }
    return {
        "hadm_id": hadm_id, "source": "none",
        "clinical_context": "",
        "table_log": [],
        "char_count": 0,
    }


# ── Gemini call helper (module-level so regenerate_section can use it) ────────
def _call_gemini(prompt_text: str, system_instruction: str | None = None,
                 thinking_budget: int | None = None) -> tuple:
    """Returns (generated_text, error_message). Retries up to 4 times on transient errors."""
    if not gemini_client:
        return None, "GEMINI_API_KEY not set. Add your key to backend/.env and restart the server."
    from google.genai import types as _gtypes
    _cfg_kw: dict = {}
    if system_instruction:
        _cfg_kw["system_instruction"] = system_instruction
    if thinking_budget is not None:
        _cfg_kw["thinking_config"] = _gtypes.ThinkingConfig(thinking_budget=thinking_budget)
    _config = _gtypes.GenerateContentConfig(**_cfg_kw) if _cfg_kw else None
    for _attempt, _wait in enumerate([0, 5, 15, 30], 1):
        if _wait:
            log.info(f"Gemini retry {_attempt}/4 — waiting {_wait}s…")
            time.sleep(_wait)
        try:
            log.info(f"Calling Gemini ({GEMINI_MODEL}) attempt {_attempt}…")
            resp = gemini_client.models.generate_content(
                model=GEMINI_MODEL, contents=prompt_text,
                **({"config": _config} if _config else {}),
            )
            if not resp.text:
                raise ValueError("Empty response")
            log.info(f"Gemini returned {len(resp.text):,} chars")
            return resp.text, None
        except Exception as e:
            err = str(e)
            if "503" in err or "429" in err or "rate" in err.lower() or "UNAVAILABLE" in err:
                log.warning(f"Gemini transient error attempt {_attempt}: {e}")
                continue
            log.error(f"Gemini non-retryable: {e}")
            return None, err
    return None, "Max retries exceeded"


def _stream_gemini_pass2(prompt_text: str, system_instruction: str, thinking_budget: int,
                          chunk_cb) -> tuple[str | None, str | None]:
    """Run Gemini Pass 2 with streaming. chunk_cb(text) called for each token chunk.
    Returns (full_text, error). Called from a thread via run_in_threadpool."""
    if not gemini_client:
        return None, "GEMINI_API_KEY not set"
    from google.genai import types as _gtypes
    _config = _gtypes.GenerateContentConfig(
        system_instruction=system_instruction,
        thinking_config=_gtypes.ThinkingConfig(thinking_budget=thinking_budget),
    )
    try:
        parts = []
        for chunk in gemini_client.models.generate_content_stream(
            model=GEMINI_MODEL, contents=prompt_text, config=_config,
        ):
            if chunk.text:
                parts.append(chunk.text)
                chunk_cb(chunk.text)
        full = "".join(parts)
        if not full:
            return None, "Empty streaming response"
        log.info(f"Gemini stream complete: {len(full):,} chars")
        return full, None
    except Exception as e:
        log.error(f"Gemini stream error: {e}")
        return None, str(e)


# ── Generate Summary endpoint ─────────────────────────────────────────────────
class GenerateSummaryRequest(BaseModel):
    discharge_type:    Optional[str] = None  # Standard | LAMA | DAMA | Death | Referral
    rejection_context: Optional[str] = None  # injected by trigger_regeneration
    nyha_class:        Optional[str] = None


import re as _re_module

def _to_labeled_documents(ctx: str) -> str:
    """Convert [SECTION] headers → [DOCUMENT N — Section Name] format for Pass 1 prompt."""
    parts = _re_module.split(r'\n(?=\[)', ctx.strip())
    out = []
    for i, part in enumerate(parts, 1):
        m = _re_module.match(r'\[([^\]]+)\](.*)', part, _re_module.DOTALL)
        if m:
            name = m.group(1).strip().title()
            body = m.group(2).strip()
            out.append(f"[DOCUMENT {i} — {name}]\n{body}")
        else:
            out.append(part)
    return "\n\n".join(out)


# Module-level so both precompute_pass1 and generate_summary can reference it
_PASS1_SYSTEM = """You are a clinical data extraction engine for an Indian cardiology hospital.
Your ONLY job is to extract facts from the provided clinical documents and return them as structured JSON.
You do not generate narrative. You do not infer. You do not extrapolate.
If a fact is not present in the documents, return null for that field.

EXTRACTION RULES — READ CAREFULLY:
A. all_labs: Extract EVERY lab test result from [LAB RESULTS] and [OUTPATIENT MEASUREMENTS] documents that has an actual numeric or descriptive clinical value. Format: {"Test Name": "value unit"} or {"Test Name": "value unit (abnormal)"}. Example: {"Hemoglobin": "9.6 g/dL", "Basophils": "0.1 %", "Anion Gap": "17 mEq/L (abnormal)", "Potassium": "3.3 mEq/L"}. STRICT EXCLUSIONS — do NOT include: (1) entries where the value is None, null, empty, "N/A", or missing; (2) internal lab system codes or order status markers such as HOLD, DONE, RFXUCU, XUCU, PAN3, or specimen tube colour references (Blue Top Hold, Red Top Hold, Light Green Top Hold, etc.) — these are administrative, not clinical values; (3) specimen tracking labels.
B. clinical_notes_text: Copy the full text from [CLINICAL NOTES] and [DISCHARGE NOTE — MIMIC-IV] documents verbatim (up to 3000 characters). This is used for the HPI and hospital course narrative.
C. microbiology: Extract ONLY culture results where a specific organism was identified. COMPLETELY OMIT any specimen whose result is "No growth" — do not include it at all. Each entry: {specimen, organism, result_summary, sensitivity_key_findings}.
D. vital_signs_trend: Summarise the VITAL SIGNS document as a prose paragraph covering: all BP readings (with dates), HR trend, SpO2, temperature, RR over the hospital stay.
E. omr_measurements: Extract all values from [OUTPATIENT MEASUREMENTS (OMR)] as key-value pairs.
F. labs (named fields): Also populate the named lab fields below as a cross-reference — these are a subset of all_labs.
G. imaging_reports: From [PHYSICIAN ORDERS (POE)], [CLINICAL NOTES], and [DISCHARGE NOTE] documents, extract ALL imaging studies — X-rays, EKGs, CT scans, MRIs, ultrasounds, nuclear studies. For each entry: state the study type and date. If findings/results are documented, include them. If only an order exists with no report, write "Ordered [date] — report not available in source documents". Format as a prose paragraph. Return null if no imaging of any kind appears. Do NOT duplicate findings already captured in ecg_findings or echo fields.

Output format: Valid JSON matching the schema below. Nothing else. No preamble. No explanation. No markdown code blocks. Raw JSON only.

Schema:
{
  "patient": {
    "name": null, "age": null, "dob": null, "sex": null, "uhid": null,
    "admission_date": null, "discharge_date": null,
    "admission_mode": null,
    "referral_source": null,
    "attending_physician": null, "attending_mci_reg": null,
    "ward": null, "bed_number": null,
    "next_of_kin": {"name": null, "relationship": null, "contact": null},
    "insurance_tpa": null
  },
  "chief_complaint": null,
  "duration_of_symptoms": null,
  "hpi": null,
  "clinical_notes_text": null,
  "pmh": {
    "comorbidities": [], "prior_cardiac_interventions": [],
    "surgical_history": [], "allergies": [],
    "family_history": null,
    "smoking": null, "alcohol": null
  },
  "vitals_on_admission": {
    "bp_systolic": null, "bp_diastolic": null,
    "heart_rate": null, "rhythm": null,
    "spo2": null, "respiratory_rate": null,
    "temperature": null, "gcs": null,
    "jvp": null, "heart_sounds": null, "murmurs": null,
    "breath_sounds": null, "pedal_oedema": null
  },
  "vital_signs_trend": null,
  "all_labs": {},
  "labs": {
    "troponin_t_peak": null, "troponin_unit": null,
    "troponin_serial": [],
    "bnp_or_ntprobnp": null,
    "hemoglobin": null, "wbc": null, "platelets": null,
    "creatinine": null, "egfr": null, "urea": null,
    "sodium": null, "potassium": null, "magnesium": null,
    "hba1c": null, "fasting_glucose": null,
    "lipid_profile": {"ldl": null, "hdl": null, "triglycerides": null, "total_cholesterol": null},
    "inr": null, "pt": null
  },
  "microbiology": [],
  "omr_measurements": {},
  "ecg_findings": null,
  "imaging_reports": null,
  "echo": {"lvef_percent": null, "wall_motion_abnormality": null, "valvular_findings": null, "pericardial_findings": null},
  "cath_lab": {
    "lad_stenosis_percent": null, "lcx_stenosis_percent": null, "rca_stenosis_percent": null,
    "intervention_performed": null, "stent_details": null, "timi_flow_post": null,
    "chest_xray_findings": null
  },
  "risk_scores": {"grace_score": null, "grace_risk": null, "timi_score": null},
  "hospital_course": null,
  "complications": [],
  "procedures": [{"name": null, "date": null, "operator": null, "outcome": null, "icd_pcs_code": null}],
  "discharge_medications": [{"drug_name_source": null, "dose": null, "frequency": null, "route": null, "duration": null, "high_risk_flag": null}],
  "dapt_months": null,
  "stopped_medications": [],
  "discharge_diagnosis_clinical": null,
  "icd10_codes": [],
  "icd10_pcs_codes": [],
  "discharge_type": "Standard",
  "condition_at_discharge": null,
  "nyha_class": null,
  "discharge_vitals": {"bp_systolic": null, "bp_diastolic": null, "heart_rate": null, "spo2": null, "weight_kg": null},
  "followup": {
    "date": null, "physician": null, "clinic": null,
    "investigations_ordered": [],
    "diet_instructions": null,
    "activity_restrictions": null,
    "emergency_return_criteria": [],
    "warnings": []
  },
  "patient_acknowledgement": {"confirmed": false, "confirmed_by": null, "relationship_to_patient": null, "timestamp": null}
}"""


@app.post("/api/encounters/{hadm_id}/precompute")
async def precompute_pass1(hadm_id: int, background_tasks: BackgroundTasks):
    """
    Pre-run Pass 1 (fact extraction) in the background so generate_summary can skip it.
    Call this when the review screen opens. Returns immediately; Pass 1 runs async.
    """
    if hadm_id in _pass1_cache:
        return {"status": "already_cached"}

    async def _run():
        try:
            _long  = httpx.Timeout(connect=5.0, read=600.0, write=10.0, pool=5.0)
            _short = httpx.Timeout(connect=5.0, read=20.0,  write=10.0, pool=5.0)
            _ROUND1_TABS = ["prescriptions", "pharmacy", "labevents", "poe",
                            "fluids", "chartevents"]

            async def _fetch(path: str, timeout=None) -> dict:
                try:
                    r = await _data_client.get(path, timeout=timeout or _long)
                    if r.status_code == 200:
                        return r.json()
                except Exception as exc:
                    log.warning(f"precompute fetch {path}: {exc}")
                return {}

            round1 = await asyncio.gather(
                _fetch(f"/api/patient/{hadm_id}/display"),
                *[_fetch(f"/api/patient/{hadm_id}/tab/{t}") for t in _ROUND1_TABS],
            )
            data = round1[0]
            if "error" in data:
                log.warning(f"[precompute] patient {hadm_id} not found")
                return
            for tab_data in round1[1:]:
                data.update(tab_data)

            round2 = await asyncio.gather(
                _fetch(f"/api/patient/{hadm_id}/tab/procedureevents", timeout=_short),
            )
            for tab_data in round2:
                data.update(tab_data)

            data.setdefault("drg_codes",   data.get("drgcodes") or [])
            data.setdefault("microevents", data.get("microbiologyevents") or [])
            data.setdefault("procevents",  data.get("procedureevents") or [])

            try:
                uploaded = await run_in_threadpool(gdb.fetch_all_uploaded_clinical_data, hadm_id)
                _MERGE = [
                    ("procedures","procedures_icd"),("diagnoses","diagnoses"),
                    ("microbiology","microevents"),("icustays","icustays"),
                    ("transfers","transfers"),
                    ("labs","labevents"),
                    ("meds","prescriptions"),("pharmacy","pharmacy"),("poe","poe"),
                    ("fluids","inputevents"),("vitals","chartevents"),("icu","procevents"),
                ]
                for src, dst in _MERGE:
                    rows = uploaded.get(src, [])
                    if rows:
                        data[dst] = data.get(dst, []) + rows
                enriched = await asyncio.gather(
                    _enrich_icd(data.get("procedures_icd") or [], "procedures"),
                    _enrich_icd(data.get("diagnoses") or [], "diagnoses"),
                    _enrich_labevents(data.get("labevents") or []),
                )
                if data.get("procedures_icd"): data["procedures_icd"] = enriched[0]
                if data.get("diagnoses"):      data["diagnoses"]      = enriched[1]
                if data.get("labevents"):      data["labevents"]      = enriched[2]
            except Exception as exc:
                log.warning(f"[precompute] uploaded merge failed (non-fatal): {exc}")

            clinical_context = build_clinical_context(hadm_id, data)
            log.info(f"[precompute] context built for {hadm_id} ({len(clinical_context):,} chars) — running Pass 1")

            _labeled_docs = _to_labeled_documents(clinical_context)
            pass1_user_msg = (
                "Extract all clinical facts from the following documents for patient discharge summary generation.\n\n"
                f"Documents provided:\n\n{_labeled_docs}\n\n"
                "Return ONLY valid JSON matching the schema. No preamble. No explanation."
            )
            pass1_text, pass1_error = await run_in_threadpool(
                _call_gemini, pass1_user_msg, _PASS1_SYSTEM, 1024
            )
            if pass1_text:
                _pass1_cache[hadm_id] = {"pass1_json": pass1_text, "clinical_context": clinical_context}
                log.info(f"[precompute] Pass 1 cached for hadm_id={hadm_id}")
            else:
                log.warning(f"[precompute] Pass 1 failed for {hadm_id}: {pass1_error}")
        except Exception as exc:
            log.warning(f"[precompute] error for {hadm_id}: {exc}")

    background_tasks.add_task(_run)
    return {"status": "started"}


# ── Pass 3: True per-section verification pipeline ────────────────────────────
_PASS3_SECTION_LABELS = {
    "s1":  "Patient Demographics",
    "s2":  "Chief Complaint",
    "s3":  "History of Presenting Illness",
    "s4":  "Significant Past History",
    "s5":  "Examination Findings on Admission",
    "s6":  "Laboratory Investigations",
    "s7":  "Imaging & Procedure Findings",
    "s8":  "Working Diagnosis at Admission",
    "s9":  "Hospital Course",
    "s10": "Procedures Performed",
    "s11": "Discharge Medications",
    "s12": "Follow-up & Discharge Advice",
    "s13": "Discharge Diagnosis",
    "s14": "Condition at Discharge",
    "s15": "Patient Acknowledgement",
}

# Source fields from clinical_json that each section is authorised to use.
# The verifier receives EXACTLY these fields — GenerationSources ≡ VerificationSources.
_S_SOURCE_FIELDS: dict[str, list[str]] = {
    's1':  ['patient'],
    's2':  ['chief_complaint', 'duration_of_symptoms', 'patient',
            'clinical_notes_text', 'discharge_diagnosis_clinical', 'icd10_codes', 'pmh'],
    's3':  ['hpi', 'clinical_notes_text', 'hospital_course',
            'vital_signs_trend', 'risk_scores', 'labs'],
    's4':  ['pmh', 'icd10_codes'],
    's5':  ['vitals_on_admission', 'vital_signs_trend', 'omr_measurements'],
    's6':  ['all_labs', 'labs', 'ecg_findings', 'omr_measurements', 'microbiology'],
    's7':  ['echo', 'cath_lab', 'ecg_findings', 'imaging_reports'],
    's8':  ['discharge_diagnosis_clinical', 'icd10_codes', 'risk_scores'],
    's9':  ['hospital_course', 'clinical_notes_text', 'vital_signs_trend',
            'complications', 'procedures'],
    's10': ['procedures', 'cath_lab'],
    's11': ['discharge_medications', 'dapt_months', 'stopped_medications'],
    's12': ['followup', 'clinical_notes_text'],
    's13': ['discharge_diagnosis_clinical', 'icd10_codes', 'icd10_pcs_codes'],
    's14': ['condition_at_discharge', 'discharge_vitals', 'nyha_class',
            'omr_measurements', 'discharge_type', 'vital_signs_trend'],
    's15': ['patient_acknowledgement'],
}

def _build_section_source(cj: dict, sec: str) -> str:
    """Serialise only the source fields allowed for a section, with field-level truncation."""
    import json as _j
    # all_labs gets a higher char limit because it may contain many lab names
    # that the generated text references — truncating too early causes false positives
    _FIELD_LIMIT = {"all_labs": 4000}
    _DEFAULT_LIMIT = 2000
    fields = _S_SOURCE_FIELDS.get(sec, [])
    parts  = []
    for f in fields:
        val = cj.get(f)
        if val is None or val == {} or val == [] or val == "":
            continue
        _limit = _FIELD_LIMIT.get(f, _DEFAULT_LIMIT)
        if isinstance(val, str):
            v_str = val[:_limit] + ("…[truncated]" if len(val) > _limit else "")
        else:
            v_str = _j.dumps(val, ensure_ascii=False)
            if len(v_str) > _limit:
                v_str = v_str[:_limit] + "…[truncated]"
        parts.append(f"{f}: {v_str}")
    if not parts:
        return "SOURCE DATA: (no data available for this section)"
    return "SOURCE DATA:\n" + "\n".join(parts)

_PASS3_SYSTEM = """You are a clinical accuracy auditor for an NABH-accredited Indian hospital.

Each section of the AI-generated discharge summary is shown with its own SOURCE DATA block. Verify each section INDEPENDENTLY against only the source data provided for THAT section.

TIER DEFINITIONS:
T1 — Minor: Wrong date format, wrong unit symbol (mg vs mcg), clinically meaningless style difference. Clinical meaning is fully unchanged.
T2 — Medication Error: Wrong drug name, wrong dose, wrong frequency, wrong route, wrong duration. Compare EXACTLY against the source medications list.
T3 — Critical: Wrong diagnosis (directly contradicts ICD codes in source), missed allergy when same drug is prescribed, hallucinated lab value not in source, fabricated vital sign not in source, wrong procedure, fabricated finding, wrong discharge condition.
OK — All claims grounded in the section's source data. No errors.

ISSUE CATEGORIES:
hallucinated_vital — vital sign value present in generated text but absent from source vitals data
hallucinated_lab — lab value present in generated text but absent from source lab data
hallucinated_finding — imaging/echo/cath finding not in source
wrong_diagnosis — diagnosis directly contradicts an ICD code in source
missed_allergy — source documents an allergy AND same drug is in discharge medications
wrong_medication — drug name in generated text doesn't match source
wrong_dose — dose in generated text doesn't match source
wrong_frequency — frequency in generated text doesn't match source
wrong_procedure — procedure not found in source procedures list
wrong_discharge_condition — discharge condition contradicts source
format_error — date format, unit symbol error only
style_error — phrasing/wording issue only, no clinical impact
no_source — source data was empty so this section could not be verified

RULES:
1. Verify each section ONLY against its own SOURCE DATA block. Do NOT cross-reference other sections.
2. If a value in the generated text matches any field in that section's source data, return OK for that value.
3. Flag T3 hallucinated_vital / hallucinated_lab only when a specific numeric value appears in the generated text AND is absent from the source data.
4. Flag T2 only for confirmed mismatches between generated medication details and source discharge_medications list.
5. Flag wrong_diagnosis (T3) only if the diagnosis DIRECTLY contradicts an ICD code — absent diagnoses are not wrong.
6. Flag missed_allergy (T3) only if source pmh.allergies lists a substance AND the same substance appears in discharge medications.
7. NEVER flag text truncation, "[…]" markers, or mid-sentence endings — these are prompt length limits, not summary errors.
8. When genuinely uncertain, return OK. Only flag things you are certain about.
9. If SOURCE DATA says "(no data available)", return tier "OK" and one issue with category "no_source" and explanation "Source data was not available — this section could not be independently verified."
10. Numeric precision tolerance: treat 26 and 26.0 as the same value. A trailing ".0" or rounding to 1 decimal place does NOT constitute a hallucination. Only flag when the numeric value is genuinely different (e.g., source says 2.4, generated says 4.2).
11. Lab name equivalents: "Lactate" and "Lactic acid" are the same test. "Troponin I" and "Troponin T" are different. "Creatinine" and "Serum creatinine" are the same. Apply clinical common sense for obvious synonyms — do NOT flag synonyms as hallucinations.
12. Units: if a value is in source data without units and the generated text adds a standard unit (mmol/L, mg/dL, ng/mL), do NOT flag this as T3. Only flag if the added unit is clinically incompatible (e.g., source says 2.4 ng/mL, generated says 2.4 mmol/L).

Return ONLY valid JSON with exactly 15 keys (s1 through s15). No text outside the JSON.
Each section value:
{"tier":"OK"|"T1"|"T2"|"T3","issues":[{"category":"...","ai_output":"exact phrase from generated text","source_value":"value from source or null if absent","explanation":"why flagged and what to fix"}]}
Issues array is [] when tier is OK."""

def _run_verification_pass_sync(enc_id: str, sections_json: dict, clinical_json_str: str) -> None:
    """Pass 3: per-section independent verification.
    Each section gets its own source data block (GenerationSources ≡ VerificationSources).
    Runs in a thread via run_in_threadpool."""
    try:
        import json as _j, re as _re
        try:
            _cj = _j.loads(clinical_json_str) if isinstance(clinical_json_str, str) else (clinical_json_str or {})
        except Exception:
            _cj = {}

        # Build 15 independent section blocks: each has its own source data + generated text
        _blocks = []
        for _sk in [f"s{i}" for i in range(1, 16)]:
            _sv = sections_json.get(_sk)
            _body = (_sv.get("text") if isinstance(_sv, dict) else None) or ""
            if len(_body) > 1400:
                _body = _body[:1400] + " […prompt truncated — not a summary error…]"
            _lbl      = _PASS3_SECTION_LABELS.get(_sk, _sk.upper())
            _src_block = _build_section_source(_cj, _sk)
            _blocks.append(
                f"=== [{_sk.upper()} — {_lbl}] ===\n"
                f"{_src_block}\n\n"
                f"GENERATED TEXT:\n{_body if _body else '(section was not generated)'}"
            )

        if not _blocks:
            log.info(f"Pass 3 skipped for enc {enc_id} — no sections")
            return

        _user_msg = (
            "Verify each section below independently against its own SOURCE DATA block only.\n"
            "Return JSON with exactly 15 keys s1–s15.\n\n"
            + "\n\n---\n\n".join(_blocks)
        )

        _raw, _err = _call_gemini(_user_msg, system_instruction=_PASS3_SYSTEM, thinking_budget=0)
        if _err or not _raw:
            log.warning(f"Pass 3 Gemini call failed for enc {enc_id}: {_err}")
            return

        _m = _re.search(r'\{[\s\S]*\}', _raw)
        if not _m:
            log.warning(f"Pass 3: no JSON in response for enc {enc_id}")
            return
        try:
            _p3 = _j.loads(_m.group(0))
        except Exception as _je:
            log.warning(f"Pass 3 JSON parse error for enc {enc_id}: {_je}")
            return

        # Merge Pass 3 into sections_json — worst tier wins per section.
        # no_source issues never escalate tier (they indicate unverifiable, not wrong).
        _rank = {"T3": 3, "T2": 2, "T1": 1, "OK": 0}
        _merged = dict(sections_json)
        _flagged = 0
        for _sk, _p3sec in _p3.items():
            if not isinstance(_p3sec, dict):
                continue
            _p3_tier   = _p3sec.get("tier", "OK")
            _p3_issues = [i for i in (_p3sec.get("issues") or []) if isinstance(i, dict)]
            # no_source issues don't escalate tier — they're informational only
            _real_issues = [i for i in _p3_issues if i.get("category") != "no_source"]
            if not _real_issues and _p3_tier != "OK":
                _p3_tier = "OK"
            _existing = _merged.get(_sk) or {}
            _ex_tier  = _existing.get("tier", "OK") if isinstance(_existing, dict) else "OK"
            if _rank.get(_p3_tier, 0) > _rank.get(_ex_tier, 0):
                _merged[_sk] = {**(_existing if isinstance(_existing, dict) else {}),
                                "tier": _p3_tier, "issues": _p3_issues}
            elif _p3_issues and isinstance(_existing, dict):
                _merged[_sk] = {**_existing,
                                "issues": (_existing.get("issues") or []) + _p3_issues}
            if _p3_tier != "OK":
                _flagged += 1

        _t1 = sum(1 for _s in _merged.values() if isinstance(_s, dict) and _s.get("tier") == "T1")
        _t2 = sum(1 for _s in _merged.values() if isinstance(_s, dict) and _s.get("tier") == "T2")
        _t3 = sum(1 for _s in _merged.values() if isinstance(_s, dict) and _s.get("tier") == "T3")
        _dl = sum(1 for _s in _merged.values() if isinstance(_s, dict) and _s.get("tier") not in ("OK", None))

        _pass3_gap_rows = []
        for _sid in [f"s{i}" for i in range(1, 16)]:
            _sd = _merged.get(_sid)
            if not isinstance(_sd, dict) or _sd.get("tier") in ("OK", None):
                continue
            _lbl = _PASS3_SECTION_LABELS.get(_sid, _sid.upper())
            _iss = [i for i in (_sd.get("issues") or [])
                    if isinstance(i, dict) and i.get("category") != "no_source"]
            if not _iss:
                continue
            _first   = _iss[0]
            _desc    = _first.get("explanation") or _first.get("description") or "AI accuracy issue detected"
            _pass3_gap_rows.append({
                "sec":    _sid,
                "title":  _lbl,
                "missing": _desc,
                "tier":   _sd["tier"],
                "sjKeys": [_sid],
            })

        gdb.update_summary(enc_id, {
            "sections_json": _merged,
            "gap_t1": _t1, "gap_t2": _t2, "gap_t3": _t3, "dl_flags": _dl,
            "gap_rows": _pass3_gap_rows,
        })
        log.info(f"Pass 3 complete for enc {enc_id} — {_flagged} section(s) flagged (T1:{_t1} T2:{_t2} T3:{_t3})")
        return {"gap_t1": _t1, "gap_t2": _t2, "gap_t3": _t3, "dl_flags": _dl}

    except Exception as _ex:
        log.warning(f"Pass 3 error for enc {enc_id}: {_ex}")
    return None


@app.post("/api/encounters/{hadm_id}/generate_summary")
async def generate_summary(hadm_id: int, source: str = "bq",
                            stream: bool = False,
                            req: GenerateSummaryRequest = None):
    """
    Full pipeline:
    1. Fetch ALL MIMIC tables for this hadm_id from Cloud SQL (BigQuery on first load)
    2. Build structured clinical context string
    3. Call Gemini LLM to write the discharge summary
    4. Save to summaries table, update encounter status
    5. Return summary text + table log + data counts

    source=gcs (default): real MIMIC data from GCS — all tables, all rows
    source=db:             Cloud SQL data (manually uploaded files)
    """
    log.info(f"{'='*60}")
    log.info(f"GENERATE SUMMARY — HADM {hadm_id}  source={source}")
    log.info(f"{'='*60}")

    # Mark as Processing immediately so Kanban shows the card in Generating column
    _enc_early = gdb.get_encounter_by_hadm(hadm_id)
    _enc_id_for_reset = _enc_early["id"] if _enc_early else None
    if _enc_early:
        gdb.update_encounter(_enc_early["id"], {"status": "Processing"})

    async def _reset_if_stuck():
        """Reset status to Pending if a crash left it stuck in Processing."""
        try:
            _chk = gdb.get_encounter_by_hadm(hadm_id)
            if _chk and _chk.get("status") == "Processing" and _enc_id_for_reset:
                gdb.update_encounter(_enc_id_for_reset, {"status": "Pending Ingestion"})
                log.warning(f"generate_summary: reset HADM {hadm_id} from stuck Processing → Pending Ingestion")
        except Exception:
            pass

    # ── Synthetic demo patient short-circuit ──────────────────────────────────
    # Hadm IDs 9900001–9900005 are pre-built Indian demo cases.
    # They skip BigQuery entirely and go straight to Pass 2.
    from .synthetic_demo import is_demo_hadm, get_demo_case_by_hadm
    if is_demo_hadm(hadm_id):
        import json as _json_demo
        demo_case = get_demo_case_by_hadm(hadm_id)
        if req and req.discharge_type:
            demo_case["discharge_type"] = req.discharge_type
        log.info(f"[DEMO] Using synthetic patient: {demo_case['patient']['name']} (discharge_type={demo_case['discharge_type']})")
        clinical_context = f"[SYNTHETIC DEMO — {demo_case['patient']['name']}]\n"
        clinical_context += f"Discharge Type: {demo_case['discharge_type']}\n"
        clinical_context += f"Primary Diagnosis: {demo_case['discharge_diagnosis_clinical']}\n"
        clinical_json_demo = _json_demo.dumps(demo_case, indent=2)
        # Jump straight to Pass 2 using demo JSON (skip Pass 1 — facts already structured)
        enc = gdb.get_encounter_by_hadm(hadm_id) or gdb.create_encounter(hadm_id, status="Ready for Review")
        enc_id    = enc["id"]
        new_version = (enc.get("version") or 1) + 1
        # Re-use the Pass 2 system prompt builder below by setting clinical_json directly
        # We store the demo JSON as clinical_context for audit trail, then fall through
        # to the normal Pass 2 path by providing all required locals.
        clinical_json = clinical_json_demo
        pass1_text  = clinical_json
        pass1_error = None
        pass1_latency = 0.0
        # Patch discharge_type if resident selected override
        _dt = demo_case.get("discharge_type", "Standard")
        table_log     = []
        total_tables  = 0
        total_records = 0
        # Skip to Pass 2 label
        _skip_to_pass2 = True
    else:
        _skip_to_pass2 = False

    # Guard: never generate a discharge summary for a patient with no real clinical
    # data — it would otherwise fabricate from synthetic fallbacks. Demo patients
    # (9900001–9900005) are exempt (handled above via _skip_to_pass2).
    if not _skip_to_pass2 and not _has_real_clinical_data(hadm_id):
        if _enc_id_for_reset:
            try:
                gdb.update_encounter(_enc_id_for_reset, {"status": "Pending Ingestion"})
            except Exception:
                pass
        raise HTTPException(
            status_code=409,
            detail="Clinical data not loaded for this patient. Admit via billing and "
                   "wait for MIMIC sync to complete before generating the discharge summary.",
        )

    # 1. Fetch all data — display + lazy tabs in parallel (uses disk cache, fast if warm)
    if not _skip_to_pass2 and source == "db":
        data = fetch_all_patient_data(hadm_id)
    elif not _skip_to_pass2:
        _long  = httpx.Timeout(connect=5.0, read=600.0, write=10.0, pool=5.0)
        _short = httpx.Timeout(connect=5.0, read=20.0,  write=10.0, pool=5.0)
        # Core tabs — all fast from BQ / Cloud SQL cache
        _ROUND1_TABS = ["prescriptions", "pharmacy", "labevents", "poe", "emar",
                        "fluids", "chartevents", "datetimeevents"]

        async def _fetch(path: str, timeout=None) -> dict:
            try:
                r = await _data_client.get(path, timeout=timeout or _long)
                if r.status_code == 200:
                    return r.json()
            except Exception as exc:
                log.warning(f"generate_summary fetch {path}: {exc}")
            return {}

        # Round 1: display + core tabs in parallel (all return in <1s when cached)
        round1 = await asyncio.gather(
            _fetch(f"/api/patient/{hadm_id}/display"),
            *[_fetch(f"/api/patient/{hadm_id}/tab/{t}") for t in _ROUND1_TABS],
        )
        data = round1[0]
        if "error" in data:
            await _reset_if_stuck()
            raise HTTPException(status_code=404, detail=data["error"])
        for tab_data in round1[1:]:
            data.update(tab_data)

        # Round 2: procedureevents + outputevents in parallel.
        # Can be slow when not cached; cap at 20 s.
        round2 = await asyncio.gather(
            _fetch(f"/api/patient/{hadm_id}/tab/procedureevents", timeout=_short),
            _fetch(f"/api/patient/{hadm_id}/tab/outputevents",    timeout=_short),
        )
        for tab_data in round2:
            data.update(tab_data)

        # Normalise BQ key aliases → keys expected by build_clinical_context.
        # BQ display returns "drgcodes" / "microbiologyevents"; tabs return "procedureevents" /
        # "datetimeevents". build_clinical_context was designed around fetch_all_patient_data
        # which uses "drg_codes" / "microevents" / "procevents" / "dtevents".
        data.setdefault("microevents", data.get("microbiologyevents") or [])
        data.setdefault("procevents",  data.get("procedureevents") or [])
        # fluids tab returns key "fluids" but build_clinical_context expects "inputevents"
        data.setdefault("inputevents", data.get("fluids") or [])

        # Merge uploaded clinical files — keys match fetch_all_uploaded_clinical_data output
        _SUMMARY_MERGE_MAP = [
            ("procedures",   "procedures_icd"),
            ("diagnoses",    "diagnoses"),
            ("microbiology", "microevents"),
            ("icustays",     "icustays"),
            ("transfers",    "transfers"),
            ("labs",         "labevents"),
            ("meds",         "prescriptions"),
            ("pharmacy",     "pharmacy"),
            ("poe",          "poe"),
            ("fluids",       "inputevents"),
            ("vitals",       "chartevents"),
            ("icu",          "procevents"),
        ]
        try:
            uploaded = await run_in_threadpool(gdb.fetch_all_uploaded_clinical_data, hadm_id)
            for src_key, dst_key in _SUMMARY_MERGE_MAP:
                rows = uploaded.get(src_key, [])
                if rows:
                    data[dst_key] = data.get(dst_key, []) + rows
            # Deduplicate procedures/diagnoses by icd_code — prefer row with long_title
            for key in ("procedures_icd", "diagnoses"):
                if data.get(key):
                    seen: dict = {}
                    for r in data[key]:
                        code = str(r.get("icd_code") or "").strip()
                        if not code:
                            continue
                        if code not in seen or (r.get("long_title") and not seen[code].get("long_title")):
                            seen[code] = r
                    data[key] = list(seen.values())
            # Auto-fill ICD descriptions and lab labels — run all three in parallel
            enriched = await asyncio.gather(
                _enrich_icd(data.get("procedures_icd") or [], "procedures"),
                _enrich_icd(data.get("diagnoses") or [], "diagnoses"),
                _enrich_labevents(data.get("labevents") or []),
            )
            if data.get("procedures_icd"): data["procedures_icd"] = enriched[0]
            if data.get("diagnoses"):      data["diagnoses"]      = enriched[1]
            if data.get("labevents"):      data["labevents"]      = enriched[2]
        except Exception as exc:
            log.warning(f"generate_summary: failed to merge uploaded clinical data: {exc}")

        data["encounter"] = gdb.get_encounter_by_hadm(hadm_id)
        data["uploaded_files"] = []
        # Build table_log from fetched data (data_server doesn't return it)
        _TABLE_COUNTS = [
            ("labevents", 100), ("prescriptions", 80), ("pharmacy", None),
            ("chartevents", 80), ("poe", None), ("inputevents", None),
            ("diagnoses", None), ("procedures_icd", None),
            ("microevents", None), ("transfers", None),
            ("icustays", None), ("procevents", None), ("noteevents", None),
        ]
        table_log = []
        for _tf, _cap in _TABLE_COUNTS:
            _rows = data.get(_tf, [])
            if _rows:
                _capped = _cap is not None and len(_rows) >= _cap
                table_log.append({"table": _tf, "count": len(_rows), "capped": _capped, "cap": _cap})
        data["table_log"] = table_log
    # For demo patients _skip_to_pass2=True so data is never set; table_log was set in demo block
    if not _skip_to_pass2:
        table_log     = data.get("table_log", [])
        total_tables  = len(table_log)
        total_records = sum(t["count"] for t in table_log)

    # 2. Build context (skipped for synthetic demo patients — clinical_context pre-set above)
    if not _skip_to_pass2:
        clinical_context = build_clinical_context(hadm_id, data)
        log.info(f"Clinical context: {len(clinical_context):,} chars across {total_tables} tables")
    else:
        log.info(f"[DEMO] Skipping context build — using pre-structured JSON directly")

    # ── Helper: call Gemini with retries (system_instruction = proper system role) ──
    def _call_gemini(prompt_text: str, system_instruction: str | None = None,
                     thinking_budget: int | None = None) -> tuple[str | None, str | None]:
        """Returns (generated_text, error_message). Tries up to 4 times."""
        if not gemini_client:
            return None, "GEMINI_API_KEY not set. Add your key to backend/.env and restart the server."
        from google.genai import types as _gtypes
        _cfg_kw: dict = {}
        if system_instruction:
            _cfg_kw["system_instruction"] = system_instruction
        if thinking_budget is not None:
            _cfg_kw["thinking_config"] = _gtypes.ThinkingConfig(thinking_budget=thinking_budget)
        _config = _gtypes.GenerateContentConfig(**_cfg_kw) if _cfg_kw else None
        _delays = [5, 15, 30]
        for _attempt, _wait in enumerate([0] + _delays, 1):
            if _wait:
                log.info(f"Gemini retry {_attempt}/{len(_delays)+1} — waiting {_wait}s…")
                time.sleep(_wait)
            try:
                log.info(f"Calling Gemini ({GEMINI_MODEL}) attempt {_attempt}…")
                resp = gemini_client.models.generate_content(
                    model=GEMINI_MODEL, contents=prompt_text,
                    **({"config": _config} if _config else {}),
                )
                if not resp.text:
                    raise ValueError(f"Empty response from {GEMINI_MODEL}")
                log.info(f"Gemini returned {len(resp.text):,} chars")
                return resp.text, None
            except Exception as e:
                err = str(e)
                if "503" in err or "429" in err or "rate" in err.lower() or "UNAVAILABLE" in err:
                    log.warning(f"Gemini transient error attempt {_attempt}: {e}")
                    continue
                log.error(f"Gemini non-retryable error: {e}")
                return None, err
        return None, "Max retries exceeded"

    # 3. TWO-PASS PIPELINE
    # ── Pass 1: Fact Extraction → JSON ────────────────────────────────────────
    # System instruction and user message are kept separate (PM spec v1.1)
    # Skipped for synthetic demo patients — clinical_json already pre-structured.
    import json as _json, re as _re
    _PASS1_SYSTEM = """You are a clinical data extraction engine for an Indian cardiology hospital.
Your ONLY job is to extract facts from the provided clinical documents and return them as structured JSON.
You do not generate narrative. You do not infer. You do not extrapolate.
If a fact is not present in the documents, return null for that field.

EXTRACTION RULES — READ CAREFULLY:
A. all_labs: Extract EVERY lab test result from [LAB RESULTS] and [OUTPATIENT MEASUREMENTS] documents that has an actual numeric or descriptive clinical value. Format: {"Test Name": "value unit"} or {"Test Name": "value unit (abnormal)"}. Example: {"Hemoglobin": "9.6 g/dL", "Basophils": "0.1 %", "Anion Gap": "17 mEq/L (abnormal)", "Potassium": "3.3 mEq/L"}. STRICT EXCLUSIONS — do NOT include: (1) entries where the value is None, null, empty, "N/A", or missing; (2) internal lab system codes or order status markers such as HOLD, DONE, RFXUCU, XUCU, PAN3, or specimen tube colour references (Blue Top Hold, Red Top Hold, Light Green Top Hold, etc.) — these are administrative, not clinical values; (3) specimen tracking labels.
B. clinical_notes_text: Copy the full text from [CLINICAL NOTES] and [DISCHARGE NOTE — MIMIC-IV] documents verbatim (up to 3000 characters). This is used for the HPI and hospital course narrative.
C. microbiology: Extract ONLY culture results where a specific organism was identified. COMPLETELY OMIT any specimen whose result is "No growth" — do not include it at all. Each entry: {specimen, organism, result_summary, sensitivity_key_findings}.
D. vital_signs_trend: Summarise the VITAL SIGNS document as a prose paragraph covering: all BP readings (with dates), HR trend, SpO2, temperature, RR over the hospital stay.
E. omr_measurements: Extract all values from [OUTPATIENT MEASUREMENTS (OMR)] as key-value pairs.
F. labs (named fields): Also populate the named lab fields below as a cross-reference — these are a subset of all_labs.
G. imaging_reports: From [PHYSICIAN ORDERS (POE)], [CLINICAL NOTES], and [DISCHARGE NOTE] documents, extract ALL imaging studies — X-rays, EKGs, CT scans, MRIs, ultrasounds, nuclear studies. For each entry: state the study type and date. If findings/results are documented, include them. If only an order exists with no report, write "Ordered [date] — report not available in source documents". Format as a prose paragraph. Return null if no imaging of any kind appears. Do NOT duplicate findings already captured in ecg_findings or echo fields.

Output format: Valid JSON matching the schema below. Nothing else. No preamble. No explanation. No markdown code blocks. Raw JSON only.

Schema:
{
  "patient": {
    "name": null, "age": null, "dob": null, "sex": null, "uhid": null,
    "admission_date": null, "discharge_date": null,
    "admission_mode": null,
    "referral_source": null,
    "attending_physician": null, "attending_mci_reg": null,
    "ward": null, "bed_number": null,
    "next_of_kin": {"name": null, "relationship": null, "contact": null},
    "insurance_tpa": null
  },
  "chief_complaint": null,
  "duration_of_symptoms": null,
  "hpi": null,
  "clinical_notes_text": null,
  "pmh": {
    "comorbidities": [], "prior_cardiac_interventions": [],
    "surgical_history": [], "allergies": [],
    "family_history": null,
    "smoking": null, "alcohol": null
  },
  "vitals_on_admission": {
    "bp_systolic": null, "bp_diastolic": null,
    "heart_rate": null, "rhythm": null,
    "spo2": null, "respiratory_rate": null,
    "temperature": null, "gcs": null,
    "jvp": null, "heart_sounds": null, "murmurs": null,
    "breath_sounds": null, "pedal_oedema": null
  },
  "vital_signs_trend": null,
  "all_labs": {},
  "labs": {
    "troponin_t_peak": null, "troponin_unit": null,
    "troponin_serial": [],
    "bnp_or_ntprobnp": null,
    "hemoglobin": null, "wbc": null, "platelets": null,
    "creatinine": null, "egfr": null, "urea": null,
    "sodium": null, "potassium": null, "magnesium": null,
    "hba1c": null, "fasting_glucose": null,
    "lipid_profile": {"ldl": null, "hdl": null, "triglycerides": null, "total_cholesterol": null},
    "inr": null, "pt": null
  },
  "microbiology": [],
  "omr_measurements": {},
  "ecg_findings": null,
  "imaging_reports": null,
  "echo": {"lvef_percent": null, "wall_motion_abnormality": null, "valvular_findings": null, "pericardial_findings": null},
  "cath_lab": {
    "lad_stenosis_percent": null, "lcx_stenosis_percent": null, "rca_stenosis_percent": null,
    "intervention_performed": null, "stent_details": null, "timi_flow_post": null,
    "chest_xray_findings": null
  },
  "risk_scores": {"grace_score": null, "grace_risk": null, "timi_score": null},
  "hospital_course": null,
  "complications": [],
  "procedures": [{"name": null, "date": null, "operator": null, "outcome": null, "icd_pcs_code": null}],
  "discharge_medications": [{"drug_name_source": null, "dose": null, "frequency": null, "route": null, "duration": null, "high_risk_flag": null}],
  "dapt_months": null,
  "stopped_medications": [],
  "discharge_diagnosis_clinical": null,
  "icd10_codes": [],
  "icd10_pcs_codes": [],
  "discharge_type": "Standard",
  "condition_at_discharge": null,
  "nyha_class": null,
  "discharge_vitals": {"bp_systolic": null, "bp_diastolic": null, "heart_rate": null, "spo2": null, "weight_kg": null},
  "followup": {
    "date": null, "physician": null, "clinic": null,
    "investigations_ordered": [],
    "diet_instructions": null,
    "activity_restrictions": null,
    "emergency_return_criteria": [],
    "warnings": []
  },
  "patient_acknowledgement": {"confirmed": false, "confirmed_by": null, "relationship_to_patient": null, "timestamp": null}
}"""

    # User message: label each clinical section as a numbered document per spec
    import re as _re2
    def _to_labeled_documents(ctx: str) -> str:
        """Convert [SECTION] headers → [DOCUMENT N — Section Name] format."""
        parts = _re2.split(r'\n(?=\[)', ctx.strip())
        out = []
        for i, part in enumerate(parts, 1):
            m = _re2.match(r'\[([^\]]+)\](.*)', part, _re2.DOTALL)
            if m:
                name = m.group(1).strip().title()
                body = m.group(2).strip()
                out.append(f"[DOCUMENT {i} — {name}]\n{body}")
            else:
                out.append(part)
        return "\n\n".join(out)

    _labeled_docs = _to_labeled_documents(clinical_context)
    pass1_user_msg = (
        "Extract all clinical facts from the following documents for patient discharge summary generation.\n\n"
        f"Documents provided:\n\n{_labeled_docs}\n\n"
        "Return valid JSON only. No other text."
    )

    log.info("=== PASS 1 — Fact Extraction (system+user split) ===")
    _t0_pass1 = time.time()
    if not _skip_to_pass2:
        _cached = _pass1_cache.get(hadm_id)
        if _cached and _cached.get("clinical_context") == clinical_context:
            log.info(f"[precompute] Pass 1 cache HIT for hadm_id={hadm_id} — skipping LLM call")
            pass1_text, pass1_error = _cached["pass1_json"], None
        else:
            if _cached:
                log.info(f"[precompute] Pass 1 cache STALE for {hadm_id} — re-running")
            pass1_text, pass1_error = await run_in_threadpool(_call_gemini, pass1_user_msg, _PASS1_SYSTEM, 1024)
            if pass1_text:
                _pass1_cache[hadm_id] = {"pass1_json": pass1_text, "clinical_context": clinical_context}
    pass1_latency = round(time.time() - _t0_pass1, 2)

    # Extract JSON from Pass 1 response (skipped for demo — clinical_json pre-set)
    if not _skip_to_pass2:
        clinical_json = "{}"
        if pass1_text:
            try:
                clean = _re.sub(r"```(?:json)?\s*", "", pass1_text).replace("```", "").strip()
                _json.loads(clean)
                clinical_json = clean
                log.info(f"Pass 1 JSON extracted: {len(clinical_json)} chars")
            except Exception as je:
                log.warning(f"Pass 1 JSON parse failed ({je}), using raw text as context")
                clinical_json = pass1_text

    # Override discharge_type and nyha_class if the user explicitly selected them in the UI
    try:
        import json as _json2
        _jdict = _json2.loads(clinical_json)
        _overridden = False
        if req and req.discharge_type:
            _jdict["discharge_type"] = req.discharge_type
            log.info(f"discharge_type overridden to: {req.discharge_type}")
            _overridden = True
        if req and req.nyha_class:
            _jdict["nyha_class"] = req.nyha_class
            log.info(f"nyha_class overridden to: {req.nyha_class}")
            _overridden = True
        if _overridden:
            clinical_json = _json2.dumps(_jdict)
    except Exception as exc:
        log.warning(f"Failed to override request parameters in clinical_json: {exc}")

    # ── Pass 2: NABH Narrative Generation from JSON ───────────────────────────
    # Apply CIMS drug name mapping: translate US generic names → Indian brand names
    # before Pass 2 so the narrative uses Indian trade names (Metolar XR, not Metoprolol).
    try:
        from .cims_drug_map import indianise_medications as _cims_map
        _jdict_cims = _json.loads(clinical_json)
        _meds = _jdict_cims.get("discharge_medications") or []
        if isinstance(_meds, list) and _meds:
            _jdict_cims["discharge_medications"] = _cims_map(_meds)
            clinical_json = _json.dumps(_jdict_cims)
            log.info(f"CIMS drug mapping applied to {len(_meds)} medications")
    except Exception as _cims_err:
        log.warning(f"CIMS mapping skipped: {_cims_err}")

    # Extract discharge_type from the validated JSON so it can be injected explicitly
    # into the system prompt — the LLM must never infer discharge type.
    _dt = "Standard"
    try:
        _dt = _json.loads(clinical_json).get("discharge_type") or "Standard"
    except Exception:
        pass
    log.info(f"Pass 2 DISCHARGE TYPE: {_dt}")

    # Build the per-type section delta instructions deterministically
    _DT_DELTA = {
        "Standard": "",
        "LAMA": """
LAMA-SPECIFIC SECTION INSTRUCTIONS (override defaults for these sections only):
s11 — Discharge Medications: List all medications from JSON.discharge_medications. After the list add: "NOTE: Patient refused to receive discharge medications. Non-compliance risk documented. Patient/relative was counselled on risks of non-adherence to prescribed therapy."
s12 — Follow-up & Discharge Advice: REPLACE entirely with AMA Risk Counselling note. Write: "The patient / patient's relative left against medical advice. The following risks were explained and documented: [list all followup.warnings from JSON, or state 'risks of leaving against medical advice were explained verbally']. The patient/relative refused to comply with the medical team's recommendation. Return precautions were advised: the patient was instructed to return immediately if symptoms worsen. AMA Refusal Declaration (separate form) has been completed."
s14 — Condition at Discharge: Begin with "Discharge type: LAMA (Left Against Medical Advice)." State JSON.condition_at_discharge as clinical condition at time of leaving. State the documented reason: "Patient/relative refused further hospital stay as documented in AMA Refusal Declaration."
s15 — Patient Acknowledgement: Write: "AMA Declaration (separate form) completed and signed by [patient/relative name if in JSON, otherwise 'patient/relative']. Standard NABH MN4 patient acknowledgement also required. Both signatures must be on file. NABH MN4 requirement applies.""",
        "DAMA": """
DAMA-SPECIFIC SECTION INSTRUCTIONS (override defaults for these sections only):
s12 — Follow-up & Discharge Advice: REPLACE entirely with DAMA documentation. Write: "The patient was discharged against medical advice upon request. Reason documented: [use JSON.followup.warnings[0] or 'Patient requested discharge against medical advice']. The hospital's clinical recommendation was: continued inpatient care was medically indicated at the time of discharge. The patient/relative was informed of the clinical risks of early discharge. Risk acknowledgement was obtained and documented in the hospital discharge letter."
s14 — Condition at Discharge: Begin with "Discharge type: DAMA (Discharged Against Medical Advice)." State reason: "Patient requested discharge against medical advice." State JSON.condition_at_discharge as clinical condition at time of departure.
s15 — Patient Acknowledgement: Write: "Patient acknowledgement obtained. Hospital administrator co-signature required in addition to patient acknowledgement (DAMA protocol). Both signatures must be on file before this record is closed." """,
        "Death": """
DEATH-SPECIFIC SECTION INSTRUCTIONS — these sections are fundamentally different:
s11 — Discharge Medications: DO NOT list any medications. Write exactly: "Medications returned to Next of Kin at time of death." Return null if no NOK information available.
s12 — Follow-up & Discharge Advice: REPLACE entirely with Death Summary. Write: "DEATH SUMMARY. Primary cause of death: [use JSON.discharge_diagnosis_clinical or 'Not documented']. Contributing conditions: [list JSON.pmh.comorbidities or 'See discharge diagnosis']. Time of death: [use discharge date/time from JSON.patient.discharge_date or 'Not documented in structured data']. Attending physician: [JSON.patient.attending_physician or 'Not documented']. Coroner notification: document as applicable per institutional protocol."
s14 — Condition at Discharge: REPLACE entirely. Write: "Discharge type: Death. Condition at time of death: [JSON.condition_at_discharge or 'Not documented']. Last recorded vital signs: [state from JSON.vitals_on_admission or note unavailable]. Time of death: [JSON.patient.discharge_date or 'Not documented in structured data']."
s15 — Patient Acknowledgement: Write: "Next of Kin acknowledgement required. Patient cannot sign. NOK name: [not documented — to be completed in physical file]. Relationship to patient: [not documented — to be completed in physical file]. NOK signature and timestamp to be recorded in the physical file. NABH MN4 NOK acknowledgement protocol applies." """,
        "Referral": """
REFERRAL/TRANSFER-SPECIFIC SECTION INSTRUCTIONS (override defaults for these sections only):
s11 — Discharge Medications: List all medications from JSON.discharge_medications. After the list add: "Medications transferred with patient to receiving facility."
s12 — Follow-up & Discharge Advice: MODIFY to include referral details. Write standard follow-up from JSON.followup, then add: "REFERRAL DETAILS: Referred to: [document receiving facility — not in JSON, note 'to be documented in referral letter']. Reason for referral: [JSON.followup.investigations_ordered[0] or 'Specialist care required — see referral letter']. Transport mode: [document from referral documentation — not in JSON, note 'see transport documentation']. Documents sent with patient: referral letter, clinical summary, investigation reports. Receiving physician contact: [to be documented in referral letter]."
s14 — Condition at Discharge: Begin with "Discharge type: Referral/Transfer." State JSON.condition_at_discharge. Add: "Patient transferred to receiving facility in [condition at discharge] condition."
s15 — Patient Acknowledgement: Write: "Standard patient/attendant acknowledgement obtained prior to transfer. NABH MN4 requirement met. Signature and timestamp recorded in physical file." """,
    }

    _dt_instructions = _DT_DELTA.get(_dt, _DT_DELTA["Standard"])

    # --- Retraining feedback: inject attending corrections from error_log into the prompt ---
    # Every attending edit → error_log row.  We group all corrections by (section, category),
    # count total occurrences, and inject them here sorted highest-frequency first.
    # Patterns that have recurred many times get multiple diverse examples so the LLM
    # generalises the fix — not just memorises one instance.  The prompt grows richer
    # with every correction and the LLM gradually learns to avoid each failure pattern.
    _prior_errors_block = ""
    try:
        _prior_errors = gdb.get_recent_errors(examples_per_pattern=3)
        if _prior_errors:
            _tier_label = {1: "T1-Minor", 2: "T2-Medication", 3: "T3-Critical"}
            _lines = []
            for _e in _prior_errors:
                _sec   = _e.get("nabh_section", "")
                _tier  = _tier_label.get(_e.get("error_tier", 0), "T2-Concern")
                _cat   = (_e.get("error_category") or "").replace("_", " ")
                _count = _e.get("occurrence_count", 1)
                _exs   = _e.get("examples", [])
                _priority = " ⚠ HIGH PRIORITY" if _count >= 5 else ""
                _lines.append(
                    f"  [{_sec} · {_tier} · {_cat} · {_count} occurrence{'s' if _count != 1 else ''}{_priority}]"
                )
                for _i, _ex in enumerate(_exs, 1):
                    _ai  = (_ex.get("ai_output")    or "")[:120]
                    _fix = (_ex.get("correct_value") or "")[:120]
                    _pfx = f"Example {_i}: " if len(_exs) > 1 else ""
                    if _fix:
                        _lines.append(f"    {_pfx}AI wrote: \"{_ai}\" → Correct: \"{_fix}\"")
                    else:
                        _lines.append(f"    {_pfx}⚠ Critical error: \"{_ai}\"")
            _prior_errors_block = (
                "\n\nPRIOR ERROR FEEDBACK — MANDATORY (real corrections by attending physicians on this hospital's cases):\n"
                + "\n".join(_lines)
                + "\n  Patterns with more occurrences are more critical. Apply all fixes proactively."
                + " If you detect a similar situation in this patient's data, correct it before writing."
            )
            log.info(f"Injected {len(_prior_errors)} error pattern(s) into Pass 2 prompt "
                     f"(total corrections: {sum(e.get('occurrence_count',1) for e in _prior_errors)})")
    except Exception as _pef:
        log.warning(f"Could not load prior error feedback: {_pef}")

    _PASS2_SYSTEM = f"""You are a clinical documentation assistant for an Indian cardiology hospital.
You generate NABH-compliant discharge summaries for cardiac inpatients.

DISCHARGE TYPE: {_dt}
This value is set deterministically by the resident — do NOT infer or override it.

CRITICAL RULES:
0. SOURCE EXHAUSTION — MANDATORY: Never write "not documented", "not available", or "not recorded" for any section unless EVERY source field listed for that section in the mapping table below has been checked and found to be null, empty, or absent. Always exhaust all mapped source fields before concluding data is absent. Synthesise proper medical narrative prose from whatever is available — do not copy-paste raw field values verbatim.
1. SOURCE-FIRST: Only use facts present in the JSON. Do NOT infer or fabricate. OMIT any field whose JSON value is null, empty, or absent — do not write "Not documented" for individual sub-fields inside lists, tables, or bullet points.
2. MANDATORY INDIAN DRUG NAMES: Every medication name in s11 (Discharge Medications) MUST use the Indian brand name as per CIMS India / Indian pharmaceutical formulary. The drug_name_source field has already been pre-mapped to Indian brands where possible — use it as-is. For any drug that still appears as a US generic (e.g. Aspirin, Atorvastatin, Clopidogrel, Metoprolol, Omeprazole, Furosemide, etc.), YOU MUST convert it to the corresponding Indian brand name using your training knowledge (e.g. Aspirin→Ecosprin, Atorvastatin→Atorva, Clopidogrel→Clopivas, Metoprolol→Metolar XR, Omeprazole→Omez, Furosemide→Lasix). NEVER write a US generic drug name in the output — always use the Indian brand name. If you genuinely do not know the Indian brand name for a specific drug, write the generic name followed by "(Indian brand — verify)".
3. Write in formal medical English suitable for an NABH-accredited hospital discharge document.
4. ABSOLUTE PROHIBITION: Never write any ICD code (e.g. "I509", "K7200"). Always use the full clinical description.
5. Never use clinical judgement words ("improved", "worsened", "resolved", "stabilised") based on lab trends — only if explicitly in the data.
6. Never infer a diagnosis from a lab value. Never guess drug frequency. Never add boilerplate advice not in the JSON.
7. CRITICAL: Do not generate sections that are not applicable to this discharge type. Return null for removed sections — do not fabricate content.

SOURCE FIELD → NABH SECTION MAPPING (exhaust ALL listed fields in order before writing "not documented"):
s1  → patient.* (name, age/dob, sex, uhid, ward, bed, dates, physician, insurance, kin)
s2  → chief_complaint → clinical_notes_text (CC:/Chief Complaint:/HPI: blocks) → discharge_diagnosis_clinical + icd10_codes → pmh.comorbidities
s3  → hpi → clinical_notes_text (HPI/History of Present Illness blocks, any clinical narrative) → hospital_course → vital_signs_trend + risk_scores
s4  → pmh.comorbidities, pmh.prior_cardiac_interventions, pmh.surgical_history, pmh.allergies, pmh.family_history, pmh.smoking, pmh.alcohol → icd10_codes secondary entries (comorbidity fallback when all PMH fields are null)
s5  → vitals_on_admission.* → vital_signs_trend → omr_measurements
s6  → all_labs (max 6 key results) → labs named fields → ecg_findings → omr_measurements → microbiology (positive only)
s7  → echo.* → cath_lab.* → ecg_findings → imaging_reports → cath_lab.chest_xray_findings
s8  → discharge_diagnosis_clinical → icd10_codes (full descriptions) → risk_scores
s9  → hospital_course → clinical_notes_text (progress notes, daily notes) → vital_signs_trend → complications
s10 → procedures.* → cath_lab.intervention_performed + stent_details + timi_flow_post
s11 → discharge_medications.* → dapt_months → stopped_medications
s12 → followup.* (date, physician, clinic, investigations_ordered, diet_instructions, activity_restrictions, emergency_return_criteria, warnings) → clinical_notes_text (discharge instructions fallback when all followup fields are null)
s13 → discharge_diagnosis_clinical → icd10_codes (full descriptions, NEVER raw ICD codes) → icd10_pcs_codes
s14 → condition_at_discharge → discharge_vitals.* → nyha_class → omr_measurements → discharge_type
s15 → patient_acknowledgement.*

STANDARD SECTION-BY-SECTION INSTRUCTIONS (apply to all types unless overridden below):
s1 — Patient Demographics: Write only the patient fields that have actual documented values from JSON.patient. Include: Full Name, Age (computed from dob if age null), Sex, UHID, Ward, Bed Number, Admission Date, Discharge Date, Admission Mode, Referral Source, Attending Physician with MCI Reg No, Insurance/TPA, Next of Kin (name and relationship). SKIP any field where the value is null — do not write "Not documented" for individual missing fields. Only include a field if it has a real value.
s2 — Chief Complaint: (1) Use JSON.chief_complaint verbatim if present. (2) If chief_complaint is null, search JSON.clinical_notes_text for a "Chief Complaint:", "CC:", or "Reason for admission:" block and use that. (3) If clinical_notes_text is also null or contains no identifiable CC block, derive the presenting complaint from JSON.discharge_diagnosis_clinical — write "Patient presented with clinical features consistent with [primary diagnosis]" using the full clinical name. (4) If icd10_codes are present, use the primary code description as additional context. (5) Write "Chief complaint was not documented." ONLY when chief_complaint, clinical_notes_text, discharge_diagnosis_clinical, AND icd10_codes are all null or empty. Add JSON.duration_of_symptoms and referral_source if present. Never an ICD code.
s3 — History of Presenting Illness: (1) Use JSON.hpi verbatim if present and detailed (more than one sentence). (2) If hpi is null or a single sentence, MUST construct a full HPI narrative from JSON.clinical_notes_text — locate the "History of Present Illness", "HPI:", or opening clinical narrative in the notes and use it. Include onset, duration, severity, associated symptoms, and relevant negatives from the notes. (3) If both hpi and clinical_notes_text are null or empty, construct a brief narrative from JSON.hospital_course and JSON.vital_signs_trend describing the clinical presentation. (4) Always add GRACE/TIMI scores from JSON.risk_scores if present. Always add serial troponin trend from JSON.labs.troponin_serial if present. (5) Write "History of presenting illness was not documented." ONLY when hpi, clinical_notes_text, AND hospital_course are all null or empty.
s4 — Significant Past History: Write only documented sub-fields from JSON.pmh (comorbidities, prior_cardiac_interventions, surgical_history, family_history, allergies, smoking, alcohol). Omit any null/empty sub-field. If ALL pmh fields are null or empty, use the secondary entries (all except the first/primary) from JSON.icd10_codes as a comorbidity list — write their full clinical descriptions as documented co-existing conditions. Write "No significant past medical history was documented." ONLY when ALL pmh fields AND all secondary icd10_codes entries are absent.
s5 — Examination Findings on Admission: List only vital signs from JSON.vitals_on_admission that have actual recorded values. Then if JSON.vital_signs_trend is present, add a "Vitals trend during admission:" paragraph from it. Omit null vitals. Add cardiovascular/respiratory/peripheral exam fields only if documented. If ALL vitals_on_admission fields are null but vital_signs_trend is present, use vital_signs_trend as the primary source.
s6 — Laboratory Investigations: From JSON.all_labs, select MAXIMUM 6 of the most clinically significant results — ONE representative value per major category only. Category rules: CBC → Haemoglobin + WBC only (skip MCV, MCH, RDW, basophils, eosinophils, etc.); Renal → Creatinine only; Electrolytes → Na+ and K+ only if abnormal; Cardiac Markers → Troponin I or BNP/NT-proBNP only (pick the most relevant one); Metabolic → HbA1c or fasting glucose only; Coagulation → PT/INR only. Prioritise ABNORMAL values. Do NOT list every sub-component of a panel — pick the single most diagnostic value per category. Exclude entries where value is None, null, "N/A", empty, admin codes (HOLD, DONE, RFXUCU, tube colour references). If JSON.all_labs is empty, fall back to JSON.labs named fields. MAXIMUM 6 bullet points for standard labs. After the lab bullet points: add a Microbiology subsection ONLY if at least one organism was identified — list ONLY positive cultures; omit "No growth". Add ECG findings from JSON.ecg_findings only if non-null. Add OMR measurements from JSON.omr_measurements if present. If all_labs, labs, ecg_findings, and omr_measurements are all empty, write "No laboratory investigations were documented for this encounter."
s7 — Imaging & Procedure Findings: (1) Write non-null fields from JSON.echo (LVEF, wall motion, valvular, pericardial findings). (2) Write non-null fields from JSON.cath_lab (stenosis percentages, intervention, stent details, TIMI flow, chest X-ray findings). (3) Add JSON.ecg_findings if non-null. (4) Add JSON.imaging_reports if non-null — this captures X-rays, EKGs, CT/MRI and other imaging orders or reports extracted from physician orders and clinical notes. (5) Write "No imaging findings were documented for this encounter." ONLY when echo, cath_lab, ecg_findings, AND imaging_reports are all null.
s8 — Working Diagnosis at Admission: Use JSON.discharge_diagnosis_clinical as the primary diagnosis name. If discharge_diagnosis_clinical is null, use the first entry of JSON.icd10_codes as the full clinical description. Add risk stratification if JSON.risk_scores.grace_risk present. List differentials only if documented.
s9 — Hospital Course: (1) Use JSON.hospital_course verbatim if present and detailed (more than two sentences). (2) If hospital_course is null or brief, MUST supplement with JSON.clinical_notes_text to construct a hospital course narrative covering: admission circumstances, key events, investigations ordered, treatments administered, clinical response, and complications. (3) If both are null, construct a brief course from JSON.vital_signs_trend, JSON.procedures, and JSON.complications. (4) List JSON.complications if any. Do NOT list procedures here — they are covered in s10. Write "Hospital course was not documented." ONLY when hospital_course, clinical_notes_text, vital_signs_trend, procedures, AND complications are all null or empty.
s10 — Procedures Performed: From JSON.procedures pick the 5 most clinically significant procedures (major surgical, major interventional, life-support). If there are fewer than 5, list all. Also include JSON.cath_lab.intervention_performed and stent_details if not already in procedures. Do NOT list routine monitoring insertions, standard IV access, or minor diagnostic procedures if more significant ones are present. Sort by date descending. Format: "N. [name] — [date]" — add "Operator: [name]" only if documented; add "Outcome: [text]" only if documented. Omit null sub-fields. If procedures AND cath_lab are both empty, write "No procedures documented."
s11 — Discharge Medications: Select the MOST RELEVANT ongoing discharge medications — maximum 10. Priority order: (1) high-risk medications first (anticoagulants, antiarrhythmics, digoxin, opioids, high-risk electrolytes), (2) primary disease-modifying drugs tied to the main diagnoses (cardiac, HIV/antiretroviral, antidiabetic, antibiotic courses), (3) other established chronic therapy. EXCLUDE entirely: vaccines given during admission; laxatives and stool softeners (Senna, Docusate, Bisacodyl, Polyethylene Glycol — unless hepatic encephalopathy, keep Lactulose); antiflatulents and antacids (Simethicone, Aluminum-Magnesium Hydroxide); routine vitamins and minerals (Ascorbic Acid, Multivitamins, Magnesium Oxide, Neutra-Phos, Thiamine, Zinc); PRN sleep aids and sedatives (Ramelteon, Lorazepam PRN, Zolpidem); PRN inpatient analgesics (Paracetamol/Calpol PRN, short-term opioids not part of an outpatient plan). Format: "N. [drug_name_source] [dose]" — add frequency only if documented; add route only if documented. Skip null sub-fields. Flag high_risk_flag items. Add DAPT duration if JSON.dapt_months present. If discharge_medications is empty AND stopped_medications is empty, write "No discharge medications documented."
s12 — Follow-up & Discharge Advice: Include only documented follow-up details from JSON.followup. Write only non-null sub-fields (date, physician, clinic, investigations ordered, diet instructions, activity restrictions, emergency return criteria, warnings). If all followup fields are null, use JSON.clinical_notes_text to look for discharge instructions. If clinical_notes_text also has no discharge instructions, write "Follow-up arrangements were not documented at the time of discharge."
s13 — Discharge Diagnosis: JSON.discharge_diagnosis_clinical as full descriptive name (NEVER any ICD code). List JSON.icd10_codes as full clinical descriptions (NEVER the raw alphanumeric code). List JSON.icd10_pcs_codes as procedure descriptions if present. Primary first, secondary diagnoses below. If discharge_diagnosis_clinical is null, use icd10_codes descriptions.
s14 — Condition at Discharge: Begin with "Discharge type: {_dt}." Then state JSON.condition_at_discharge verbatim if present. List only discharge vitals from JSON.discharge_vitals that have actual values — omit null vitals. Add JSON.omr_measurements values if relevant (e.g. weight, BP at discharge). Add NYHA class only if JSON.nyha_class present. If condition_at_discharge is null, state "Clinical condition at discharge: as per attending physician's assessment."
s15 — Patient Acknowledgement: If JSON.patient_acknowledgement.confirmed = true, state "Acknowledged by [confirmed_by] ([relationship_to_patient]) at [timestamp]." Otherwise: "Patient acknowledgement to be confirmed by the resident prior to physician sign-off (NABH MN4 requirement). Signature and timestamp to be recorded in the physical file."{_dt_instructions}

{_prior_errors_block}
OUTPUT FORMAT — MANDATORY:
Return a JSON object with exactly 15 keys: s1 through s15. Each value is an object with four fields:
- "text": narrative text for that section (string)
- "confidence": float 0.0–1.0, your confidence this section is fully grounded in the source JSON
- "tier": "OK" (section accurate and complete — no errors), "T1" (minor phrasing or formatting error — clinical meaning unchanged), "T2" (medication concern — wrong drug, dose, or duration), or "T3" (critical clinical error — wrong diagnosis, missed finding, or fabricated value — patient safety risk)
- "issues": array of issue objects; empty array [] when tier is "OK". Each object has two fields: "description" (string — what is wrong) and "quote" (string — the exact phrase copied verbatim from this section's "text" that contains the error, so the physician can find it instantly; use "" only if the problem is an omission not present in the text at all).
Raw JSON only — no markdown, no prose outside the JSON, no code fences.
Example: {{"s1": {{"text": "...", "confidence": 0.94, "tier": "OK", "issues": []}}, "s6": {{"text": "Patient Troponin I: 2.4 ng/mL on admission...", "confidence": 0.55, "tier": "T3", "issues": [{{"description": "Troponin value 2.4 ng/mL not found in source documents — possible hallucination", "quote": "2.4 ng/mL"}}]}}}}"""

    _rej_prefix = ""
    if req and req.rejection_context:
        _rej_prefix = (
            f"REVISION REQUEST: This summary was previously rejected. Doctor's reason:\n"
            f"\"{req.rejection_context}\"\n\n"
            "Address this reason specifically in your revised summary. Review every section for the issue described.\n\n"
        )
    pass2_user_msg = (
        f"{_rej_prefix}"
        "Generate a complete NABH discharge summary for the following patient. "
        "Use only the facts in this JSON. Do not add clinical information not present.\n\n"
        f"{clinical_json}\n\n"
        "Return the 15-section NABH summary as JSON (s1 through s15). Raw JSON only."
    )

    # Resolve enc_id / new_version before streaming branch (demo path already set these)
    if not _skip_to_pass2:
        _enc_pre = (data.get("encounter") or
                    gdb.get_encounter_by_hadm(hadm_id) or
                    gdb.create_encounter(hadm_id, status="Ready for Review"))
        enc_id      = _enc_pre["id"]
        new_version = (_enc_pre.get("version") or 1) + 1

    # 4. Call Gemini — Pass 2
    log.info("=== PASS 2 — NABH Narrative Generation (system+user split, JSON output) ===")

    # ── Streaming path (SSE) — frontend receives text token-by-token ──────────
    if stream:
        from fastapi.responses import StreamingResponse as _SR

        # Capture all local state needed inside the generator closure
        _p1_lat        = pass1_latency
        _p2_sys        = _PASS2_SYSTEM
        _p2_usr        = pass2_user_msg
        _enc_id_ref    = [enc_id]
        _new_ver_ref   = [new_version]
        _skip_ref      = _skip_to_pass2
        _data_ref2     = data if not _skip_to_pass2 else {}
        _src           = source
        _tt            = total_tables
        _tr            = total_records
        _tlog          = table_log
        _cc            = clinical_context
        _hdm           = hadm_id
        _req2          = req

        async def _sse_gen():
            import json as _json2, re as _re2
            queue: asyncio.Queue = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def _cb(text: str):
                loop.call_soon_threadsafe(queue.put_nowait, text)

            async def _run():
                return await run_in_threadpool(
                    _stream_gemini_pass2, _p2_usr, _p2_sys, 2048, _cb
                )

            _t0 = time.time()
            task = asyncio.create_task(_run())

            # ── Post-generation work runs as an independent asyncio task so the
            #    DB save completes even when the SSE client disconnects mid-stream.
            #    asyncio.create_task() tasks are NOT cancelled when the generator
            #    receives GeneratorExit, so status/summary always reach the DB. ──
            async def _finalize() -> dict:
                generated_text, generation_error = await task
                _p2_lat = round(time.time() - _t0, 2)
                _tot_lat = round(_p1_lat + _p2_lat, 2)
                log.info(f"Latency — Pass1={_p1_lat}s Pass2={_p2_lat}s Total={_tot_lat}s (stream)")

                # Parse Pass 2 JSON
                sections_json: dict = {}
                _NABH_TITLES2 = {
                    "s1":"S1 — Patient Demographics","s2":"S2 — Chief Complaint",
                    "s3":"S3 — History of Presenting Illness","s4":"S4 — Significant Past History",
                    "s5":"S5 — Examination Findings on Admission","s6":"S6 — Laboratory Investigations",
                    "s7":"S7 — Imaging & Procedure Findings","s8":"S8 — Working Diagnosis at Admission",
                    "s9":"S9 — Hospital Course","s10":"S10 — Procedures Performed",
                    "s11":"S11 — Discharge Medications","s12":"S12 — Follow-up & Discharge Advice",
                    "s13":"S13 — Discharge Diagnosis","s14":"S14 — Condition at Discharge",
                    "s15":"S15 — Patient Acknowledgement",
                }
                if generated_text and not generation_error:
                    try:
                        _clean = _re2.sub(r"```(?:json)?\s*", "", generated_text).replace("```","").strip()
                        _parsed = _json2.loads(_clean)
                        if isinstance(_parsed, dict) and "s1" in _parsed:
                            _CONF_THRESH = 0.60
                            sections_json = {}
                            for _k, _v in _parsed.items():
                                if not _k.startswith("s"):
                                    continue
                                if isinstance(_v, dict):
                                    _sec = {
                                        "text": str(_v.get("text", "Not documented")),
                                        "confidence": float(_v.get("confidence", 1.0)),
                                        "tier": _v.get("tier", "OK"),
                                        "issues": list(_v.get("issues", [])),
                                        "passed": True,
                                    }
                                    if _sec["confidence"] < _CONF_THRESH:
                                        _sec["text"] = "INCORRECT_STRING"
                                        _sec["tier"] = "T3"
                                        _sec["issues"].insert(0, f"Confidence {_sec['confidence']:.2f} below threshold {_CONF_THRESH}")
                                        _sec["passed"] = False
                                else:
                                    _sec = {"text": str(_v), "confidence": 1.0, "tier": "OK", "issues": [], "passed": True}
                                sections_json[_k] = _sec
                            _parts = []
                            for _key in [f"s{i}" for i in range(1, 16)]:
                                _sec_data = sections_json.get(_key, {})
                                _text = _sec_data.get("text", "Not documented") if isinstance(_sec_data, dict) else str(_sec_data)
                                _parts.append(f"**{_NABH_TITLES2.get(_key,_key.upper())}**\n{_text}")
                            generated_text = "\n\n".join(_parts)

                            # ── Retry loop for streaming path ────────────────────
                            _s_nc_fail = sum(1 for _s in sections_json.values()
                                             if isinstance(_s, dict) and not _s.get("passed", True))
                            if _s_nc_fail > 0:
                                log.info(f"Stream: {_s_nc_fail} sections failed confidence gate — retrying")
                                for _sr in range(2):
                                    _sfailing = [k for k, v in sections_json.items()
                                                 if isinstance(v, dict) and not v.get("passed", True)]
                                    if not _sfailing:
                                        break
                                    for _ssid in _sfailing:
                                        _sttl = _NABH_TITLES2.get(_ssid, _ssid.upper())
                                        _sorig = sections_json[_ssid].get("confidence", 0.0)
                                        _srp = (
                                            f"Regenerate ONLY the {_sttl} section for a NABH discharge summary.\n\n"
                                            f"Previous confidence {_sorig:.2f} below threshold 0.60.\n"
                                            f"Issues: {'; '.join(sections_json[_ssid].get('issues', []))}\n\n"
                                            f"STRICT RULES: Only state facts in the source data. "
                                            f"Write 'Not documented' when absent. No fabrication.\n"
                                            f'Return JSON: {{\"text\":\"...\",\"confidence\":0.0-1.0,\"tier\":\"OK/T1/T2/T3\",\"issues\":[{{\"description\":\"...\",\"quote\":\"exact phrase from text\"}}]}}\n\n'
                                            f"CLINICAL SOURCE:\n{clinical_context[:6000]}\n\nJSON only:"
                                        )
                                        _srt, _sre = await run_in_threadpool(_call_gemini, _srp)
                                        if _srt and not _sre:
                                            try:
                                                _srt_clean = _re2.sub(r"```(?:json)?\s*", "", _srt).replace("```", "").strip()
                                                _srpa = _json2.loads(_srt_clean)
                                                if isinstance(_srpa, dict) and "text" in _srpa:
                                                    _snew = {
                                                        "text":       str(_srpa.get("text", "Not documented")),
                                                        "confidence": float(_srpa.get("confidence", 0.5)),
                                                        "tier":       _srpa.get("tier", "OK"),
                                                        "issues":     list(_srpa.get("issues", [])),
                                                        "passed":     True,
                                                    }
                                                    if _snew["confidence"] < _CONF_THRESH:
                                                        _snew["text"] = "INCORRECT_STRING"
                                                        _snew["tier"] = "T3"
                                                        _snew["issues"].insert(0, f"Retry {_sr+1} conf {_snew['confidence']:.2f} still below threshold")
                                                        _snew["passed"] = False
                                                    else:
                                                        log.info(f"Stream {_ssid} recovered retry {_sr+1} conf={_snew['confidence']:.2f}")
                                                    sections_json[_ssid] = _snew
                                            except Exception as _srpe:
                                                log.warning(f"Stream retry parse fail {_ssid}: {_srpe}")
                                # Rebuild generated_text after stream retries
                                _parts_r = []
                                for _key in [f"s{i}" for i in range(1, 16)]:
                                    _sd_r = sections_json.get(_key, {})
                                    _tx_r = _sd_r.get("text", "Not documented") if isinstance(_sd_r, dict) else str(_sd_r)
                                    _parts_r.append(f"**{_NABH_TITLES2.get(_key,_key.upper())}**\n{_tx_r}")
                                generated_text = "\n\n".join(_parts_r)
                    except Exception as _pe:
                        log.warning(f"Pass2 JSON parse failed in stream: {_pe}")

                # ROUGE
                rouge_scores: dict = {}
                if _src != "db" and generated_text and not generation_error and not _skip_ref:
                    try:
                        ref_note = _data_ref2.get("discharge_note_text")
                        if ref_note:
                            from rouge_score import rouge_scorer as _rs2
                            _sc = _rs2.RougeScorer(["rouge1","rouge2","rougeL"], use_stemmer=True)
                            _sco = _sc.score(ref_note, generated_text)
                            rouge_scores = {
                                "rouge1": round(_sco["rouge1"].fmeasure,4),
                                "rouge2": round(_sco["rouge2"].fmeasure,4),
                                "rougeL": round(_sco["rougeL"].fmeasure,4),
                            }
                    except Exception:
                        pass

                # Save to DB (summary first, then Pass 3, then mark Ready for Review)
                if _enc_id_ref[0]:
                    try:
                        gdb.upsert_summary(
                            _enc_id_ref[0], generated_text,
                            clinical_context=_cc,
                            pass1_latency_s=_p1_lat, pass2_latency_s=_p2_lat, total_latency_s=_tot_lat,
                            rouge1=rouge_scores.get("rouge1"), rouge2=rouge_scores.get("rouge2"),
                            rougeL=rouge_scores.get("rougeL"),
                            summary_version=_new_ver_ref[0],
                            pass1_version=PASS1_VERSION, pass2_version=PASS2_VERSION,
                            sections_json=sections_json if sections_json else None,
                        )
                        if sections_json:
                            _gt1 = sum(1 for _s in sections_json.values() if isinstance(_s, dict) and _s.get("tier") == "T1")
                            _gt2 = sum(1 for _s in sections_json.values() if isinstance(_s, dict) and _s.get("tier") == "T2")
                            _gt3 = sum(1 for _s in sections_json.values() if isinstance(_s, dict) and _s.get("tier") == "T3")
                            _gdl = sum(1 for _s in sections_json.values() if isinstance(_s, dict) and _s.get("tier") not in ("OK", None))
                            gdb.update_summary(_enc_id_ref[0], {"gap_t1": _gt1, "gap_t2": _gt2, "gap_t3": _gt3, "dl_flags": _gdl})

                        # Pass 3: cross-verify generated summary against source BEFORE marking Ready for Review
                        _p3_counts = None
                        if sections_json and clinical_json and not generation_error:
                            try:
                                _p3_counts = await run_in_threadpool(
                                    _run_verification_pass_sync, _enc_id_ref[0], sections_json, clinical_json
                                )
                            except Exception as _p3e:
                                log.warning(f"Pass 3 error in streaming path: {_p3e}")

                        _enc_upd: dict = {"status":"Ready for Review","version":_new_ver_ref[0]}
                        if _req2 and _req2.discharge_type:
                            _enc_upd["discharge_type"] = _req2.discharge_type
                        gdb.update_encounter(_enc_id_ref[0], _enc_upd)
                    except Exception as _dbe:
                        log.error(f"Stream: DB save error (resetting to Pending Ingestion): {_dbe}")
                        try:
                            gdb.update_encounter(_enc_id_ref[0], {"status": "Pending Ingestion"})
                        except Exception:
                            pass

                return {
                    "generated_text": generated_text,
                    "generation_error": generation_error,
                    "rouge_scores": rouge_scores,
                    "sections_json": sections_json,
                    "_p2_lat": _p2_lat,
                    "_tot_lat": _tot_lat,
                    "_p3_counts": _p3_counts,
                }

            _finalize_task = asyncio.create_task(_finalize())

            # Yield token chunks — keep looping until task done AND queue empty
            while not task.done() or not queue.empty():
                try:
                    chunk = await asyncio.wait_for(queue.get(), timeout=0.05)
                    yield f"data: {_json2.dumps({'type': 'chunk', 'text': chunk})}\n\n"
                except asyncio.TimeoutError:
                    continue
            # Drain any last items that arrived after task completed
            while not queue.empty():
                chunk = queue.get_nowait()
                yield f"data: {_json2.dumps({'type': 'chunk', 'text': chunk})}\n\n"

            # Wait for finalization — only reached when client is still connected
            _r = await _finalize_task

            # Final SSE event — include Pass 3 gap counts so frontend never needs a separate fetch
            _p3c = _r.get('_p3_counts') or {}
            yield f"data: {_json2.dumps({'type':'done','summary':_r['generated_text'],'generation_error':_r['generation_error'],'sections_json':_r['sections_json'] or None,'summary_version':_new_ver_ref[0],'clinical_context':_cc,'table_log':_tlog,'latency':{'pass1_s':_p1_lat,'pass2_s':_r['_p2_lat'],'total_s':_r['_tot_lat'],'ok':_r['_tot_lat']<30},'rouge':_r['rouge_scores'] or None,'gap_t1':_p3c.get('gap_t1',0),'gap_t2':_p3c.get('gap_t2',0),'gap_t3':_p3c.get('gap_t3',0),'dl_flags':_p3c.get('dl_flags',0)})}\n\n"

        return _SR(_sse_gen(), media_type="text/event-stream",
                   headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

    # ── Non-streaming path (used by trigger_regeneration) ─────────────────────
    _t0_pass2 = time.time()
    generated_text, generation_error = await run_in_threadpool(_call_gemini, pass2_user_msg, _PASS2_SYSTEM, 2048)
    pass2_latency = round(time.time() - _t0_pass2, 2)
    total_latency = round(pass1_latency + pass2_latency, 2)
    log.info(f"Latency — Pass1={pass1_latency}s Pass2={pass2_latency}s Total={total_latency}s (target <30s)")

    # 4b. Parse Pass 2 JSON output → sections_json dict + assemble narrative text
    # PM spec v1.0: Pass 2 returns {"s1":"...","s15":"..."}. We assemble the narrative
    # from that JSON so the frontend parser (rv2ParseSummary) is untouched.
    _NABH_SECTION_TITLES = {
        "s1": "S1 — Patient Demographics",
        "s2": "S2 — Chief Complaint",
        "s3": "S3 — History of Presenting Illness",
        "s4": "S4 — Significant Past History",
        "s5": "S5 — Examination Findings on Admission",
        "s6": "S6 — Laboratory Investigations",
        "s7": "S7 — Imaging & Procedure Findings",
        "s8": "S8 — Working Diagnosis at Admission",
        "s9": "S9 — Hospital Course",
        "s10": "S10 — Procedures Performed",
        "s11": "S11 — Discharge Medications",
        "s12": "S12 — Follow-up & Discharge Advice",
        "s13": "S13 — Discharge Diagnosis",
        "s14": "S14 — Condition at Discharge",
        "s15": "S15 — Patient Acknowledgement",
    }
    _CONFIDENCE_THRESHOLD = 0.60
    sections_json: dict = {}
    if generated_text and not generation_error:
        try:
            _clean_p2 = _re.sub(r"```(?:json)?\s*", "", generated_text).replace("```", "").strip()
            _parsed = _json.loads(_clean_p2)
            if isinstance(_parsed, dict) and "s1" in _parsed:
                for _k, _v in _parsed.items():
                    if not _k.startswith("s"):
                        continue
                    if isinstance(_v, dict):
                        _sec = {
                            "text": str(_v.get("text", "Not documented")),
                            "confidence": float(_v.get("confidence", 1.0)),
                            "tier": _v.get("tier", "OK"),
                            "issues": list(_v.get("issues", [])),
                            "passed": True,
                        }
                        if _sec["confidence"] < _CONFIDENCE_THRESHOLD:
                            _sec["text"] = "INCORRECT_STRING"
                            _sec["tier"] = "T3"
                            _sec["issues"].insert(0, f"Confidence {_sec['confidence']:.2f} below threshold {_CONFIDENCE_THRESHOLD}")
                            _sec["passed"] = False
                    else:
                        _sec = {"text": str(_v), "confidence": 1.0, "tier": "OK", "issues": [], "passed": True}
                    sections_json[_k] = _sec
                # Assemble narrative in **S1 — Title**\ntext format for frontend
                _parts = []
                for _key in [f"s{i}" for i in range(1, 16)]:
                    _title = _NABH_SECTION_TITLES.get(_key, _key.upper())
                    _sec_data = sections_json.get(_key, {})
                    _text = _sec_data.get("text", "Not documented") if isinstance(_sec_data, dict) else str(_sec_data)
                    _parts.append(f"**{_title}**\n{_text}")
                generated_text = "\n\n".join(_parts)
                _nc_fail = sum(1 for _s in sections_json.values() if isinstance(_s, dict) and not _s.get("passed", True))
                log.info(f"Pass 2 JSON parsed OK — {len(sections_json)} sections, "
                         f"T1={sum(1 for s in sections_json.values() if isinstance(s,dict) and s.get('tier')=='T1')}, "
                         f"T2={sum(1 for s in sections_json.values() if isinstance(s,dict) and s.get('tier')=='T2')}, "
                         f"T3={sum(1 for s in sections_json.values() if isinstance(s,dict) and s.get('tier')=='T3')}, "
                         f"confidence_failures={_nc_fail}")

                # ── Retry loop for sections that failed the confidence gate ──────
                if _nc_fail > 0:
                    for _retry_round in range(2):
                        _failing = [k for k, v in sections_json.items()
                                    if isinstance(v, dict) and not v.get("passed", True)]
                        if not _failing:
                            break
                        log.info(f"Confidence-gate retry {_retry_round+1}/2 for sections: {_failing}")
                        for _sid in _failing:
                            _stitle = _NABH_SECTION_TITLES.get(_sid, _sid.upper())
                            _orig_conf = sections_json[_sid].get("confidence", 0.0)
                            _retry_p = (
                                f"Regenerate ONLY the {_stitle} section for a NABH discharge summary.\n\n"
                                f"Previous attempt confidence was {_orig_conf:.2f} — below the 0.60 threshold.\n"
                                f"Previous issues: {'; '.join(sections_json[_sid].get('issues', []))}\n\n"
                                f"STRICT RULES:\n"
                                f"1. Only state facts explicitly present in the clinical source data below.\n"
                                f"2. If a fact is absent, write 'Not documented' — never infer or fabricate.\n"
                                f"3. Return a single JSON object: "
                                f'{{\"text\": \"...\", \"confidence\": 0.0-1.0, \"tier\": \"OK/T1/T2/T3\", \"issues\": [{{\"description\": \"...\", \"quote\": \"exact phrase from text\"}}]}}\n'
                                f"   tier OK = accurate, T1 = minor phrasing/formatting error, T2 = medication concern, T3 = critical clinical error.\n"
                                f"4. 'text' must be the narrative for {_stitle} only — no section header.\n\n"
                                f"CLINICAL SOURCE DATA:\n{clinical_context[:6000]}\n\nJSON only:"
                            )
                            _rt, _re2 = await run_in_threadpool(_call_gemini, _retry_p)
                            if _rt and not _re2:
                                try:
                                    _rc = _re.sub(r"```(?:json)?\s*", "", _rt).replace("```", "").strip()
                                    _rp = _json.loads(_rc)
                                    if isinstance(_rp, dict) and "text" in _rp:
                                        _new = {
                                            "text":       str(_rp.get("text", "Not documented")),
                                            "confidence": float(_rp.get("confidence", 0.5)),
                                            "tier":       _rp.get("tier", "OK"),
                                            "issues":     list(_rp.get("issues", [])),
                                            "passed":     True,
                                        }
                                        if _new["confidence"] < _CONFIDENCE_THRESHOLD:
                                            _new["text"] = "INCORRECT_STRING"
                                            _new["tier"] = "T3"
                                            _new["issues"].insert(0, f"Retry {_retry_round+1} confidence {_new['confidence']:.2f} still below {_CONFIDENCE_THRESHOLD}")
                                            _new["passed"] = False
                                            log.warning(f"{_sid} still failing after retry {_retry_round+1} (conf={_new['confidence']:.2f})")
                                        else:
                                            log.info(f"{_sid} recovered on retry {_retry_round+1} (conf={_new['confidence']:.2f})")
                                        sections_json[_sid] = _new
                                except Exception as _rpe:
                                    log.warning(f"Retry parse failed for {_sid}: {_rpe}")
                    # Rebuild generated_text to reflect any recovered sections
                    _parts2 = []
                    for _key in [f"s{i}" for i in range(1, 16)]:
                        _t2 = _NABH_SECTION_TITLES.get(_key, _key.upper())
                        _sd2 = sections_json.get(_key, {})
                        _tx2 = _sd2.get("text", "Not documented") if isinstance(_sd2, dict) else str(_sd2)
                        _parts2.append(f"**{_t2}**\n{_tx2}")
                    generated_text = "\n\n".join(_parts2)
                    _nc_fail_after = sum(1 for s in sections_json.values()
                                         if isinstance(s, dict) and not s.get("passed", True))
                    log.info(f"After confidence-gate retries: {_nc_fail_after} sections still failing")
            else:
                log.warning("Pass 2 response was not the expected s1–s15 JSON; using raw text")
        except Exception as _p2e:
            log.warning(f"Pass 2 JSON parse failed ({_p2e}); using raw text as fallback")

    # _data_ref: safe reference to data dict for both demo and real patients
    _data_ref = data if not _skip_to_pass2 else {}

    # Fallback when LLM unavailable
    if not generated_text:
        adm = _data_ref.get("admission") or {}
        pat = _data_ref.get("patient") or {}
        generated_text = (
            f"[AI Generation Unavailable]\n"
            f"{generation_error}\n\n"
            f"Data collected successfully for HADM {hadm_id}:\n"
            f"  Patient:       {pat.get('full_name','Unknown')}\n"
            f"  Admitted:      {adm.get('admittime','—')} → {adm.get('dischtime','—')}\n"
            f"  Diagnoses:     {len(_data_ref.get('diagnoses',[]))} ICD codes\n"
            f"  Lab results:   {len(_data_ref.get('labevents',[]))}\n"
            f"  Prescriptions: {len(_data_ref.get('prescriptions',[]))}\n"
            f"  eMAR entries:  {len(_data_ref.get('emar',[]))}\n"
            f"  ICU stays:     {len(_data_ref.get('icustays',[]))}\n"
            f"  Notes:         {len(_data_ref.get('noteevents',[]))}\n"
            f"  Tables queried:{total_tables}  Total records:{total_records}"
        )

    # 5. ROUGE scoring against MIMIC ground-truth discharge note (fire-and-forget, non-blocking)
    rouge_scores: dict = {}
    if source != "db" and generated_text and not generation_error:
        try:
            ref_note = data.get("discharge_note_text") if not _skip_to_pass2 else None
            if ref_note:
                from rouge_score import rouge_scorer as _rs
                _scorer = _rs.RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=True)
                _scores = _scorer.score(ref_note, generated_text)
                rouge_scores = {
                    "rouge1": round(_scores["rouge1"].fmeasure, 4),
                    "rouge2": round(_scores["rouge2"].fmeasure, 4),
                    "rougeL": round(_scores["rougeL"].fmeasure, 4),
                }
                log.info(f"ROUGE — R1={rouge_scores['rouge1']} R2={rouge_scores['rouge2']} RL={rouge_scores['rougeL']} (target RL>0.45)")
            else:
                log.info(f"ROUGE skipped — no MIMIC discharge note found for hadm_id={hadm_id}")
        except Exception as _re:
            log.warning(f"ROUGE scoring failed (non-fatal): {_re}")

    # 6. Save to app DB
    # Order: upsert summary → Pass 3 verification → mark Ready for Review
    # This ensures tier counts are accurate BEFORE the doctor sees the entry in the queue.
    gdb.upsert_summary(
        enc_id, generated_text,
        clinical_context=clinical_context,
        pass1_latency_s=pass1_latency,
        pass2_latency_s=pass2_latency,
        total_latency_s=total_latency,
        rouge1=rouge_scores.get("rouge1"),
        rouge2=rouge_scores.get("rouge2"),
        rougeL=rouge_scores.get("rougeL"),
        summary_version=new_version,
        pass1_version=PASS1_VERSION,
        pass2_version=PASS2_VERSION,
        sections_json=sections_json if sections_json else None,
    )
    if sections_json:
        try:
            _gt1 = sum(1 for _s in sections_json.values() if isinstance(_s, dict) and _s.get("tier") == "T1")
            _gt2 = sum(1 for _s in sections_json.values() if isinstance(_s, dict) and _s.get("tier") == "T2")
            _gt3 = sum(1 for _s in sections_json.values() if isinstance(_s, dict) and _s.get("tier") == "T3")
            _gdl = sum(1 for _s in sections_json.values() if isinstance(_s, dict) and _s.get("tier") not in ("OK", None))
            gdb.update_summary(enc_id, {"gap_t1": _gt1, "gap_t2": _gt2, "gap_t3": _gt3, "dl_flags": _gdl})
        except Exception as _gce:
            log.warning(f"Gap count update error: {_gce}")

    # Pass 3: synchronous LLM cross-verification — runs BEFORE status → Ready for Review
    # so tier flags in the queue are accurate when the doctor sees them.
    if sections_json and clinical_json and not generation_error:
        try:
            await run_in_threadpool(_run_verification_pass_sync, enc_id, sections_json, clinical_json)
        except Exception as _p3e:
            log.warning(f"Pass 3 error for HADM {hadm_id}: {_p3e}")

    # Mark Ready for Review AFTER Pass 3 — tier counts are now accurate
    try:
        _enc_update: dict = {"status": "Ready for Review", "version": new_version}
        if req and req.discharge_type:
            _enc_update["discharge_type"] = req.discharge_type
        gdb.update_encounter(enc_id, _enc_update)
    except Exception as _dbu:
        log.error(f"DB status update failed for HADM {hadm_id} (resetting): {_dbu}")
        try:
            gdb.update_encounter(enc_id, {"status": "Pending Ingestion"})
        except Exception:
            pass
        raise HTTPException(500, f"Failed to save summary status: {_dbu}")

    # 7. Audit log
    try:
        gdb.log_action("SUMMARY_GENERATED", hadm_id=hadm_id, details={
            "tables_queried":  total_tables,
            "records_fetched": total_records,
            "llm":  GEMINI_MODEL if (generated_text and not generation_error) else "none",
            "pass1_latency_s": pass1_latency,
            "pass2_latency_s": pass2_latency,
            "total_latency_s": total_latency,
            "rouge_scores":    rouge_scores or None,
            "error": generation_error,
        })
    except Exception:
        pass

    log.info(f"Summary generation complete for HADM {hadm_id}")

    # Persist encounter data so the GCS DB knows about this HADM even for GCS-sourced records
    if source == "gcs" and not gdb.get_encounter_by_hadm(hadm_id):
        gdb.create_encounter(hadm_id, status="Ready for Review")

    return {
        "status": "success",
        "source": source,
        "summary": generated_text,
        "generation_error": generation_error,
        "clinical_context": clinical_context,
        "table_log": table_log,
        "summary_version": new_version,
        "prompt_version": {"pass1": PASS1_VERSION, "pass2": PASS2_VERSION},
        "sections_json": sections_json if sections_json else None,
        "latency": {
            "pass1_s":  pass1_latency,
            "pass2_s":  pass2_latency,
            "total_s":  total_latency,
            "target_s": 30,
            "ok":       total_latency < 30,
        },
        "rouge": rouge_scores if rouge_scores else None,
        "data_points_analyzed": {
            "tables_queried":    total_tables,
            "total_records":     total_records,
            **({
                "labs":              len(_data_ref.get("labevents", [])),
                "prescriptions":     len(_data_ref.get("prescriptions", [])),
                "pharmacy":          len(_data_ref.get("pharmacy", [])),
                "emar":              len(_data_ref.get("emar", [])),
                "emar_detail":       len(_data_ref.get("emar_detail", [])),
                "diagnoses":         len(_data_ref.get("diagnoses", [])),
                "procedures_icd":    len(_data_ref.get("procedures_icd", [])),
                "notes":             len(_data_ref.get("noteevents", [])),
                "icu_stays":         len(_data_ref.get("icustays", [])),
                "chart_events":      len(_data_ref.get("chartevents", [])),
                "input_events":      len(_data_ref.get("inputevents", [])),
                "output_events":     len(_data_ref.get("outputevents", [])),
                "proc_events":       len(_data_ref.get("procevents", [])),
                "ingredient_events": len(_data_ref.get("ingredients", [])),
                "datetime_events":   len(_data_ref.get("dtevents", [])),
                "microbiology":      len(_data_ref.get("microevents", [])),
                "transfers":         len(_data_ref.get("transfers", [])),
                "services":          len(_data_ref.get("services", [])),
                "drg_codes":         len(_data_ref.get("drg_codes", [])),
                "poe":               len(_data_ref.get("poe", [])),
                "poe_detail":        len(_data_ref.get("poe_detail", [])),
                "hcpcsevents":       len(_data_ref.get("hcpcsevents", [])),
                "omr":               len(_data_ref.get("omr", [])),
            } if not _skip_to_pass2 else {}),
        },
    }


@app.post("/api/encounters/{hadm_id}/reset_generation")
async def reset_generation(hadm_id: int):
    """Reset a stuck 'Processing' encounter back to 'Pending Ingestion' so the user can start fresh."""
    enc = gdb.get_encounter_by_hadm(hadm_id)
    if not enc:
        raise HTTPException(404, "Encounter not found")
    if enc.get("status") != "Processing":
        return {"status": "ok", "message": f"Already '{enc.get('status')}' — no change needed"}
    gdb.update_encounter(enc["id"], {"status": "Pending Ingestion"})
    log.info(f"reset_generation: HADM {hadm_id} manually reset from Processing → Pending Ingestion")
    return {"status": "ok", "message": "Reset to 'Pending Ingestion'"}


@app.post("/api/encounters/reset_all_stuck")
async def reset_all_stuck():
    """Reset ALL encounters currently stuck in 'Processing' back to 'Pending Ingestion'."""
    stuck = gdb.list_encounters(status="Processing")
    reset_ids = []
    for enc in (stuck or []):
        gdb.update_encounter(enc["id"], {"status": "Pending Ingestion"})
        reset_ids.append(enc.get("hadm_id") or enc.get("id"))
        log.info(f"reset_all_stuck: {enc.get('hadm_id')} reset Processing → Pending Ingestion")
    return {"status": "ok", "reset_count": len(reset_ids), "reset_ids": reset_ids}


@app.post("/api/encounters/{hadm_id}/force_pending")
async def force_pending(hadm_id: int):
    """Force any encounter to 'Pending Ingestion' status regardless of current state."""
    enc = gdb.get_encounter_by_hadm(hadm_id)
    if not enc:
        raise HTTPException(404, "Encounter not found")
    prev = enc.get("status", "unknown")
    gdb.update_encounter(enc["id"], {"status": "Pending Ingestion"})
    log.info(f"force_pending: HADM {hadm_id} forced {prev} → Pending Ingestion")
    return {"status": "ok", "previous": prev, "current": "Pending Ingestion"}


@app.post("/api/encounters/{hadm_id}/force_review")
async def force_review(hadm_id: int):
    """Force any encounter to 'Awaiting Review' (shows as 'In Review' on dashboard)."""
    enc = gdb.get_encounter_by_hadm(hadm_id)
    if not enc:
        raise HTTPException(404, "Encounter not found")
    prev = enc.get("status", "unknown")
    gdb.update_encounter(enc["id"], {"status": "Awaiting Review"})
    log.info(f"force_review: HADM {hadm_id} forced {prev} → Awaiting Review")
    return {"status": "ok", "previous": prev, "current": "Awaiting Review"}


@app.post("/api/encounters/promote_files_ready_to_review")
async def promote_files_ready_to_review():
    """Change all 'Files Ready' encounters to 'Awaiting Review' in one shot."""
    ready = gdb.list_encounters(status="Files Ready")
    updated = []
    for enc in (ready or []):
        gdb.update_encounter(enc["id"], {"status": "Awaiting Review"})
        updated.append(enc.get("hadm_id") or enc.get("id"))
        log.info(f"promote_to_review: {enc.get('hadm_id')} Files Ready → Awaiting Review")
    return {"status": "ok", "updated_count": len(updated), "updated_ids": updated}


# ── Regenerate single NABH section (doctor feedback → AI fix) ─────────────────
_NABH_SECTION_RULES = {
    "s1":  "S1 — Patient Demographics: Name, Age/Gender, HADM ID, Ward, Admission Date, Discharge Date, Admission Type, Admitted From, Discharged To. Exact values from source only.",
    "s2":  "S2 — Chief Complaint: State the primary documented diagnosis and admission type only. No added symptom words.",
    "s3":  "S3 — History of Presenting Illness: Use DRG description, admission type, primary diagnosis, and admission labs. State documented diagnoses. Report abnormal labs by name and value — no clinical interpretation.",
    "s4":  "S4 — Significant Past History: List all secondary diagnoses as documented conditions. Do not label any as 'active' or 'controlled'.",
    "s5":  "S5 — Examination Findings: Use vital signs data only. If unavailable write: 'Vital signs on admission were not recorded in the structured data.'",
    "s6":  "S6 — Laboratory Investigations: ALL lab values. Compact inline grouped by category. Show admission→discharge pairs where both exist. Mark flagged values as '(abnormal)' or '(low)' or '(high)' exactly as flagged in the source data. Format: *Category*: Name value→value (abnormal); Name2 value2 unit; Append *Microbiology Cultures*: section if data available.",
    "s7":  "S7 — Imaging & Procedure Findings: List imaging orders by name and date only. No findings or interpretations added.",
    "s8":  "S8 — Working Diagnosis at Admission: Primary diagnosis as working diagnosis. Include differentials only if documented.",
    "s9":  "S9 — Hospital Course: Narrate ONLY documented events — ward movements with dates, procedures, imaging orders (name+date), medication counts from eMAR, discharge date and destination. No clinical reasoning.",
    "s10": "S10 — Procedures Performed: One procedure per line with documented date. Include hemodialysis sessions from physician orders.",
    "s11": "S11 — Discharge Medications: Numbered list. Format exactly: 'N. Drug Dose – Route'. No frequency. No extras.",
    "s12": "S12 — Follow-up & Discharge Advice: Follow-up with services as arranged. Transcribe explicit discharge advice if documented.",
    "s13": "S13 — Discharge Diagnosis: All diagnoses, primary first, one per line. Names only — no ICD codes.",
    "s14": "S14 — Condition at Discharge: Discharge destination and documented discharge lab values only. No 'stable' or 'improved' unless explicitly in source.",
    "s15": "S15 — Patient Acknowledgement: Write exactly: 'Patient acknowledgement to be confirmed by the resident prior to physician sign-off (NABH MN4 requirement). Signature and timestamp to be recorded in the physical file.'",
}

class RegenerateSectionRequest(BaseModel):
    section_id:       str
    section_label:    str
    doctor_feedback:  str
    current_text:     str

@app.post("/api/encounters/{hadm_id}/regenerate_section")
async def regenerate_section(hadm_id: int, req: RegenerateSectionRequest):
    enc = gdb.get_encounter_by_hadm(hadm_id)
    if not enc:
        raise HTTPException(status_code=404, detail="Encounter not found")
    summary_rec = gdb.get_summary_by_encounter(enc["id"])
    clinical_context = (summary_rec or {}).get("clinical_context", "")
    if not clinical_context:
        raise HTTPException(status_code=400, detail="No clinical context stored — generate the full summary first so the AI has source data to work from.")
    section_rule = _NABH_SECTION_RULES.get(req.section_id, f"{req.section_label}: Accurately describe what is in the source data for this section.")
    prompt = f"""You are a medical scribe making a minimal correction to one entry in a NABH discharge summary section. CRITICAL: Do NOT fabricate or infer data.

SECTION: {req.section_label} ({req.section_id.upper()})

FULL CURRENT SECTION TEXT (copy this exactly, changing only what the doctor specifies):
{req.current_text}

DOCTOR'S INSTRUCTION (apply this correction to the ONE matching entry only):
{req.doctor_feedback}

SECTION FORMAT RULE:
{section_rule}

CLINICAL SOURCE DATA (ground truth):
{clinical_context}

TASK — READ CAREFULLY:
1. Output the COMPLETE section text above, character-for-character, with ONLY the one entry the doctor described changed
2. Every other line, value, label, and piece of formatting must remain EXACTLY as it appears above — do not reorder, remove, add, or reformat anything else
3. Change ONLY the specific entry the doctor's instruction refers to; leave all other entries untouched
4. Keep the EXACT SAME FORMAT for the corrected entry (inline, bullet, label — whatever it is now)
5. Do NOT add any explanation, prefix, header, or commentary
6. DOCTOR'S AUTHORITY: The doctor's instruction is a clinician's correction and takes priority over the clinical source data for the ONE specific fact they are correcting. Apply the doctor's stated value exactly as instructed. The source data is reference only — it does not override the doctor's explicit correction.
7. Write in English only
8. CRITICAL: If the doctor says "had growth" or similar, modify ONLY that specific entry — do NOT duplicate or append rows

Corrected full section text (output ONLY this, nothing else):"""

    log.info(f"regenerate_section HADM={hadm_id} section={req.section_id}: {req.doctor_feedback[:120]}")
    text, error = await run_in_threadpool(_call_gemini, prompt)
    if not text:
        raise HTTPException(status_code=500, detail=error or "AI generation failed")
    try:
        gdb.log_action("SECTION_REGENERATED", hadm_id=hadm_id, details={
            "section_id":      req.section_id,
            "doctor_feedback": req.doctor_feedback[:300],
        })
    except Exception:
        pass
    return {"section_id": req.section_id, "section_text": text.strip()}


# ── Send back for revision ─────────────────────────────────────────────────────
class SendRevisionRequest(BaseModel):
    reason: str

@app.post("/api/encounters/{hadm_id}/send_revision")
def send_revision(hadm_id: int, req: SendRevisionRequest):
    enc = gdb.get_encounter_by_hadm(hadm_id)
    if not enc:
        raise HTTPException(status_code=404, detail=f"No encounter found for HADM {hadm_id}")
    updated = gdb.update_encounter(enc["id"], {
        "status":          "Revision Requested",
        "revision_reason": req.reason,
        "revision_at":     datetime.utcnow().isoformat(),
    })
    try:
        gdb.log_action("REVISION_REQUESTED", hadm_id=hadm_id, details={
            "encounter_id": enc["id"],
            "reason":       req.reason[:300],
        })
    except Exception:
        pass
    return updated or enc


# ── Full 7-Step Rejection Flow ────────────────────────────────────────────────

class RejectRequest(BaseModel):
    reason:       str
    prev_t1_count: int = 0
    rejected_by:  Optional[str] = None   # user UUID

@app.post("/api/encounters/{hadm_id}/reject")
def reject_encounter(hadm_id: int, req: RejectRequest):
    """Step 1–2: Doctor submits rejection. Creates rejection_log entry + updates encounter status."""
    enc = gdb.get_encounter_by_hadm(hadm_id)
    if not enc:
        raise HTTPException(404, f"No encounter for HADM {hadm_id}")
    version = (enc.get("rejection_count") or 0) + 1
    # Create audit log entry
    try:
        rl = gdb.create_rejection_log(
            encounter_id=enc["id"],
            hadm_id=hadm_id,
            rejected_by=req.rejected_by,
            reason=req.reason,
            prev_t1=req.prev_t1_count,
            version=version,
        )
    except Exception:
        rl = {}
    # Update encounter status
    gdb.update_encounter(enc["id"], {
        "status":           "Revision Requested",
        "revision_reason":  req.reason,
        "revision_at":      datetime.utcnow().isoformat(),
        "rejection_count":  version,
    })
    try:
        gdb.log_action("REJECTED", hadm_id=hadm_id, details={
            "encounter_id": enc["id"], "reason": req.reason[:300], "version": version,
        })
    except Exception:
        pass
    return {"ok": True, "rejection_log_id": rl.get("id"), "version": version}


class RegenerateRequest(BaseModel):
    rejection_log_id: Optional[int] = None
    discharge_type:   Optional[str] = None

@app.post("/api/encounters/{hadm_id}/trigger_regeneration")
async def trigger_regeneration(hadm_id: int, req: RegenerateRequest):
    """Step 4: Admin triggers LLM re-run with rejection context injected into prompt."""
    enc = gdb.get_encounter_by_hadm(hadm_id)
    if not enc:
        raise HTTPException(404, f"No encounter for HADM {hadm_id}")

    # Mark encounter as Processing so doctor sees regen in progress
    gdb.update_encounter(enc["id"], {"status": "Processing"})

    # Record that regeneration was triggered
    if req.rejection_log_id:
        try:
            gdb.update_rejection_log(req.rejection_log_id, {
                "regeneration_triggered_at": datetime.utcnow().isoformat()
            })
        except Exception:
            pass

    # Fetch rejection reason so it can be injected into the prompt
    rejection_ctx = ""
    try:
        rl_list = gdb.get_rejection_log(enc["id"])
        if rl_list:
            rejection_ctx = rl_list[0].get("rejection_reason", "")
    except Exception:
        pass

    # Build request with rejection context — same path as clicking Generate in UI
    regen_req = GenerateSummaryRequest(
        discharge_type=req.discharge_type or enc.get("discharge_type"),
        rejection_context=rejection_ctx or None,
    )

    try:
        result = await generate_summary(hadm_id, source="bq", req=regen_req)
    except HTTPException:
        gdb.update_encounter(enc["id"], {"status": "Revision Requested"})
        raise
    except Exception as e:
        log.warning(f"Regeneration failed for HADM {hadm_id}: {e}")
        gdb.update_encounter(enc["id"], {"status": "Revision Requested"})
        raise HTTPException(500, f"Regeneration failed: {e}")

    if req.rejection_log_id:
        try:
            gdb.update_rejection_log(req.rejection_log_id, {
                "regenerated_at": datetime.utcnow().isoformat(),
                "new_t1_count":   0,
            })
        except Exception:
            pass

    try:
        gdb.log_action("REGENERATED", hadm_id=hadm_id, details={
            "encounter_id": enc["id"], "rejection_log_id": req.rejection_log_id,
        })
    except Exception:
        pass

    return {"ok": True, "summary_generated": True, "new_t1_count": 0, "auto_resolved": []}


@app.post("/api/encounters/{hadm_id}/notify_doctor")
def notify_doctor(hadm_id: int, rejection_log_id: Optional[int] = None):
    """Step 5: Send DPDPA-compliant non-PHI notification to assigned doctor."""
    enc = gdb.get_encounter_by_hadm(hadm_id)
    if not enc:
        raise HTTPException(404, f"No encounter for HADM {hadm_id}")
    # Update status to Awaiting Review so doctor queue shows the case
    gdb.update_encounter(enc["id"], {"status": "Awaiting Review"})
    now_iso = datetime.utcnow().isoformat()
    if rejection_log_id:
        try:
            gdb.update_rejection_log(rejection_log_id, {"notification_sent_at": now_iso})
        except Exception:
            pass
    # In production: integrate Firebase / SNS push notification here.
    # For now, log the event and return a non-PHI notification payload.
    case_ref = f"PT-{str(hadm_id)[:2]}-XXXX"   # DPDPA: no patient-identifying info
    try:
        gdb.log_action("NOTIFICATION_SENT", hadm_id=hadm_id, details={
            "case_ref": case_ref, "rejection_log_id": rejection_log_id,
        })
    except Exception:
        pass
    return {
        "ok":       True,
        "sent_at":  now_iso,
        "case_ref": case_ref,
        "message":  "A discharge summary assigned to you has been regenerated and is ready for review.",
        "dpdpa":    "No PHI included — patient identified by internal case reference only.",
    }


@app.get("/api/encounters/{hadm_id}/rejection_log")
def get_rejection_log(hadm_id: int):
    """Get full rejection audit trail for an encounter."""
    enc = gdb.get_encounter_by_hadm(hadm_id)
    if not enc:
        raise HTTPException(404, f"No encounter for HADM {hadm_id}")
    logs = gdb.get_rejection_log(enc["id"])
    return {"encounter_id": enc["id"], "hadm_id": hadm_id, "rejections": logs}


@app.get("/api/rejection_logs")
def list_rejection_logs(limit: int = 50):
    """All rejection log entries across all encounters — for ward admin audit view."""
    return gdb.list_rejection_logs(limit=limit)


# ── Amendment (S7) ────────────────────────────────────────────────────────────

class AmendmentRequest(BaseModel):
    reason:            str
    section:           str
    details:           str
    doc_name:          Optional[str] = None
    submitted_by_name: Optional[str] = ""
    from_version:      Optional[str] = "v1.0"

@app.post("/api/amendments/{encounter_id}")
def create_amendment(encounter_id: str, req: AmendmentRequest):
    """Persist an amendment request (S7 form submission) to the DB."""
    enc = gdb.get_encounter_by_id(encounter_id)
    if not enc:
        raise HTTPException(404, f"Encounter {encounter_id} not found")
    hadm_id = enc.get("hadm_id", 0)
    # Build deterministic ref: AMD-YYYY-{hadm_id}-{count+1}
    existing = gdb.get_latest_amendment(encounter_id)
    seq = 1 if not existing else 2
    amendment_ref = f"AMD-{datetime.utcnow().year}-{hadm_id}-{seq:02d}"
    row = gdb.create_amendment(
        encounter_id=encounter_id,
        hadm_id=hadm_id,
        amendment_ref=amendment_ref,
        reason=req.reason,
        section=req.section,
        details=req.details,
        doc_name=req.doc_name,
        submitted_by_name=req.submitted_by_name or "",
        from_version=req.from_version or "v1.0",
        to_version="v1.1",
    )
    try:
        gdb.log_action("AMENDMENT_SUBMITTED", hadm_id=hadm_id, details={
            "amendment_ref": amendment_ref, "section": req.section
        })
    except Exception:
        pass
    try:
        with _get_engine().begin() as _conn:
            _conn.execute(
                _text("UPDATE billing_records SET billing_phase='amendment_pending', updated_at=NOW() WHERE hadm_id=:h AND billing_phase='reconciliation_pending'"),
                {"h": hadm_id}
            )
    except Exception:
        pass
    return {"ok": True, "amendment_ref": amendment_ref, "id": row.get("id"), "created_at": row.get("created_at")}


@app.get("/api/amendments/{encounter_id}")
def get_amendment(encounter_id: str):
    """Return the latest amendment and total amendment count for an encounter."""
    row   = gdb.get_latest_amendment(encounter_id)
    count = gdb.count_amendments(encounter_id)
    return {"ok": True, "amendment": row or None, "amendment_count": count}


@app.get("/api/encounters/{hadm_id}/revision_state")
def get_revision_state(hadm_id: int):
    """
    Shared 7-step revision state for all screens (doctor / resident / ward admin).
    Returns the active rejection loop state so all clients show the same step.
    """
    enc = gdb.get_encounter_by_hadm(hadm_id)
    if not enc:
        raise HTTPException(404, f"No encounter for HADM {hadm_id}")

    rl = gdb.get_latest_rejection_log_with_user(enc["id"])
    if not rl:
        return {
            "active": False,
            "hadm_id": hadm_id,
            "enc_status": enc.get("status"),
            "rejection_reason": enc.get("revision_reason"),
            "rejected_by_name": None,
        }

    # Compute current step from timestamps
    step = 1
    if rl.get("rejected_at"):               step = 2
    if rl.get("files_ready_at"):            step = 3
    if rl.get("regeneration_triggered_at"): step = 4
    if rl.get("notification_sent_at"):      step = 5
    if rl.get("re_reviewed_at"):            step = 6
    if rl.get("signed_at"):                 step = 7

    def _ts(v):
        return v.isoformat() if v and hasattr(v, "isoformat") else v

    return {
        "active":             not bool(rl.get("signed_at")),
        "hadm_id":            hadm_id,
        "step":               step,
        "rejection_log_id":   rl["id"],
        "rejection_reason":   rl.get("rejection_reason"),
        "rejected_by_name":   rl.get("rejected_by_name"),
        "enc_status":         enc.get("status"),
        "timestamps": {
            "rejected_at":               _ts(rl.get("rejected_at")),
            "files_ready_at":            _ts(rl.get("files_ready_at")),
            "regeneration_triggered_at": _ts(rl.get("regeneration_triggered_at")),
            "regenerated_at":            _ts(rl.get("regenerated_at")),
            "notification_sent_at":      _ts(rl.get("notification_sent_at")),
            "re_reviewed_at":            _ts(rl.get("re_reviewed_at")),
            "signed_at":                 _ts(rl.get("signed_at")),
        },
    }


class RejectionLogPatch(BaseModel):
    re_reviewed_at: Optional[str] = None
    signed_at:      Optional[str] = None
    new_t1_count:   Optional[int] = None

@app.patch("/api/rejection_logs/{log_id}")
def patch_rejection_log(log_id: int, req: RejectionLogPatch):
    """Update step timestamps (re_reviewed_at, signed_at) from the doctor's client."""
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "No fields to update")
    return gdb.update_rejection_log(log_id, fields)


# ── Error Log (3-Tier Accuracy Framework) ────────────────────────────────────

class ErrorLogRequest(BaseModel):
    hadm_id:         Optional[str]  = None
    nabh_section:    Optional[str]  = None
    error_tier:      int
    ai_output:       Optional[str]  = None
    correct_value:   Optional[str]  = None
    error_category:  Optional[str]  = None   # formatting | medication_dose | diagnosis | hallucination | other
    source_present:  Optional[bool] = None
    attending_id:    Optional[str]  = None
    summary_version: Optional[str]  = None

@app.post("/api/errors")
def create_error_log(req: ErrorLogRequest):
    if req.error_tier not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="error_tier must be 1, 2, or 3")
    entry = gdb.log_error(
        hadm_id        = req.hadm_id,
        error_tier     = req.error_tier,
        nabh_section   = req.nabh_section,
        ai_output      = req.ai_output,
        correct_value  = req.correct_value,
        error_category = req.error_category,
        source_present = req.source_present,
        attending_id   = req.attending_id,
        summary_version= req.summary_version,
    )
    # Check pilot gate: if 7-day T3 rate > 25%, flag it
    try:
        stats = gdb.get_error_stats()
        entry["gate_status"] = "pause" if (stats.get("tier3_rate_pct") or 0) > 25 else "ok"
        entry["tier3_rate_pct"] = stats.get("tier3_rate_pct", 0)
    except Exception:
        entry["gate_status"] = "ok"
    return entry

@app.get("/api/errors/stats")
def get_error_stats():
    try:
        return gdb.get_error_stats()
    except Exception as e:
        return {"tier3_count": 0, "total_errors": 0, "tier3_rate_pct": 0, "by_tier": [], "by_section": []}


# ── Usability Ratings (5-point scale, CMO demo) ───────────────────────────────
class UsabilityRatingRequest(BaseModel):
    encounter_id:  Optional[str] = None
    hadm_id:       Optional[int] = None
    attending_id:  Optional[str] = None
    rating:        int   # 1–5
    feedback:      Optional[str] = None

@app.post("/api/usability_rating")
def create_usability_rating(req: UsabilityRatingRequest):
    if req.rating not in (1, 2, 3, 4, 5):
        raise HTTPException(status_code=400, detail="rating must be 1–5")
    entry = gdb.log_usability_rating(
        encounter_id=req.encounter_id,
        hadm_id=req.hadm_id,
        attending_id=req.attending_id,
        rating=req.rating,
        feedback=req.feedback,
    )
    return entry

@app.get("/api/usability_rating/stats")
def get_usability_stats():
    try:
        return gdb.get_usability_stats()
    except Exception:
        return {"total_ratings": 0, "avg_rating": 0.0, "distribution": {}, "target": 4.0}


@app.get("/api/prompt_version_log")
def get_prompt_version_log():
    """Return per-prompt-version Tier 3 rate for the PM version log table."""
    try:
        return gdb.get_prompt_version_log()
    except Exception as e:
        log.warning(f"prompt_version_log failed: {e}")
        return {"versions": [], "current": {"pass1": PASS1_VERSION, "pass2": PASS2_VERSION}}


@app.get("/api/cmo/metrics")
def get_cmo_metrics():
    """Real, computed CMO pilot-dashboard data — replaces the hardcoded values that used
    to live directly in cmo.html. Baseline (pre-pilot) figures have no live data source
    (they're a one-time historical measurement) and stay as fixed reference constants;
    everything under "pilot" is computed live from the DB."""
    from sqlalchemy import text as _text
    from .cloud_sql_db import get_engine as _get_engine

    BASELINE_DOC_TIME_MIN = 192        # 3.2h — pre-pilot manual documentation time
    BASELINE_NABH_PCT     = 71.0       # pre-pilot NABH compliance average

    with _get_engine().connect() as conn:
        core = conn.execute(_text("""
            SELECT
                COUNT(*) FILTER (WHERE e.status = 'Signed Off')                          AS signed_count,
                COUNT(*)                                                                  AS total_summaries,
                COUNT(*) FILTER (WHERE s.gap_t1 > 0)                                      AS t1_flagged,
                AVG(EXTRACT(EPOCH FROM (s.signed_at - e.created_at)))
                    FILTER (WHERE s.signed_at IS NOT NULL)                                AS avg_doc_time_s
            FROM app_summaries s
            JOIN app_encounters e ON e.id = s.encounter_id
        """)).fetchone()

        rej = conn.execute(_text("""
            SELECT
                COUNT(*)                                                                  AS rejections,
                AVG(EXTRACT(EPOCH FROM (signed_at - rejected_at)))
                    FILTER (WHERE signed_at IS NOT NULL)                                  AS avg_resign_s
            FROM rejection_log
        """)).fetchone()

        section_rows = conn.execute(_text("""
            SELECT
                nabh_section,
                COUNT(*) FILTER (WHERE error_tier = 1) AS t1,
                COUNT(*) FILTER (WHERE error_tier = 2) AS t2
            FROM error_log
            WHERE nabh_section IS NOT NULL
            GROUP BY nabh_section
            ORDER BY nabh_section
        """)).fetchall()

    total_summaries = int(core[1] or 0)
    denom = max(total_summaries, 1)

    sections = []
    for sec, t1, t2 in section_rows:
        t1_rate = round(t1 / denom * 100, 1)
        t2_rate = round(t2 / denom * 100, 1)
        sections.append({
            "section": sec,
            "section_label": _PASS3_SECTION_LABELS.get(sec, sec),
            "accuracy_pct": round(max(0.0, 100 - t1_rate - t2_rate), 1),
            "t1_rate_pct": t1_rate,
            "t2_rate_pct": t2_rate,
        })
    nabh_compliance_pct = round(
        sum(s["accuracy_pct"] for s in sections) / len(sections), 1
    ) if sections else None

    avg_doc_time_s = core[3]
    avg_doc_time_min = round(avg_doc_time_s / 60, 0) if avg_doc_time_s else None
    doc_time_delta_pct = (
        round((avg_doc_time_min - BASELINE_DOC_TIME_MIN) / BASELINE_DOC_TIME_MIN * 100, 0)
        if avg_doc_time_min is not None else None
    )
    nabh_delta_pct = (
        round(nabh_compliance_pct - BASELINE_NABH_PCT, 0) if nabh_compliance_pct is not None else None
    )

    avg_resign_s = rej[1]
    avg_resign_min = round(avg_resign_s / 60) if avg_resign_s else None

    try:
        usability = gdb.get_usability_stats()
    except Exception:
        usability = {"total_ratings": 0, "avg_rating": 0.0, "distribution": {}}

    return {
        "pilot": {
            "total_summaries":       total_summaries,
            "signed_count":          int(core[0] or 0),
            "avg_doc_time_minutes":  avg_doc_time_min,
            "nabh_compliance_pct":   nabh_compliance_pct,
            "t1_flag_rate_pct":      round((core[2] or 0) / denom * 100, 1),
            "rejections":            int(rej[0] or 0),
            "avg_resign_minutes":    avg_resign_min,
            "usability_avg_rating":  usability.get("avg_rating", 0.0),
            "usability_total_ratings": usability.get("total_ratings", 0),
            "usability_recommend_pct": round(
                (usability["distribution"].get("5", 0) + usability["distribution"].get("4", 0))
                / max(usability.get("total_ratings", 0), 1) * 100, 0
            ) if usability.get("total_ratings") else None,
        },
        "baseline": {
            "doc_time_minutes": BASELINE_DOC_TIME_MIN,
            "nabh_compliance_pct": BASELINE_NABH_PCT,
        },
        "deltas": {
            "doc_time_pct":  doc_time_delta_pct,
            "nabh_pct_pts":  nabh_delta_pct,
        },
        "section_accuracy": sections,
        "not_tracked": {
            "phi_breaches": "No PHI-breach logging table exists — no incidents logged, not actively monitored.",
            "dpdpa_consent_rate": "Consent checkbox is client-side only (upload.html) and not persisted to the DB.",
        },
    }


@app.get("/api/demo/cases")
def get_demo_cases():
    """List all synthetic Indian demo patients available for offline/always-on demo."""
    from .synthetic_demo import list_demo_cases as _list_demo
    return {"cases": _list_demo()}


# ── Users ──────────────────────────────────────────────────────────────────────
@app.get("/api/users")
def get_users(role: Optional[str] = None):
    return gdb.list_users(role=role)

@app.get("/api/users/doctors")
def get_doctors():
    return gdb.list_users(role="Doctor")


# ── Super Admin — User Management ─────────────────────────────────────────────
_ADMIN_CREATABLE_ROLES = {
    "Doctor", "Admin Staff", "Billing Staff", "Super Admin",
    "Ward Nurse", "Charge Nurse", "GW Nurse", "Resident",
}

class AdminCreateUserRequest(BaseModel):
    full_name:       str
    hospital_email:  str
    password:        str
    role:            str
    ward_assignment: Optional[str] = None

@app.post("/api/admin/users")
def admin_create_user(req: AdminCreateUserRequest):
    if req.role not in _ADMIN_CREATABLE_ROLES:
        raise HTTPException(status_code=400,
            detail=f"role must be one of: {', '.join(sorted(_ADMIN_CREATABLE_ROLES))}")
    if gdb.user_exists(req.hospital_email):
        raise HTTPException(status_code=409, detail="Email already registered")
    hashed = _bcrypt.hashpw(req.password.encode(), _bcrypt.gensalt()).decode()
    created = gdb.create_user(
        email=req.hospital_email, password_hash=hashed,
        role=req.role, full_name=req.full_name,
    )
    if req.ward_assignment:
        created = gdb.update_user(created["id"], {"ward_assignment": req.ward_assignment}) or created
    return created

@app.post("/api/admin/users/{user_id}/deactivate")
def admin_deactivate_user(user_id: str):
    updated = gdb.update_user(user_id, {"is_active": False})
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return updated


# ── Super Admin — Settings (NEWS2 thresholds + module toggles) ───────────────
@app.get("/api/admin/settings")
def admin_get_settings():
    from sqlalchemy import text as _text
    from .cloud_sql_db import get_engine as _get_engine
    with _get_engine().connect() as conn:
        row = conn.execute(_text(
            "SELECT module_toggles, news2_thresholds FROM app_settings WHERE id = 1"
        )).fetchone()
    if not row:
        raise HTTPException(status_code=500, detail="app_settings row missing")
    return {"module_toggles": row[0] or {}, "news2_thresholds": row[1] or {}}

class AdminSettingsUpdateRequest(BaseModel):
    module_toggles:   Optional[Dict[str, Any]] = None
    news2_thresholds: Optional[Dict[str, Any]] = None

@app.patch("/api/admin/settings")
def admin_update_settings(req: AdminSettingsUpdateRequest):
    import json as _json
    from sqlalchemy import text as _text
    from .cloud_sql_db import get_engine as _get_engine
    set_parts, params = [], {}
    if req.module_toggles is not None:
        set_parts.append("module_toggles = module_toggles || CAST(:mt AS jsonb)")
        params["mt"] = _json.dumps(req.module_toggles)
    if req.news2_thresholds is not None:
        set_parts.append("news2_thresholds = news2_thresholds || CAST(:nt AS jsonb)")
        params["nt"] = _json.dumps(req.news2_thresholds)
    if not set_parts:
        return admin_get_settings()
    with _get_engine().begin() as conn:
        conn.execute(_text(f"UPDATE app_settings SET {', '.join(set_parts)}, updated_at = NOW() WHERE id = 1"), params)
    return admin_get_settings()


# ── Super Admin — Drug-Lab Interaction Rules ──────────────────────────────────
@app.get("/api/admin/drug-lab-rules")
def admin_list_drug_lab_rules():
    from sqlalchemy import text as _text
    from .cloud_sql_db import get_engine as _get_engine
    with _get_engine().connect() as conn:
        rows = conn.execute(_text(
            "SELECT * FROM drug_lab_rules ORDER BY rule_code"
        )).fetchall()
    return [dict(r._mapping) for r in rows]

class DrugLabRuleRequest(BaseModel):
    agent_a:          Optional[str] = None
    agent_b:           str
    interaction_type:  str   # DDI | DLI | LI
    severity:           str  # T1 | T2
    action_required:   str
    evidence:          Optional[str] = None
    is_active:         bool = True

@app.post("/api/admin/drug-lab-rules")
def admin_create_drug_lab_rule(req: DrugLabRuleRequest):
    from sqlalchemy import text as _text
    from .cloud_sql_db import get_engine as _get_engine
    with _get_engine().begin() as conn:
        next_num = conn.execute(_text(
            "SELECT COALESCE(MAX(CAST(SUBSTRING(rule_code FROM 3) AS INTEGER)), 0) + 1 FROM drug_lab_rules"
        )).scalar()
        rule_code = f"R-{next_num:03d}"
        row = conn.execute(_text("""
            INSERT INTO drug_lab_rules (rule_code, agent_a, agent_b, interaction_type, severity, action_required, evidence, is_active)
            VALUES (:code, :a, :b, :type, :sev, :action, :ev, :active)
            RETURNING *
        """), {"code": rule_code, "a": req.agent_a, "b": req.agent_b, "type": req.interaction_type,
               "sev": req.severity, "action": req.action_required, "ev": req.evidence, "active": req.is_active}).fetchone()
    return dict(row._mapping)

@app.patch("/api/admin/drug-lab-rules/{rule_id}")
def admin_update_drug_lab_rule(rule_id: int, req: DrugLabRuleRequest):
    from sqlalchemy import text as _text
    from .cloud_sql_db import get_engine as _get_engine
    with _get_engine().begin() as conn:
        row = conn.execute(_text("""
            UPDATE drug_lab_rules
            SET agent_a = :a, agent_b = :b, interaction_type = :type, severity = :sev,
                action_required = :action, evidence = :ev, is_active = :active, updated_at = NOW()
            WHERE id = :id
            RETURNING *
        """), {"id": rule_id, "a": req.agent_a, "b": req.agent_b, "type": req.interaction_type,
               "sev": req.severity, "action": req.action_required, "ev": req.evidence, "active": req.is_active}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    return dict(row._mapping)

@app.delete("/api/admin/drug-lab-rules/{rule_id}")
def admin_delete_drug_lab_rule(rule_id: int):
    from sqlalchemy import text as _text
    from .cloud_sql_db import get_engine as _get_engine
    with _get_engine().begin() as conn:
        result = conn.execute(_text("DELETE FROM drug_lab_rules WHERE id = :id"), {"id": rule_id})
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"status": "deleted", "id": rule_id}


# ── Encounters (extended) ─────────────────────────────────────────────────────
class UpdateEncounterRequest(BaseModel):
    status:          Optional[str] = None
    assigned_to:     Optional[str] = None
    version:         Optional[int] = None
    revision_reason: Optional[str] = None
    revision_at:     Optional[str] = None

@app.patch("/api/encounters/{encounter_id}")
def update_encounter(encounter_id: str, req: UpdateEncounterRequest):
    from sqlalchemy import text as _text
    from .cloud_sql_db import get_engine as _get_engine
    # Use __fields_set__ so explicitly-sent null values (e.g. assigned_to: null) are written,
    # while fields omitted from the request body are not overwritten.
    fields = {k: req.dict()[k] for k in req.__fields_set__}
    enc = gdb.update_encounter(encounter_id, fields)
    if not enc:
        raise HTTPException(404, "Encounter not found")

    # Auto-trigger CE4 billing reconciliation when doctor signs off
    if req.status == "Signed Off":
        try:
            with _get_engine().begin() as conn:
                enc_row = conn.execute(
                    _text("SELECT hadm_id FROM app_encounters WHERE id = :id"),
                    {"id": encounter_id}
                ).fetchone()
                if enc_row and enc_row[0]:
                    h = enc_row[0]
                    br = conn.execute(
                        _text("SELECT id, billing_phase FROM billing_records WHERE hadm_id = :h"),
                        {"h": h}
                    ).fetchone()
                    if br:
                        if br[1] not in ("paid", "reconciliation_pending"):
                            conn.execute(
                                _text("UPDATE billing_records SET billing_phase = 'reconciliation_pending', updated_at = NOW() WHERE hadm_id = :h"),
                                {"h": h}
                            )
                    else:
                        conn.execute(
                            _text("INSERT INTO billing_records (hadm_id, billing_phase) VALUES (:h, 'reconciliation_pending')"),
                            {"h": h}
                        )
        except Exception as _be:
            log.warning(f"Billing trigger on sign-off failed for encounter {encounter_id}: {_be}")

    return enc

@app.get("/api/encounters/{hadm_id}/encounter")
async def get_encounter_by_hadm_id(hadm_id: int, background_tasks: BackgroundTasks):
    enc = await run_in_threadpool(gdb.get_encounter_by_hadm, hadm_id)
    if not enc:
        raise HTTPException(404, "Encounter not found")
    await run_in_threadpool(gdb.update_encounter, enc["id"], {"last_accessed_at": datetime.now().isoformat()})

    # Pre-warm the data_server tab cache in the background so generate_summary is fast.
    # Tabs already cached return in ms; uncached ones (e.g. procedureevents) hit BigQuery
    # once here rather than blocking the summary pipeline later.
    async def _prewarm():
        _tabs = ["prescriptions", "pharmacy", "labevents", "poe", "emar",
                 "fluids", "chartevents", "datetimeevents", "procedureevents", "emar_detail"]
        _t = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)
        async with httpx.AsyncClient(base_url="http://127.0.0.1:7016") as client:
            await asyncio.gather(*[
                client.get(f"/api/patient/{hadm_id}/tab/{t}", timeout=_t)
                for t in _tabs
            ], return_exceptions=True)
        log.debug(f"[prewarm] tabs cached for hadm_id={hadm_id}")

    background_tasks.add_task(_prewarm)
    return enc


# ── Summaries ─────────────────────────────────────────────────────────────────
class UpdateSummaryRequest(BaseModel):
    content:                  Optional[str]  = None
    signed_by:                Optional[str]  = None
    signed_at:                Optional[str]  = None
    claim_verification_status:Optional[str]  = None
    nli_score:                Optional[float]= None
    signature_mode:           Optional[str]  = None
    signature_data:           Optional[str]  = None
    draft_saved_at:           Optional[str]  = None
    draft_edits:              Optional[Dict[str, Any]] = None
    llm_edits_count:          Optional[int]  = None
    gap_t1:                   Optional[int]  = None
    gap_t2:                   Optional[int]  = None
    gap_t3:                   Optional[int]  = None
    gap_rows:                 Optional[List[Dict[str, Any]]] = None
    # Version control fields (not stored in app_summaries, consumed by endpoint logic)
    save_version:             Optional[bool] = False
    save_type:                Optional[str]  = "draft"   # "draft" | "signed"
    saved_by_name:            Optional[str]  = None

@app.get("/api/encounters/{encounter_id}/summary")
def get_summary(encounter_id: str):
    s = gdb.get_summary_by_encounter(encounter_id)
    return s if s else {"encounter_id": encounter_id, "content": None}

_VERSION_ONLY_FIELDS = {"save_version", "save_type"}

@app.patch("/api/summaries/{encounter_id}")
def update_summary(encounter_id: str, req: UpdateSummaryRequest):
    fields = {k: v for k, v in req.dict().items()
              if v is not None and k not in _VERSION_ONLY_FIELDS}
    # Auto-compute llm_edits_count from draft_edits if not explicitly provided
    if req.draft_edits is not None and req.llm_edits_count is None:
        fields["llm_edits_count"] = len(req.draft_edits)
    # Increment doc_version counter when creating a versioned snapshot
    if req.save_version and req.content:
        existing = gdb.get_summary_by_encounter(encounter_id)
        fields["doc_version"] = (existing.get("doc_version") or 0) + 1 if existing else 1
    s = gdb.update_summary(encounter_id, fields)
    if not s:
        raise HTTPException(404, "Summary not found")
    # Create immutable snapshot AFTER successful save
    if req.save_version and req.content:
        try:
            gdb.create_summary_version(
                summary_id    = s["id"],
                encounter_id  = encounter_id,
                hadm_id       = s.get("hadm_id") or 0,
                content       = req.content,
                sections_json = s.get("sections_json"),
                saved_by      = req.signed_by or None,
                saved_by_name = req.saved_by_name or None,
                save_type     = req.save_type or "draft",
            )
        except Exception as _ve:
            log.warning(f"Version snapshot failed (non-fatal): {_ve}")
    return s

@app.get("/api/summaries/{encounter_id}/versions")
def list_versions(encounter_id: str):
    return gdb.list_summary_versions(encounter_id)

@app.get("/api/summaries/versions/{version_id}")
def get_version(version_id: str):
    v = gdb.get_summary_version(version_id)
    if not v:
        raise HTTPException(404, "Version not found")
    return v


# ── Drug-Lab Interaction Check (Module D) ─────────────────────────────────────

_DL_DRUG_CLASS_MAP = {
    "ace_inhibitors":    ["lisinopril","enalapril","ramipril","perindopril","captopril","trandolapril","quinapril","fosinopril"],
    "arbs":              ["losartan","telmisartan","valsartan","olmesartan","irbesartan","candesartan"],
    "k_sparing_diuretics": ["spironolactone","amiloride","eplerenone","finerenone"],
    "metformin":         ["metformin","glucophage","glycomet","obimet"],
    "nsaids":            ["ibuprofen","naproxen","diclofenac","indomethacin","ketorolac","aspirin","mefenamic","aceclofenac","etoricoxib","celecoxib"],
    "anticoagulants":    ["warfarin","apixaban","rivaroxaban","dabigatran","enoxaparin","heparin","acenocoumarol","acitrom"],
    "beta_blockers":     ["metoprolol","carvedilol","atenolol","bisoprolol","propranolol","nebivolol","labetalol"],
    "loop_diuretics":    ["furosemide","frusemide","torsemide","torasemide","bumetanide","lasix"],
    "digoxin":           ["digoxin","lanoxin","digitoxin"],
    "amiodarone":        ["amiodarone","cordarone","tachyra"],
    "statins":           ["atorvastatin","rosuvastatin","simvastatin","pravastatin","lovastatin","fluvastatin","pitavastatin"],
}

_DL_RULES = [
    {"name":"Hyperkalemia risk with ACE inhibitors","trigger":{"lab":"potassium","condition":"> 5.5"},"medications":["ace_inhibitors","k_sparing_diuretics"],"severity":"CRITICAL","message":"K⁺ {lab_value} mmol/L with ACE inhibitor/K-sparing diuretic — hyperkalemia risk.","action":"Hold ACE inhibitor and K-sparing diuretic. Repeat K⁺ in 2h. Notify physician. Consider calcium gluconate if K⁺ > 6.0.","guideline":"Cardiological Society of India (CSI) HF Guidelines 2022"},
    {"name":"Lactic acidosis risk — eGFR low with metformin","trigger":{"lab":"egfr","condition":"< 30"},"medications":["metformin"],"severity":"CRITICAL","message":"eGFR {lab_value} mL/min with metformin active — lactic acidosis risk.","action":"Stop metformin immediately. Monitor bicarbonate and lactate. Notify physician.","guideline":"CDSCO Drug Safety Guidelines / RSSDI 2023"},
    {"name":"AKI risk — rising creatinine with NSAID","trigger":{"lab":"creatinine","condition":"> 1.5"},"medications":["nsaids","ace_inhibitors"],"severity":"WARNING","message":"Creatinine {lab_value} mg/dL with nephrotoxic medication — AKI risk.","action":"Review nephrotoxic medications. Increase monitoring frequency. Consider renal ultrasound.","guideline":"KDIGO AKI Guidelines 2012 / Indian Nephrology Society"},
    {"name":"Bleeding risk — elevated INR with anticoagulant","trigger":{"lab":"inr","condition":"> 3.5"},"medications":["anticoagulants"],"severity":"CRITICAL","message":"INR {lab_value} with anticoagulant active — major bleeding risk.","action":"Hold anticoagulant. Consider vitamin K (1–5 mg oral). Monitor for bleeding signs. Notify physician urgently.","guideline":"CSI Anticoagulation Guidelines / ACCP 2012"},
    {"name":"Lactate elevation — sepsis concern","trigger":{"lab":"lactate","condition":"> 2.0"},"medications":[],"severity":"WARNING","message":"Lactate {lab_value} mmol/L elevated — assess for sepsis.","action":"Assess qSOFA/SOFA criteria. Consider blood cultures and broad-spectrum antibiotics.","guideline":"Surviving Sepsis Campaign 2021 / ISCCM India"},
    {"name":"Digoxin toxicity — hypokalemia","trigger":{"lab":"potassium","condition":"< 3.5"},"medications":["digoxin"],"severity":"CRITICAL","message":"K⁺ {lab_value} mmol/L with active digoxin — hypokalemia greatly increases digoxin toxicity risk.","action":"Hold digoxin. Check digoxin serum level (target 0.8–1.2 ng/mL). Replace potassium (IV/oral). 12-lead ECG urgently. Notify cardiologist.","guideline":"CSI Guidelines / FDA Drug Safety / Cardiological Society of India 2022"},
    {"name":"Amiodarone potentiates warfarin — INR elevation","trigger":{"lab":"inr","condition":"> 2.5"},"medications":["anticoagulants","amiodarone"],"severity":"WARNING","message":"INR {lab_value} with amiodarone + anticoagulant active — amiodarone inhibits warfarin metabolism (CYP2C9).","action":"Reduce warfarin dose by 30–50%. Monitor INR weekly for 6 weeks (peak effect at 7 weeks). Check for bleeding signs.","guideline":"CSI Atrial Fibrillation Guidelines 2021 / British National Formulary"},
    {"name":"Loop diuretic — hypokalemia arrhythmia risk","trigger":{"lab":"potassium","condition":"< 3.5"},"medications":["loop_diuretics"],"severity":"WARNING","message":"K⁺ {lab_value} mmol/L with loop diuretic (furosemide/torsemide) — diuretic-induced hypokalemia, cardiac arrhythmia risk.","action":"Potassium replacement (oral KCl 20–40 mEq or IV if < 3.0). Review diuretic dose. 12-lead ECG. Notify physician.","guideline":"CSI Heart Failure Guidelines 2022 / Indian Heart Journal"},
    {"name":"Beta-blocker symptomatic bradycardia","trigger":{"lab":"heart_rate","condition":"< 50"},"medications":["beta_blockers"],"severity":"WARNING","message":"HR {lab_value} bpm with beta-blocker active — symptomatic bradycardia risk.","action":"Withhold next beta-blocker dose. 12-lead ECG. If symptomatic (hypotension, dizziness), notify cardiologist. Consider atropine if haemodynamically unstable.","guideline":"ESC 2021 HF Guidelines / CSI Bradycardia Protocol"},
    {"name":"Statin hepatotoxicity — elevated transaminases","trigger":{"lab":"alt","condition":"> 120"},"medications":["statins"],"severity":"WARNING","message":"ALT {lab_value} U/L (>3× ULN) with statin active — statin-induced hepatotoxicity risk.","action":"Withhold statin. Repeat LFT in 1 week. If ALT > 200 U/L, consult gastroenterology. Do NOT restart until ALT < 3× ULN.","guideline":"RSSDI Lipid Guidelines 2023 / ICMR Statin Safety Guidelines"},
    {"name":"Hyperkalemia early warning — HF patient on ACE + spironolactone","trigger":{"lab":"potassium","condition":"> 5.0"},"medications":["ace_inhibitors","k_sparing_diuretics"],"severity":"WARNING","message":"K⁺ {lab_value} mmol/L (> 5.0) with ACE inhibitor + aldosterone antagonist — early hyperkalemia in heart failure.","action":"Reduce spironolactone dose. Low-potassium diet counselling. Repeat K⁺ in 24h. If K⁺ > 5.5 mmol/L, hold spironolactone.","guideline":"CSI HF Guidelines 2022 / ESC HF 2021 (Section 7.3)"},
    {"name":"Amiodarone + Digoxin — serum digoxin toxicity","trigger":{"lab":"creatinine","condition":"> 1.2"},"medications":["digoxin","amiodarone"],"severity":"CRITICAL","message":"Creatinine {lab_value} mg/dL with amiodarone + digoxin — amiodarone increases digoxin levels by 70–100% via P-gp inhibition.","action":"Reduce digoxin dose by 50%. Check serum digoxin level urgently (therapeutic range 0.8–1.2 ng/mL). Monitor for toxicity: nausea, bradycardia, visual disturbance. Notify cardiologist.","guideline":"CSI AF Guidelines 2021 / FDA Drug Safety Communication"},
    {"name":"Contrast nephropathy risk — creatinine with metformin","trigger":{"lab":"creatinine","condition":"> 1.3"},"medications":["metformin"],"severity":"WARNING","message":"Creatinine {lab_value} mg/dL with metformin — risk of contrast-induced nephropathy if contrast agent used.","action":"Hold metformin 48h before and after contrast administration. Ensure adequate IV hydration. Recheck creatinine before restarting.","guideline":"CDSCO Advisory / RCR Contrast Guidelines 2023"},
]

# MIMIC lab label → rule engine key
_DL_LAB_MAP = {
    "potassium": "potassium",
    "creatinine": "creatinine",
    "inr(pt)": "inr",
    "inr": "inr",
    "pt - inr": "inr",
    "lactate": "lactate",
    "lactic acid": "lactate",
    "alt (sgpt)": "alt",
    "alanine aminotransferase (alt)": "alt",
    "sgpt": "alt",
    "glomerular filtration rate (mdrd)": "egfr",
    "estimated gfr (mdrd)": "egfr",
    "egfr": "egfr",
}

def _dl_eval_condition(condition: str, value: float) -> bool:
    c = condition.strip()
    if c.startswith(">="): return value >= float(c[2:])
    if c.startswith("<="): return value <= float(c[2:])
    if c.startswith(">"): return value > float(c[1:])
    if c.startswith("<"): return value < float(c[1:])
    if c.startswith("="): return value == float(c[1:])
    return False

def _dl_med_matches(med: str, classes: list) -> bool:
    ml = med.lower()
    for cls in classes:
        for cm in _DL_DRUG_CLASS_MAP.get(cls, []):
            if cm in ml:
                return True
    return False

def _run_dl_rules(med_names: list, patient_labs: dict) -> list:
    alerts = []
    for rule in _DL_RULES:
        lab_key = rule["trigger"]["lab"]
        lab_val = patient_labs.get(lab_key)
        if lab_val is None:
            continue
        if not _dl_eval_condition(rule["trigger"]["condition"], lab_val):
            continue
        med_classes = rule.get("medications", [])
        if not med_classes:
            alerts.append({**rule, "lab_value": round(lab_val, 2), "triggering_meds": [], "message": rule["message"].format(lab_value=round(lab_val, 2), lab_name=lab_key)})
            continue
        matching = [m for m in med_names if _dl_med_matches(m, med_classes)]
        if matching:
            alerts.append({**rule, "lab_value": round(lab_val, 2), "triggering_meds": matching, "message": rule["message"].format(lab_value=round(lab_val, 2), lab_name=lab_key)})
    return alerts

@app.get("/api/encounters/{hadm_id}/dl_check")
async def dl_check(hadm_id: int):
    # 1. Prescriptions → med names
    med_names: list = []
    try:
        async with httpx.AsyncClient(timeout=30) as _c:
            _r = await _c.get(f"{DATA_SERVER}/api/patient/{hadm_id}/tab/prescriptions")
            _rx = _r.json()
        med_names = list({(r.get("drug") or "").strip() for r in _rx.get("prescriptions", []) if r.get("drug")})
    except Exception as _e:
        log.warning(f"dl_check: prescriptions fetch failed: {_e}")

    # 2. Labevents → most-recent numeric value per mapped key
    patient_labs: dict = {}
    try:
        async with httpx.AsyncClient(timeout=30) as _c:
            _r = await _c.get(f"{DATA_SERVER}/api/patient/{hadm_id}/tab/labevents")
            _lab = _r.json()
        for row in sorted(_lab.get("labevents", []), key=lambda x: x.get("charttime") or "", reverse=True):
            lbl = (row.get("label") or "").strip().lower()
            mapped = _DL_LAB_MAP.get(lbl)
            if mapped and mapped not in patient_labs:
                v = row.get("valuenum")
                if v is not None:
                    try:
                        patient_labs[mapped] = float(v)
                    except (ValueError, TypeError):
                        pass
    except Exception as _e:
        log.warning(f"dl_check: labevents fetch failed: {_e}")

    # 3. Chartevents → heart rate (only if needed and not already set)
    if "heart_rate" not in patient_labs:
        try:
            async with httpx.AsyncClient(timeout=20) as _c:
                _r = await _c.get(f"{DATA_SERVER}/api/patient/{hadm_id}/tab/chartevents")
                _ch = _r.json()
            for row in sorted(_ch.get("chartevents", []), key=lambda x: x.get("charttime") or "", reverse=True):
                lbl = (row.get("label") or "").strip().lower()
                if "heart rate" in lbl:
                    v = row.get("valuenum")
                    if v is not None:
                        try:
                            patient_labs["heart_rate"] = float(v)
                        except (ValueError, TypeError):
                            pass
                    break
        except Exception as _e:
            log.warning(f"dl_check: chartevents fetch failed: {_e}")

    # 4. Run rules
    alerts = _run_dl_rules(med_names, patient_labs)
    dl_count = len(alerts)

    # 5. Persist dl_flags on the summary for this encounter
    try:
        from sqlalchemy import text as _sqlt
        from .cloud_sql_app_db import get_engine as _geng
        with _geng().begin() as _conn:
            _enc_row = _conn.execute(
                _sqlt("SELECT id FROM app_encounters WHERE hadm_id = :h ORDER BY created_at DESC LIMIT 1"),
                {"h": hadm_id}
            ).fetchone()
            if _enc_row:
                _conn.execute(
                    _sqlt("UPDATE app_summaries SET dl_flags = :dl, updated_at = NOW() WHERE encounter_id = :enc"),
                    {"dl": dl_count, "enc": str(_enc_row[0])}
                )
    except Exception as _e:
        log.warning(f"dl_check: could not persist dl_flags: {_e}")

    return {
        "hadm_id": hadm_id,
        "count": dl_count,
        "critical_count": sum(1 for a in alerts if a["severity"] == "CRITICAL"),
        "warning_count": sum(1 for a in alerts if a["severity"] == "WARNING"),
        "alerts": alerts,
        "checked_labs": patient_labs,
        "med_count": len(med_names),
    }


# ── Settings ──────────────────────────────────────────────────────────────────
@app.get("/api/settings")
def get_settings():
    return gdb.get_settings()

@app.patch("/api/settings")
def update_settings(fields: Dict[str, Any]):
    return gdb.update_settings(fields)


# ── Audit Log ─────────────────────────────────────────────────────────────────
@app.get("/api/audit_log")
def get_audit_log(limit: int = 100):
    return gdb.list_audit_log(limit=limit)


# ── Medication localization (US MIMIC names → Indian brand names via Gemini) ──

# In-process cache so the same drug list isn't re-queried per request
_MED_LOCALIZE_CACHE: dict[str, str] = {}

# Hardcoded fallback map (mirrors frontend _DRUG_MAP for offline / Gemini-down)
_MED_FALLBACK: dict[str, str] = {
    "aspirin":"Ecosprin","acetylsalicylic acid":"Ecosprin",
    "clopidogrel":"Clopivas","ticagrelor":"Brilinta","prasugrel":"Practi",
    "heparin":"Heparin","enoxaparin":"Clexane","fondaparinux":"Arixtra",
    "warfarin":"Warf","rivaroxaban":"Xarelto","apixaban":"Eliquis","dabigatran":"Pradaxa",
    "metoprolol":"Metolar XR","metoprolol succinate":"Metolar XR","metoprolol tartrate":"Metolar",
    "bisoprolol":"Concor","carvedilol":"Cardivas","atenolol":"Tenormin",
    "propranolol":"Inderal","nebivolol":"Nebicard",
    "ramipril":"Cardace","lisinopril":"Listril","enalapril":"Envas",
    "perindopril":"Coversyl","captopril":"Capoten","fosinopril":"Fovas",
    "losartan":"Cosart","valsartan":"Valzaar","candesartan":"Candesar","olmesartan":"Olsar",
    "irbesartan":"Irbetan","telmisartan":"Telma","azilsartan":"Azilide",
    "sacubitril/valsartan":"Vymada","sacubitril-valsartan":"Vymada","entresto":"Vymada",
    "amlodipine":"Stamlo","diltiazem":"Dilzem","verapamil":"Calaptin","nifedipine":"Nicardia",
    "atorvastatin":"Atorva","rosuvastatin":"Rozavel","simvastatin":"Simvotin",
    "pravastatin":"Pravator","pitavastatin":"Livalo","lovastatin":"Lova",
    "spironolactone":"Aldactone","eplerenone":"Inspra",
    "furosemide":"Lasix","frusemide":"Lasix","torsemide":"Dytor","torasemide":"Dytor",
    "hydrochlorothiazide":"Hydrochlorothiazide","indapamide":"Natrilix SR",
    "nitroglycerin":"Nitrocontin","glyceryl trinitrate":"Nitrocontin",
    "isosorbide dinitrate":"Sorbitrate","isosorbide mononitrate":"Monotrate",
    "nicorandil":"Nikoran","trimetazidine":"Vastarel MR","ivabradine":"Coralan",
    "empagliflozin":"Jardiance","dapagliflozin":"Forxiga","canagliflozin":"Invokana",
    "amiodarone":"Cordarone","digoxin":"Lanoxin","lidocaine":"Xylocard",
    "hydralazine":"Nepresol","clonidine":"Catapres","prazosin":"Minipress",
    "metformin":"Glycomet","insulin glargine":"Basalog","insulin aspart":"Novorapid",
    "sitagliptin":"Januvia","vildagliptin":"Galvus","saxagliptin":"Onglyza",
    "pantoprazole":"Pan","omeprazole":"Omez","rabeprazole":"Razo","lansoprazole":"Lanzol",
    "potassium chloride":"Potklor",
    "paracetamol":"Calpol","acetaminophen":"Calpol","tramadol":"Ultracet",
    "cefazolin":"Reflin","cephalexin":"Sporidex",
    "amoxicillin-clavulanate":"Augmentin","amoxicillin/clavulanate":"Augmentin",
}

class MedLocalizeRequest(BaseModel):
    drugs: List[str]

@app.post("/api/localize/medications")
async def localize_medications(req: MedLocalizeRequest):
    """Convert US MIMIC drug names to Indian brand names using Gemini, with static fallback."""
    if not req.drugs:
        return {"mapping": {}}

    result: dict[str, str] = {}
    to_llm: list[str] = []

    for raw in req.drugs:
        if not raw or raw == "—":
            continue
        key = raw.strip().lower()
        if key in _MED_LOCALIZE_CACHE:
            result[raw] = _MED_LOCALIZE_CACHE[key]
        elif key in _MED_FALLBACK:
            result[raw] = _MED_FALLBACK[key]
            _MED_LOCALIZE_CACHE[key] = _MED_FALLBACK[key]
        else:
            # Also try first word match
            first = key.split()[0] if key.split() else key
            if first in _MED_FALLBACK:
                result[raw] = _MED_FALLBACK[first]
                _MED_LOCALIZE_CACHE[key] = _MED_FALLBACK[first]
            else:
                to_llm.append(raw)

    if to_llm and gemini_client:
        try:
            drug_list_str = "\n".join(f"- {d}" for d in to_llm[:60])  # cap at 60 per call
            prompt = f"""You are a clinical pharmacist in India. Convert these US drug names (from MIMIC hospital data) to their most commonly used Indian brand names.

Return ONLY a valid JSON object — no markdown, no explanation — mapping each input drug name exactly as given to its Indian brand name.

Rules:
- Use the most widely stocked Indian brand (e.g. "Atorvastatin" → "Atorva", "Furosemide" → "Lasix", "Metoprolol Succinate" → "Metolar XR")
- If the drug is already used under the same name in India, return it unchanged
- If no clear Indian brand exists, return the generic name unchanged
- Do not add dosage strengths

Drugs:
{drug_list_str}

Respond with JSON only:
{{"OriginalName": "IndianBrandName", ...}}"""

            response = await asyncio.to_thread(
                gemini_client.models.generate_content,
                model=GEMINI_MODEL,
                contents=prompt,
            )
            raw_text = (response.text or "").strip()
            # Strip markdown code fences if Gemini adds them
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            import json as _json
            mapping = _json.loads(raw_text)
            for orig, brand in mapping.items():
                result[orig] = brand
                _MED_LOCALIZE_CACHE[orig.strip().lower()] = brand
        except Exception as e:
            log.warning(f"[localize_medications] Gemini failed: {e} — using raw names")
            for d in to_llm:
                result[d] = d  # pass through unchanged

    # Anything still missing → pass through unchanged
    for raw in req.drugs:
        if raw and raw not in result:
            result[raw] = raw

    return {"mapping": result}


# ── Uploaded files list ───────────────────────────────────────────────────────
@app.get("/api/encounters/{encounter_id}/files")
def list_files(encounter_id: str):
    return {"files": gdb.list_files_by_encounter(encounter_id)}



# ── Data server proxy (port 7015 → internal 7016) ────────────────────────────
# Lets the browser talk to the data server through the main API port when 7016
# is blocked by a firewall. Used on server deployments; localhost uses 7016 direct.
_DATA_SERVER = os.environ.get("DATA_SERVER_URL", "http://127.0.0.1:7016")

@app.api_route("/data-proxy/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def data_proxy(path: str, request: Request):
    url = f"{_DATA_SERVER}/{path}"
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            resp = await client.request(
                method=request.method,
                url=url,
                params=dict(request.query_params),
                content=await request.body(),
                headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
            )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/json"),
            headers={"Access-Control-Allow-Origin": "*"},
        )
    except httpx.ReadTimeout:
        return JSONResponse(
            {"detail": "Data server timeout — dataset still loading, retry in a moment"},
            status_code=504,
            headers={"Access-Control-Allow-Origin": "*"},
        )
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return JSONResponse(
            {"detail": "Data server unreachable on port 7016"},
            status_code=503,
            headers={"Access-Control-Allow-Origin": "*"},
        )
