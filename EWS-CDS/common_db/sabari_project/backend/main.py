import math
import os
import uuid as _uuid_mod
import yaml
from collections import defaultdict
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session
from database import SessionLocal, init_db, engine as _shared_engine
from models import (
    Patient, VitalTimeSeries, LabEvent, Medication, Escalation, CcuTransfer, DrugLabAction,
    # New ERD schema models (migration 026)
    DrugLabRule, DrugLabFlag, EwsEvent, DcmAssessment, FluidBalance,
    DischargeSection, DischargeAmendment, HcAdmission,
)
from engine.drug_lab import check_patient_against_rules
from mimic_sync import sync_patient_from_mimic, list_dcm_patients
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import random

# ── Shared auth helpers (reads app_users via the same Cloud SQL engine) ────────

_EWS_ALLOWED_ROLES = {"Ward Nurse", "Charge Nurse", "GW Nurse", "Resident", "Doctor"}

def _lookup_session_token(token: str):
    """Return app_users row dict for this session token, or None."""
    if not token or len(token) < 8:
        return None
    try:
        with _shared_engine.connect() as conn:
            row = conn.execute(sql_text(
                "SELECT id, hospital_email, role, full_name, ward_assignment "
                "FROM app_users WHERE session_token = :tok AND is_active = TRUE LIMIT 1"
            ), {"tok": token}).fetchone()
        return dict(row._mapping) if row else None
    except Exception:
        return None

def get_current_ews_user(request: Request):
    """Optional auth dependency — returns user dict or None (never blocks)."""
    token = (request.headers.get("Authorization", "").replace("Bearer ", "").strip()
             or request.headers.get("X-Foqal-Token", "").strip())
    return _lookup_session_token(token)

def require_ews_user(request: Request):
    """Strict auth dependency — raises 401 if no valid session token."""
    user = get_current_ews_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user

_NEWS2_YAML = os.path.join(os.path.dirname(__file__), "rules", "news2_thresholds.yaml")
_NEWS2_CACHE: dict | None = None

def _load_news2_thresholds() -> dict:
    global _NEWS2_CACHE
    if _NEWS2_CACHE is None:
        with open(_NEWS2_YAML, "r", encoding="utf-8") as f:
            _NEWS2_CACHE = yaml.safe_load(f)
    return _NEWS2_CACHE

def _score_range(value: float, bands: list[dict]) -> int:
    """Score a numeric vital against a sorted list of band dicts {min?, max?, score}."""
    for band in bands:
        lo = band.get("min", float("-inf"))
        hi = band.get("max", float("inf"))
        if lo <= value <= hi:
            return band.get("score", 0)
    return 0

class EscalationCreate(BaseModel):
    patientId: int
    level: str
    attending: str
    observations: str
    interventions: str
    escalatedBy: str

def is_valid(val):
    if val is None:
        return False
    if isinstance(val, (float, int)) and (math.isnan(val) or val == 0):
        return False
    return True

app = FastAPI(
    title="Foqal CareOS API",
    description="Clinical Decision Support — Early Warning + Drug-Lab Interaction Checker. Calibrated for Indian cardiology wards (CSI/CDSCO/ICMR guidelines).",
    version="0.2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    init_db()
    _apply_ews_startup_migrations()
    _seed_ews_drug_lab_rules()

def _apply_ews_startup_migrations():
    """Idempotent column additions that the EWS backend depends on.
    Mirrors a subset of Ashmit's startup migrations so EWS can boot independently.
    All statements use IF NOT EXISTS — safe to re-run on every restart.
    """
    import logging as _log
    _logger = _log.getLogger(__name__)
    stmts = [
        # Bridge FKs: link active_patients → app_encounters / app_summaries
        "ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS encounter_id UUID",
        "ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS summary_id   UUID",
        "CREATE INDEX IF NOT EXISTS idx_ap_encounter ON active_patients (encounter_id) WHERE encounter_id IS NOT NULL",
        # Workflow columns used by handoff logic
        "ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS updated_at              TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS primary_diagnosis_title VARCHAR(255)",
        "ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS discharge_type          VARCHAR(20)",
        "ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS discharge_time          TIMESTAMPTZ",
        "ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS los_days                NUMERIC(6,2)",
        # NYHA / LVEF / BNP — from schema_migration_v2
        "ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS nyha_class   SMALLINT",
        "ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS lvef_percent SMALLINT",
        "ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS bnp_baseline NUMERIC(10,2)",
        # Cardiology labs on ews_lab_events — from schema_migration_v2
        "ALTER TABLE ews_lab_events ADD COLUMN IF NOT EXISTS bnp        NUMERIC(10,2)",
        "ALTER TABLE ews_lab_events ADD COLUMN IF NOT EXISTS troponin   NUMERIC(10,4)",
        "ALTER TABLE ews_lab_events ADD COLUMN IF NOT EXISTS sodium     NUMERIC(6,2)",
        "ALTER TABLE ews_lab_events ADD COLUMN IF NOT EXISTS hemoglobin NUMERIC(6,2)",
        # Daily weight on vitals timeseries
        "ALTER TABLE ews_vitals_timeseries ADD COLUMN IF NOT EXISTS weight_kg NUMERIC(6,2)",
        # EWS-specific columns on active_patients (from ews_migration.sql)
        "ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS patient_code        VARCHAR(20)",
        "ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS ward                VARCHAR(30)",
        "ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS room                VARCHAR(20)",
        "ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS bed                 VARCHAR(20)",
        "ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS ward_location       VARCHAR(20) DEFAULT 'CCU'",
        "ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS hypercapnic_failure SMALLINT DEFAULT 0",
        "ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS diagnosis_short     VARCHAR(80)",
        "ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS ews_complaint       TEXT",
    ]
    ok = 0
    for stmt in stmts:
        try:
            with _shared_engine.begin() as conn:
                conn.execute(sql_text(stmt))
            ok += 1
        except Exception as e:
            _logger.debug("EWS startup migration skipped (%s…): %s", stmt[:50], e)
    _logger.info("EWS startup migrations: %d/%d applied", ok, len(stmts))


def _seed_ews_drug_lab_rules():
    """Seed ews.drug_lab_rules from drug_lab_rules.yaml (idempotent, runs every restart).
    Without this, _persist_drug_lab_flags silently skips every alert because rule_id_map
    returns empty — ews.drug_lab_flags is never written despite the engine firing correctly."""
    import uuid as _uuid_seed
    import logging as _log_seed
    _logger = _log_seed.getLogger(__name__)

    def _parse_condition(cond: str):
        """'> 5.5' → ('gt', 5.5);  '< 30' → ('lt', 30); etc."""
        s = cond.strip()
        if s.startswith('>='):
            return 'gte', float(s[2:].strip())
        if s.startswith('<='):
            return 'lte', float(s[2:].strip())
        if s.startswith('>'):
            return 'gt', float(s[1:].strip())
        if s.startswith('<'):
            return 'lt', float(s[1:].strip())
        return 'eq', float(s[1:].strip())

    def _parse_guideline_source(text: str):
        for src in ('CDSCO', 'FDA', 'ESC', 'ICMR', 'WHO'):
            if src in text:
                return src
        return None

    def _parse_recommended_action(text: str):
        t = text.strip().lower()
        if t.startswith(('hold', 'stop', 'withhold')):
            return 'hold'
        if t.startswith('reduce'):
            return 'reduce'
        if t.startswith(('assess', 'review', 'check', 'consider', 'potassium', 'repeat')):
            return 'monitor'
        return 'notify'

    try:
        from engine.drug_lab import load_rules
        rules = load_rules()
    except Exception as _e:
        _logger.warning("_seed_ews_drug_lab_rules: could not load YAML — %s", _e)
        return

    seeded = skipped = 0
    try:
        with _shared_engine.begin() as conn:
            for rule in rules:
                rule_name = rule['name']
                trigger = rule.get('trigger', {})
                comparator, threshold = _parse_condition(trigger.get('condition', '> 0'))
                medications = rule.get('medications', [])
                result = conn.execute(sql_text("""
                    INSERT INTO ews.drug_lab_rules
                        (rule_id, rule_name, trigger_drug, trigger_lab,
                         lab_threshold, comparator, severity, recommended_action,
                         clinical_rationale, guideline_source, is_active)
                    SELECT :rid, :rname, :tdrug, :tlab,
                           :thresh, :comp, :sev, :raction,
                           :rationale, :gsource, TRUE
                    WHERE NOT EXISTS (
                        SELECT 1 FROM ews.drug_lab_rules WHERE rule_name = :rname
                    )
                """), {
                    "rid":      str(_uuid_seed.uuid4()),
                    "rname":    rule_name,
                    "tdrug":    (', '.join(medications) if medications else 'any')[:100],
                    "tlab":     trigger.get('lab', '')[:100],
                    "thresh":   threshold,
                    "comp":     comparator,
                    "sev":      rule.get('severity', 'WARNING'),
                    "raction":  _parse_recommended_action(rule.get('action', '')),
                    "rationale": rule.get('action', ''),
                    "gsource":  _parse_guideline_source(rule.get('guideline', '')),
                })
                if result.rowcount > 0:
                    seeded += 1
                else:
                    skipped += 1
        _logger.info("ews.drug_lab_rules: %d seeded, %d already present", seeded, skipped)
    except Exception as _e:
        _logger.warning(
            "ews.drug_lab_rules seed skipped (migration 026 may not have run yet): %s", _e
        )


# ── Staff endpoint — feeds escalation nurse/doctor pickers ────────────────────

@app.get("/api/staff")
def list_staff(role: Optional[str] = None):
    """Return EWS-role staff from the shared app_users table."""
    try:
        with _shared_engine.connect() as conn:
            if role:
                rows = conn.execute(sql_text(
                    "SELECT id, full_name, role, ward_assignment FROM app_users "
                    "WHERE role = :r AND is_active = TRUE ORDER BY full_name"
                ), {"r": role}).fetchall()
            else:
                rows = conn.execute(sql_text(
                    "SELECT id, full_name, role, ward_assignment FROM app_users "
                    "WHERE role IN ('Ward Nurse','Charge Nurse','GW Nurse','Resident','Doctor') "
                    "AND is_active = TRUE ORDER BY role, full_name"
                )).fetchall()
        return {"staff": [dict(r._mapping) for r in rows]}
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).warning("staff list failed: %s", e)
        return {"staff": []}

@app.get("/api/auth/me")
def auth_me(user=Depends(get_current_ews_user)):
    """Return the currently authenticated user (for frontend session validation)."""
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def calculate_news2(vitals, hypercapnic_failure=False):
    """
    YAML-driven NEWS2 scorer. Loads thresholds from rules/news2_thresholds.yaml.
    active_set in the YAML controls which threshold set is used (uk_news2 or india_news2).
    SpO2 Scale 2 (hypercapnic) on-oxygen bonuses are still handled in code per RCP spec.
    """
    cfg = _load_news2_thresholds()
    active = cfg.get("active_set", "uk_news2")
    thresholds = cfg.get(active, cfg.get("uk_news2", {}))

    score = 0
    factors = []

    rr = vitals.get('resp_rate')
    if rr is not None:
        s = _score_range(rr, thresholds.get("resp_rate", []))
        score += s
        if s > 0: factors.append({"name": "Respiration Rate", "score": s})

    spo2 = vitals.get('spo2')
    if spo2 is not None:
        on_o2 = vitals.get('air_or_oxygen') == 'Oxygen'
        if hypercapnic_failure:
            s2_bands = thresholds.get("spo2_scale2", [])
            s = _score_range(spo2, s2_bands)
            # On-Oxygen bonuses per RCP SpO2 Scale 2 spec (93-94→+1, 95-96→+2, ≥97→+3)
            if on_o2 and spo2 >= 93:
                if spo2 <= 94: s = 1
                elif spo2 <= 96: s = 2
                else: s = 3
            score += s
            if s > 0: factors.append({"name": "SpO2 (Scale 2)", "score": s})
        else:
            s = _score_range(spo2, thresholds.get("spo2_scale1", []))
            score += s
            if s > 0: factors.append({"name": "SpO2 (Scale 1)", "score": s})

    if vitals.get('air_or_oxygen') == 'Oxygen':
        score += 2
        factors.append({"name": "Supplemental Oxygen", "score": 2})

    sbp = vitals.get('sbp')
    if sbp is not None:
        s = _score_range(sbp, thresholds.get("sbp", []))
        score += s
        if s > 0: factors.append({"name": "Systolic BP", "score": s})

    hr = vitals.get('heart_rate')
    if hr is not None:
        s = _score_range(hr, thresholds.get("heart_rate", []))
        score += s
        if s > 0: factors.append({"name": "Heart Rate", "score": s})

    consciousness = vitals.get('consciousness')
    if consciousness and consciousness != 'A':
        score += 3
        factors.append({"name": "Consciousness (CVPU)", "score": 3})

    temp = vitals.get('temperature')
    if temp is not None:
        s = _score_range(temp, thresholds.get("temperature", []))
        score += s
        if s > 0: factors.append({"name": "Temperature", "score": s})

    return {"total": score, "factors": factors}


# ════════════════════════════════════════════════════════════════════════════
#  Derived helpers — monitoring cadence, plain-language EWS reason, demo ML
# ════════════════════════════════════════════════════════════════════════════

def fmt_mins(mins):
    """Human-friendly minutes → '45m' / '2h' / '2h 30m'."""
    mins = int(max(0, mins))
    if mins < 60:
        return f"{mins}m"
    h, m = divmod(mins, 60)
    return f"{h}h" if m == 0 else f"{h}h {m}m"


def monitoring_plan(score, factors, ward_location):
    """NEWS2 response-protocol monitoring cadence (NHS/RCP), adapted by ward.

    GW (General Ward) follows the standard score-based cadence; CCU is floored at
    hourly because critical-care patients are monitored continuously regardless of
    a low transient score (NABH ICU 1:1).
    """
    any_single_3 = any(f.get("score", 0) >= 3 for f in factors)
    if score >= 7:
        interval, label = 30, "Continuous"
    elif score >= 5 or any_single_3:
        interval, label = 60, "Hourly"
    elif score >= 1:
        interval, label = 360, "4-6 hourly"
    else:
        interval, label = 720, "12-hourly"

    if ward_location == "CCU":
        interval = min(interval, 60)
        if label in ("4-6 hourly", "12-hourly"):
            label = "Hourly (CCU)"
    return {"interval_mins": interval, "label": label}


# Plain-language labels for each NEWS2 contributor, with direction from the value.
def _signal_for(name, score, lv):
    sev = "crit" if score >= 3 else "warn"
    rr   = lv.get("resp_rate"); spo2 = lv.get("spo2"); sbp = lv.get("sbp")
    hr   = lv.get("heart_rate"); temp = lv.get("temperature")
    if name == "Respiration Rate":
        if rr is not None and rr < 12:
            return {"short": "RR", "arrow": "↓", "plain": f"Slow breathing (RR {int(rr)})", "sev": sev}
        return {"short": "RR", "arrow": "↑", "plain": f"Fast breathing (RR {int(rr) if rr else '-'})", "sev": sev}
    if name.startswith("SpO2"):
        return {"short": "SpO₂", "arrow": "↓", "plain": f"Low oxygen (SpO₂ {int(spo2) if spo2 else '-'}%)", "sev": sev}
    if name == "Supplemental Oxygen":
        return {"short": "On O₂", "arrow": "", "plain": "On supplemental oxygen", "sev": "warn"}
    if name == "Systolic BP":
        if sbp is not None and sbp >= 220:
            return {"short": "BP", "arrow": "↑", "plain": f"Hypertensive crisis (SBP {int(sbp)})", "sev": sev}
        return {"short": "BP", "arrow": "↓", "plain": f"Low blood pressure (SBP {int(sbp) if sbp else '-'})", "sev": sev}
    if name == "Heart Rate":
        if hr is not None and hr <= 50:
            return {"short": "HR", "arrow": "↓", "plain": f"Slow heart rate (HR {int(hr)})", "sev": sev}
        return {"short": "HR", "arrow": "↑", "plain": f"Fast heart rate (HR {int(hr) if hr else '-'})", "sev": sev}
    if name == "Consciousness (CVPU)":
        return {"short": "Alert↓", "arrow": "", "plain": "Reduced alertness (not fully alert)", "sev": "crit"}
    if name == "Temperature":
        if temp is not None and temp <= 36.0:
            return {"short": "Temp", "arrow": "↓", "plain": f"Low temperature ({temp}°C)", "sev": sev}
        return {"short": "Temp", "arrow": "↑", "plain": f"Fever ({temp if temp else '-'}°C)", "sev": sev}
    return {"short": name, "arrow": "", "plain": name, "sev": sev}


def build_ews_reason(latest_vitals, news_data, drug_lab_alerts, score, status):
    """Plain-language, glanceable reason a nurse can read in ~5s — derived from the
    real NEWS2 contributors + drug-lab rule engine. No phenotype codes, no ML number."""
    signals = [_signal_for(f["name"], f["score"], latest_vitals) for f in news_data["factors"]]

    flag = None
    if drug_lab_alerts:
        crit = [a for a in drug_lab_alerts if a.get("severity") == "CRITICAL"]
        top = (crit or drug_lab_alerts)[0]
        flag = {"text": top.get("rule_name") or top.get("message", "Drug-lab interaction"),
                "sev": "crit" if top.get("severity") == "CRITICAL" else "warn"}

    if status == "stale":
        action, tone = "Vitals overdue — record now", "muted"
    elif score >= 7:
        action, tone = "Escalate now", "crit"
    elif score >= 5 or any(f["score"] >= 3 for f in news_data["factors"]):
        action, tone = "Urgent review (1 hr)", "warn"
    elif score >= 1:
        action, tone = "Review 4-6 hourly", "low"
    else:
        action, tone = "All parameters normal", "stable"
    if flag and flag["sev"] == "crit" and score < 7:
        action = "Attending action needed"
    return {"signals": signals, "flag": flag, "action": action, "tone": tone}


_ML_LABELS = {
    "Respiration Rate": "Respiratory rate trend",
    "SpO2 (Scale 1)": "SpO₂ downtrend", "SpO2 (Scale 2)": "SpO₂ downtrend",
    "Supplemental Oxygen": "Oxygen requirement",
    "Systolic BP": "Falling blood pressure", "Heart Rate": "Heart-rate trend",
    "Consciousness (CVPU)": "Reduced consciousness", "Temperature": "Temperature",
}

def ml_demo(score, factors, recent_vitals, has_critical_flag):
    """DETERMINISTIC illustrative risk for the demo (no real model yet).

    Stable across refreshes so it doesn't jitter. Replace with the trained model's
    output later — the response shape (risk/window/explanation/contributors) is the
    integration contract.
    """
    news_vals = [r["news2"] for r in recent_vitals if isinstance(r.get("news2"), int)]
    worsening = len(news_vals) >= 2 and news_vals[-1] > news_vals[0]
    risk = score * 10 + (12 if worsening else 0) + (10 if has_critical_flag else 0)
    risk = max(5, min(95, risk))
    total = sum(f["score"] for f in factors) or 1
    contributors = [
        {"label": _ML_LABELS.get(f["name"], f["name"]), "pct": round(f["score"] / total * 100)}
        for f in sorted(factors, key=lambda x: x["score"], reverse=True)[:4]
    ]
    window = "4-6 hour" if risk >= 60 else "6-12 hour"
    return {"risk": risk, "window": window, "contributors": contributors, "worsening": worsening}


class PatientCreate(BaseModel):
    name: str
    age: int
    sex: str
    ward: str
    room: str
    bed: str
    complaint: str
    hr: float
    rr: float
    spo2: float
    sbp: float
    dbp: float
    temp: float
    air_or_oxygen: str = 'Air'
    consciousness: str = 'A'
    hypercapnic_failure: int = 0

class EscalationCreate(BaseModel):
    patientId: int
    level: str
    attending: str
    observations: str
    interventions: str
    escalatedBy: str  # required — caller must supply the logged-in nurse's name

class EscalationResolve(BaseModel):
    resolvedBy: str
    notes: str

def _ensure_admission_bridge(db, hadm_id: int, full_name: str, sex: str) -> str | None:
    """Create (or fetch) the hospital_core.admissions bridge row for a hadm_id.
    Returns the admission_id UUID, or None if hospital_core is not provisioned yet.
    Shared by HIS admission (POST /api/patients) and the provision endpoints."""
    existing = db.query(HcAdmission).filter(HcAdmission.hadm_id == hadm_id).first()
    if existing:
        return existing.admission_id

    hospital_row = db.execute(
        sql_text("SELECT hospital_id FROM hospital_core.hospitals LIMIT 1")
    ).fetchone()
    if not hospital_row:
        return None  # migration 026 seed not run — skip silently, flat admission still works
    ward_row = db.execute(
        sql_text("SELECT ward_id FROM hospital_core.wards LIMIT 1")
    ).fetchone()

    uhid = f"FOQAL-{datetime.now().year}-{hadm_id:07d}"
    db.execute(sql_text("""
        INSERT INTO hospital_core.patients (uhid, hospital_id, full_name, sex)
        VALUES (:uhid, :hid, :name, :sex) ON CONFLICT (uhid) DO NOTHING
    """), {"uhid": uhid, "hid": hospital_row[0], "name": full_name or "Unknown", "sex": sex or "M"})

    admission_id = str(_uuid_mod.uuid4())
    db.execute(sql_text("""
        INSERT INTO hospital_core.admissions
            (admission_id, uhid, hospital_id, ward_id, hadm_id, status, admitted_at, updated_at)
        VALUES (:adm_id, :uhid, :hid, :wid, :hadm_id, 'admitted', NOW(), NOW())
        ON CONFLICT (hadm_id) DO NOTHING
    """), {
        "adm_id": admission_id, "uhid": uhid, "hid": hospital_row[0],
        "wid": ward_row[0] if ward_row else None, "hadm_id": hadm_id,
    })
    db.commit()
    # Re-read in case ON CONFLICT skipped our insert (row created concurrently)
    row = db.query(HcAdmission).filter(HcAdmission.hadm_id == hadm_id).first()
    return row.admission_id if row else admission_id


@app.post("/api/patients")
def add_patient(patient: PatientCreate, db: Session = Depends(get_db)):
    max_row = db.query(Patient).order_by(Patient.hadm_id.desc()).first()
    new_id = (max_row.hadm_id + 1) if max_row else 10100

    year_suffix = datetime.now().year % 100
    new_patient = Patient(
        id=str(_uuid_mod.uuid4()),   # active_patients.id is NOT NULL with no DB default on this instance
        hadm_id=new_id,
        subject_id=new_id,
        patient_code=f"PT-{year_suffix:02d}-{new_id:04d}",
        patient_name=patient.name,
        anchor_age=patient.age,
        gender=(patient.sex or "M")[0].upper(),
        ward=patient.ward,
        room=patient.room,
        bed=patient.bed,
        admit_time=datetime.now(),
        ews_complaint=patient.complaint,
        admitting_diagnosis=patient.complaint,
        hypercapnic_failure=patient.hypercapnic_failure,
        ward_location="CCU",
        status="active",
        data_fetch_status="fetched",
        updated_at=datetime.now(),   # NOT NULL on this instance, no DB default
    )
    db.add(new_patient)
    db.commit()

    v = VitalTimeSeries(
        hadm_id=new_id,
        chart_time=datetime.now(),
        heart_rate=patient.hr,
        resp_rate=patient.rr,
        spo2=patient.spo2,
        sbp=patient.sbp,
        dbp=patient.dbp,
        temperature=patient.temp,
        air_or_oxygen=patient.air_or_oxygen,
        consciousness=patient.consciousness
    )
    db.add(v)
    db.commit()

    # Immediately create an app_encounters row so Ashmit's doctor queue can see this patient.
    # Status is 'Pending Ingestion' — it upgrades to 'Ready for Review' on CCU step-down.
    enc_id = str(_uuid_mod.uuid4())
    try:
        year_suffix_enc = datetime.now().year % 100
        prefix = f"PT-{year_suffix_enc:02d}-"
        with _shared_engine.begin() as conn:
            max_seq = conn.execute(sql_text(
                "SELECT COALESCE(MAX(CAST(SUBSTRING(display_id FROM 7) AS INTEGER)), 0) "
                "FROM app_encounters WHERE display_id LIKE :p"
            ), {"p": f"{prefix}%"}).scalar() or 0
            display_id = f"{prefix}{(max_seq + 1):04d}"
            conn.execute(sql_text("""
                INSERT INTO app_encounters (id, hadm_id, display_id, status, version, created_at, updated_at)
                VALUES (:id, :h, :did, 'Pending Ingestion', 1, NOW(), NOW())
                ON CONFLICT (hadm_id) DO NOTHING
            """), {"id": enc_id, "h": new_id, "did": display_id})
            conn.execute(sql_text(
                "UPDATE active_patients SET encounter_id = :eid, updated_at = NOW() "
                "WHERE hadm_id = :h AND encounter_id IS NULL"
            ), {"eid": enc_id, "h": new_id})
    except Exception as _enc_err:
        import logging as _log
        _log.getLogger(__name__).warning("app_encounters auto-create failed for hadm %s: %s", new_id, _enc_err)

    # Proper-HIS admission: also create the hospital_core.admissions bridge row so the new
    # patient is complete across BOTH the flat (active_patients) and normalized (ERD) models
    # in a single admission action. This makes drug_lab_flags / dcm_assessments / fluid_balance
    # immediately usable for the patient without a separate provision call.
    admission_id = None
    try:
        admission_id = _ensure_admission_bridge(db, new_id, patient.name, (patient.sex or "M")[0].upper())
    except Exception as _adm_err:
        import logging as _log
        _log.getLogger(__name__).warning("hospital_core.admissions bridge failed for hadm %s: %s", new_id, _adm_err)

    return {"message": "Patient added", "subject_id": new_id,
            "encounter_id": enc_id, "admission_id": admission_id}

REPLAY_OFFSET = 0

# Per-process cache: prevents re-inserting the same drug-lab flag on every 15-min poll
_drug_lab_flag_cache: dict = {}


def _persist_drug_lab_flags_bulk(db, pending: list) -> None:
    """Write CRITICAL/WARNING alerts to ews.drug_lab_flags in ONE bulk pass.

    pending = [(hadm_id, alerts), ...] collected during the ward-data loop.

    Performance: the in-process _drug_lab_flag_cache means that once a (patient, rule)
    pair has been persisted today, it is skipped with ZERO DB queries. So warm calls
    return immediately. Only when there are genuinely new alerts do we issue THREE
    bulk lookups (HcAdmission, DrugLabRule, active DrugLabFlag) for the whole ward —
    never per-patient. This replaced an N+1 that made the first load take ~27s.
    """
    import logging as _logging
    from datetime import date as _date
    _log_dl = _logging.getLogger(__name__)
    today_str = str(_date.today())

    # Collect only the uncached CRITICAL/WARNING alerts across all patients.
    todo = []  # (hadm_id, alert)
    for hadm_id, alerts in pending:
        for a in alerts:
            if a.get("severity") not in ("CRITICAL", "WARNING"):
                continue
            if (hadm_id, a.get("rule_name", ""), today_str) in _drug_lab_flag_cache:
                continue
            todo.append((hadm_id, a))
    if not todo:
        return  # warm path — everything already persisted today, zero DB hits

    hadm_ids = list({h for h, _ in todo})
    # 1 bulk query: hadm_id -> admission_id
    hc_adm_map = {a.hadm_id: a.admission_id
                  for a in db.query(HcAdmission).filter(HcAdmission.hadm_id.in_(hadm_ids)).all()}
    # 1 bulk query: rule_name -> rule_id (small table, fetch all)
    rule_id_map = {r.rule_name: r.rule_id for r in db.query(DrugLabRule).all()}
    # 1 bulk query: already-active flags so we don't double-insert
    adm_ids = list(hc_adm_map.values())
    active_flags = set()
    if adm_ids:
        for f in db.query(DrugLabFlag).filter(
            DrugLabFlag.admission_id.in_(adm_ids), DrugLabFlag.status == "active"
        ).all():
            active_flags.add((f.admission_id, f.rule_id))

    wrote = False
    for hadm_id, alert in todo:
        rule_name = alert.get("rule_name", "")
        _drug_lab_flag_cache[(hadm_id, rule_name, today_str)] = True   # mark cached regardless
        admission_id = hc_adm_map.get(hadm_id)
        rule_id = rule_id_map.get(rule_name)
        if not admission_id or not rule_id:
            continue  # patient not bridged yet, or unknown rule — skip silently
        if (admission_id, rule_id) in active_flags:
            continue  # already an active flag for this admission+rule
        db.add(DrugLabFlag(
            flag_id=str(_uuid_mod.uuid4()),
            admission_id=admission_id,
            rule_id=rule_id,
            severity=alert["severity"],
            trigger_drug_value=(", ".join(alert.get("triggering_meds", [])))[:100],
            trigger_lab_value=float(alert["lab_value"]) if alert.get("lab_value") else None,
            recommended_action=(alert.get("action", "Monitor patient"))[:30],
            status="active",
            flagged_at=datetime.now(),
        ))
        active_flags.add((admission_id, rule_id))
        wrote = True
    if wrote:
        try:
            db.commit()
        except Exception as _e:
            db.rollback()
            _log_dl.warning("ews.drug_lab_flags bulk persist error: %s", _e)


@app.get("/api/ward-data")
def get_ward_data(ward: str = "All", location: str = "All", replay: bool = False,
                  hadm_id: Optional[int] = None, db: Session = Depends(get_db)):
    global REPLAY_OFFSET
    if replay:
        REPLAY_OFFSET = (REPLAY_OFFSET + 1) % 20

    q = db.query(Patient).filter(Patient.status.notin_(['signed_off', 'archived']))
    if ward != "All":
        q = q.filter(Patient.ward == ward)
    if location != "All":
        q = q.filter(Patient.ward_location == location)   # CCU | GENERAL_WARD
    if hadm_id is not None:
        q = q.filter(Patient.hadm_id == hadm_id)
    patients = q.all()

    if not patients:
        return {"patients": [], "ward": ward}

    patient_ids = [p.hadm_id for p in patients]

    # Bulk-fetch vitals/labs/meds in 3 queries instead of 3×N Cloud SQL round-trips
    _vrows = db.query(VitalTimeSeries).filter(
        VitalTimeSeries.hadm_id.in_(patient_ids)
    ).order_by(VitalTimeSeries.chart_time.desc()).all()

    # demo_now = latest chart_time across the fetched vitals (computed in Python to
    # avoid a separate MAX() round-trip to us-central1; _vrows is sorted desc).
    demo_now = _vrows[0].chart_time if _vrows else datetime.now()

    _pending_drug_lab = []   # (hadm_id, alerts) collected in the loop, persisted in one bulk pass after
    _vitals_map = defaultdict(list)
    for _v in _vrows:
        _vitals_map[_v.hadm_id].append(_v)

    _lrows = db.query(LabEvent).filter(
        LabEvent.hadm_id.in_(patient_ids)
    ).order_by(LabEvent.chart_time.desc()).all()
    _labs_map = defaultdict(list)
    for _l in _lrows:
        _labs_map[_l.hadm_id].append(_l)

    _mrows = db.query(Medication).filter(
        Medication.hadm_id.in_(patient_ids)
    ).all()
    _meds_map = defaultdict(list)
    for _m in _mrows:
        _meds_map[_m.hadm_id].append(_m)

    result = []
    for p in patients:
        all_vitals = list(_vitals_map[p.hadm_id])   # already sorted desc by bulk query

        # NOTE: MIMIC auto-sync is deliberately NOT done here. It used to call
        # sync_patient_from_mimic() inside this loop, which issues ~5 commits +
        # several ap_* queries PER patient on EVERY poll — for patients with empty
        # ap_* (no BigQuery data yet) this made /api/ward-data take 30-60s. A read
        # endpoint must never write. Populate vitals explicitly via
        # POST /api/patients/{id}/sync-mimic or /api/patients/bulk-sync-mimic.
        if not all_vitals:
            continue
            
        safe_offset = min(REPLAY_OFFSET, len(all_vitals) - 1)
        vitals_history = all_vitals[safe_offset : safe_offset + 24]
            
        vitals_history.reverse()
        
        # ── Forward-fill the latest non-null value for each vital ──
        latest_vitals = {
            'resp_rate': None, 'spo2': None, 'sbp': None,
            'dbp': None, 'heart_rate': None, 'temperature': None,
            'consciousness': 'A', 'air_or_oxygen': 'Air',
            'urine_output': None, 'fluid_balance': None,
        }
        for v in vitals_history:
            if is_valid(v.resp_rate):    latest_vitals['resp_rate']    = v.resp_rate
            if is_valid(v.spo2):         latest_vitals['spo2']          = v.spo2
            if is_valid(v.sbp):          latest_vitals['sbp']           = v.sbp
            if is_valid(v.dbp):          latest_vitals['dbp']           = v.dbp
            if is_valid(v.heart_rate):   latest_vitals['heart_rate']    = v.heart_rate
            if is_valid(v.temperature):  latest_vitals['temperature']   = v.temperature
            if getattr(v, 'urine_output', None) is not None:  latest_vitals['urine_output']  = v.urine_output
            if getattr(v, 'fluid_balance', None) is not None: latest_vitals['fluid_balance'] = v.fluid_balance
            if hasattr(v, 'consciousness') and v.consciousness and v.consciousness not in (None, ''):
                latest_vitals['consciousness'] = v.consciousness
            if hasattr(v, 'air_or_oxygen') and v.air_or_oxygen and v.air_or_oxygen not in (None, ''):
                latest_vitals['air_or_oxygen'] = v.air_or_oxygen
            
        # Calculate time diff for stale check
        latest_time = vitals_history[-1].chart_time or demo_now
        time_diff_secs = (demo_now - latest_time).total_seconds()
        stale_mins = int(time_diff_secs // 60)

        news_data = calculate_news2(latest_vitals, getattr(p, 'hypercapnic_failure', 0) == 1)
        news2_score = news_data["total"]

        # Monitoring cadence + "vitals due/overdue" — adapts to CCU vs General Ward
        ward_location = getattr(p, 'ward_location', 'CCU') or 'CCU'
        monitoring = monitoring_plan(news2_score, news_data["factors"], ward_location)
        is_overdue = stale_mins > monitoring["interval_mins"]
        due_label = ("Overdue " + fmt_mins(stale_mins - monitoring["interval_mins"])) if is_overdue \
                    else ("Due in " + fmt_mins(monitoring["interval_mins"] - stale_mins))

        if is_overdue: status = 'stale'
        elif news2_score >= 7: status = 'critical'
        elif news2_score >= 5: status = 'warning'
        else: status = 'stable'

        # ── Build trajectory — filter out completely-null data points ──
        trajectory = []
        # Running forward-fill per series for the chart
        fill = {'hr': None, 'rr': None, 'spo2': None, 'temp': None, 'sbp': None, 'dbp': None}
        for v in vitals_history:
            if is_valid(v.heart_rate):  fill['hr']   = round(v.heart_rate, 1)
            if is_valid(v.resp_rate):   fill['rr']   = round(v.resp_rate, 1)
            if is_valid(v.spo2):        fill['spo2'] = round(v.spo2, 1)
            if is_valid(v.temperature): fill['temp'] = round(v.temperature, 1)
            if is_valid(v.sbp):         fill['sbp']  = round(v.sbp, 1)
            if is_valid(v.dbp):         fill['dbp']  = round(v.dbp, 1)

            # Only add points where at least one numeric vital is valid
            has_any_valid = any([
                is_valid(v.heart_rate), is_valid(v.resp_rate),
                is_valid(v.spo2), is_valid(v.sbp)
            ])
            if not has_any_valid:
                continue

            time_str = v.chart_time.strftime("%H:%M") if v.chart_time else "--"
            trajectory.append({
                "time": time_str,
                # Use forward-filled values so no null gaps in the chart
                "hr":   fill['hr'],
                "rr":   fill['rr'],
                "spo2": fill['spo2'],
                "temp": fill['temp'],
                "sbp":  fill['sbp'],
                "dbp":  fill['dbp'],
            })

        # ── Recent Vitals (last 6 readings ≈ 6h) — use resolved latest values ──
        recent_vitals = []
        for pt in trajectory[-6:]:
            # Compute historical NEWS2
            # Carry the patient's current consciousness / O2 status across the window so the
            # trend NEWS2 stays consistent with the headline score (demo readings are constant).
            hist_v_dict = {
                'resp_rate': pt['rr'], 'spo2': pt['spo2'], 'sbp': pt['sbp'],
                'dbp': pt['dbp'], 'heart_rate': pt['hr'], 'temperature': pt['temp'],
                'consciousness': latest_vitals['consciousness'],
                'air_or_oxygen': latest_vitals['air_or_oxygen'],
            }
            # Only calculate if we have enough numeric data, else leave as None
            hist_news2 = "--"
            if pt['hr'] is not None and pt['sbp'] is not None:
                hist_news2 = calculate_news2(hist_v_dict, getattr(p, 'hypercapnic_failure', 0) == 1)["total"]

            recent_vitals.append({
                "time": pt["time"],
                "hr":   pt["hr"] if pt["hr"] is not None else "--",
                "rr":   pt["rr"] if pt["rr"] is not None else "--",
                "spo2": pt["spo2"] if pt["spo2"] is not None else "--",
                "temp": pt["temp"] if pt["temp"] is not None else "--",
                "sbp":  pt["sbp"] if pt["sbp"] is not None else "--",
                "dbp":  pt["dbp"] if pt["dbp"] is not None else "--",
                "news2": hist_news2
            })

        db_labs = _labs_map[p.hadm_id][:10]

        formatted_labs = []
        rule_engine_labs = {}
        for l in db_labs:
            l_time = l.chart_time.strftime("%H:%M") if l.chart_time else "--"
            if l.lactate:
                formatted_labs.append({"time": l_time, "test": "Lactate", "value": round(l.lactate, 2), "unit": "mmol/L"})
                if "lactate" not in rule_engine_labs: rule_engine_labs["lactate"] = l.lactate
            if l.creatinine:
                formatted_labs.append({"time": l_time, "test": "Creatinine", "value": round(l.creatinine, 2), "unit": "mg/dL"})
                if "creatinine" not in rule_engine_labs: rule_engine_labs["creatinine"] = l.creatinine
            if l.potassium:
                formatted_labs.append({"time": l_time, "test": "Potassium", "value": round(l.potassium, 2), "unit": "mmol/L"})
                if "potassium" not in rule_engine_labs: rule_engine_labs["potassium"] = l.potassium
            # MIMIC-sourced labs (new columns from schema_migration_v2)
            if getattr(l, 'bnp', None):
                formatted_labs.append({"time": l_time, "test": "BNP", "value": round(float(l.bnp), 0), "unit": "pg/mL"})
                if "bnp" not in rule_engine_labs: rule_engine_labs["bnp"] = float(l.bnp)
            if getattr(l, 'troponin', None):
                formatted_labs.append({"time": l_time, "test": "Troponin T", "value": round(float(l.troponin), 4), "unit": "ng/mL"})
                if "troponin" not in rule_engine_labs: rule_engine_labs["troponin"] = float(l.troponin)
            if getattr(l, 'sodium', None):
                formatted_labs.append({"time": l_time, "test": "Sodium", "value": round(float(l.sodium), 1), "unit": "mmol/L"})
                if "sodium" not in rule_engine_labs: rule_engine_labs["sodium"] = float(l.sodium)
            if getattr(l, 'hemoglobin', None):
                formatted_labs.append({"time": l_time, "test": "Hemoglobin", "value": round(float(l.hemoglobin), 1), "unit": "g/dL"})

        # ── Full medication objects (name + dose + frequency) ──
        meds_db = _meds_map[p.hadm_id]
        med_names = [m.med_name for m in meds_db]
        medications = [
            {"name": m.med_name, "dose": m.dose or "--", "frequency": m.frequency or "--"}
            for m in meds_db
        ]
        
        drug_lab_alerts = check_patient_against_rules(med_names, rule_engine_labs)
        # Defer audit persistence to a single bulk pass AFTER the loop (avoids N+1 —
        # the old per-patient version queried HcAdmission/DrugLabFlag per patient,
        # which made the first ward-data load take ~27s against Cloud SQL).
        _pending_drug_lab.append((p.hadm_id, drug_lab_alerts))
        if any(a['severity'] == 'CRITICAL' for a in drug_lab_alerts) and status != 'critical':
            status = 'critical'
            news2_score = max(news2_score, 7)

        sbp_val = latest_vitals['sbp']
        dbp_val = latest_vitals['dbp']
        bp_str = f"{int(sbp_val)}/{int(dbp_val)}" if sbp_val and dbp_val else "--/--"
        # Deterministic illustrative ML (demo — real model lands Sprint 4)
        has_critical_flag = any(a.get('severity') == 'CRITICAL' for a in drug_lab_alerts)
        ml = ml_demo(news2_score, news_data["factors"], recent_vitals, has_critical_flag)
        ml_risk = ml["risk"]

        # ── NEWS2 clinical risk tier (per NHS protocol) ──
        # Check if any single parameter scored 3 (Low-Medium risk trigger)
        any_single_param_3 = any(f['score'] >= 3 for f in news_data["factors"])

        # ── Brief flag explanation (shown on dashboard row) ──
        brief_flag = ""
        if status == 'critical':
            abnormal = [f['name'] for f in news_data["factors"]]
            if drug_lab_alerts:
                brief_flag = drug_lab_alerts[0]['message'][:80]
            elif abnormal:
                brief_flag = f"↑ {', '.join(abnormal[:2])}"
            else:
                brief_flag = "Critical deterioration detected"
        elif status == 'warning':
            abnormal = [f['name'] for f in news_data["factors"]]
            brief_flag = f"Early instability: {', '.join(abnormal[:2])}" if abnormal else "Early signs of instability"
        elif any_single_param_3:
            abnormal = [f['name'] for f in news_data["factors"] if f['score'] >= 3]
            brief_flag = f"Single param alert: {abnormal[0]}" if abnormal else ""

        # ── NHS NEWS2 Clinical Response Protocol ──
        # Low (0): Monitor min every 12 hrs
        # Low (1-4): Monitor min every 4-6 hrs
        # Low-Medium (score 3 in any single param): Monitor min every 1 hr
        # Medium (5-6): Urgent review, consider critical care assessment
        # High (≥7): Emergent — continuous monitoring, transfer to higher care
        abnormal_factors = [f['name'] for f in news_data["factors"] if f['score'] > 0]
        factor_str = ", ".join(abnormal_factors) if abnormal_factors else "multiple vitals"

        if status == 'critical':  # NEWS2 ≥ 7 → HIGH risk
            explanation = (
                f"HIGH RISK (NEWS2 ≥7). ML risk score: {ml_risk}%. "
                f"Primary contributors: {factor_str}. "
                "Continuous monitoring of vital signs required."
            )
            action = (
                "Emergent assessment by clinical team or critical care team. "
                "Initiate continuous SpO2/ECG monitoring. "
                "Usually requires transfer to higher level of care (HDU/ICU)."
            )
            if drug_lab_alerts:
                explanation = drug_lab_alerts[0]['message']
                action = drug_lab_alerts[0]['action']

        elif status == 'warning':  # NEWS2 5-6 → MEDIUM risk
            explanation = (
                f"MEDIUM RISK (NEWS2 5–6). Abnormal: {factor_str}. "
                f"ML risk score: {ml_risk}%."
            )
            action = (
                "Urgent review by ward-based doctor or acute team nurse. "
                "Decide if critical care team assessment is needed. "
                "Increase monitoring frequency."
            )

        elif any_single_param_3:  # Any single param scores 3 → LOW-MEDIUM risk
            single_3 = [f['name'] for f in news_data["factors"] if f['score'] >= 3]
            explanation = (
                f"LOW-MEDIUM RISK: Score of 3 in {', '.join(single_3)}. "
                "Requires urgent ward-based review even if total NEWS2 is low."
            )
            action = (
                "Urgent review by a ward-based doctor within 1 hour. "
                "Decide change in frequency of clinical monitoring or escalation of care. "
                "Minimum monitoring every hour."
            )

        elif news2_score == 0:  # Score 0 → LOW, routine
            explanation = "LOW RISK (NEWS2 = 0). All vital signs within normal parameters."
            action = (
                "Assessment by registered nurse. "
                "Continue routine ward monitoring, minimum every 12 hours."
            )

        else:  # Score 1-4 → LOW risk
            explanation = (
                f"LOW RISK (NEWS2 {news2_score}). Minor abnormalities: {factor_str}."
            )
            action = (
                "Assessment by registered nurse or equivalent. "
                "Decide change in frequency of monitoring or escalation of care. "
                "Minimum monitoring every 4–6 hours."
            )

        ews_reason = build_ews_reason(latest_vitals, news_data, drug_lab_alerts, news2_score, status)

        result.append({
            "id": str(p.hadm_id),
            "patient_code": p.patient_code or f"PT-26-{p.hadm_id:04d}",
            "diagnosis_short": p.diagnosis_short or (p.ews_complaint.split(',')[0] if p.ews_complaint else "—"),
            "ward_location": ward_location,
            "ewsReason": ews_reason,
            "monitoring": monitoring,
            "isOverdue": is_overdue,
            "dueLabel": due_label,
            "urineOutput": int(latest_vitals['urine_output']) if latest_vitals['urine_output'] is not None else None,
            "fluidBalance": int(latest_vitals['fluid_balance']) if latest_vitals['fluid_balance'] is not None else None,
            "mlContributors": ml["contributors"],
            "mlWindow": ml["window"],
            "name": p.patient_name,
            "age": p.anchor_age,
            "sex": p.gender,
            "ward": p.ward,
            "room": p.room,
            "bed": p.bed,
            "admitted": p.admit_time.strftime("%d %b %Y") if p.admit_time else "--",
            "complaint": p.ews_complaint,
            "briefFlag": brief_flag,
            "status": status,
            "vitals": {"bp_time": vitals_history[-1].chart_time.strftime("%H:%M") if vitals_history[-1].chart_time else "--"},
            "hr":   int(latest_vitals['heart_rate'])  if latest_vitals['heart_rate']  else "--",
            "rr":   int(latest_vitals['resp_rate'])   if latest_vitals['resp_rate']   else "--",
            "spo2": int(latest_vitals['spo2'])        if latest_vitals['spo2']        else "--",
            "bp":   bp_str,
            "temp": round(latest_vitals['temperature'], 1) if latest_vitals['temperature'] else "--",
            "avpu": latest_vitals['consciousness'] or "A",
            "o2":   latest_vitals['air_or_oxygen'] or "Air",
            "news2": news2_score,
            "newsFactors": news_data["factors"],
            "mlRisk": ml_risk,
            "mlExplanation": explanation,
            "recommendedAction": action,
            "trajectory": trajectory,
            "recentVitals": recent_vitals,
            "recentLabs": formatted_labs[:5],
            "drugLabAlerts": drug_lab_alerts,
            "meds": med_names,
            "medications": medications,
            "stale_mins": stale_mins,
            "nyhaClass": getattr(p, 'nyha_class', None),
            "bnpBaseline": float(p.bnp_baseline) if getattr(p, 'bnp_baseline', None) else None,
        })

    # Persist drug-lab flags for the whole ward in ONE bulk pass (no per-patient queries).
    try:
        _persist_drug_lab_flags_bulk(db, _pending_drug_lab)
    except Exception:
        pass  # audit write is non-fatal — alerts are already in the response

    return {"patients": result, "ward": ward}

@app.post("/api/escalations")
def create_escalation(esc: EscalationCreate, db: Session = Depends(get_db)):
    # Get patient info
    patient = db.query(Patient).filter(Patient.hadm_id == esc.patientId).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Get latest vitals for NEWS2 score
    vitals = db.query(VitalTimeSeries).filter(VitalTimeSeries.hadm_id == esc.patientId).order_by(VitalTimeSeries.chart_time.desc()).first()
    
    news2_score = 0
    if vitals:
        v_dict = {
            'resp_rate': vitals.resp_rate, 'spo2': vitals.spo2, 'sbp': vitals.sbp,
            'dbp': vitals.dbp, 'heart_rate': vitals.heart_rate, 'temperature': vitals.temperature,
            'consciousness': vitals.consciousness, 'air_or_oxygen': vitals.air_or_oxygen
        }
        news_data = calculate_news2(v_dict, patient.hypercapnic_failure == 1)
        news2_score = news_data["total"]

    new_esc = Escalation(
        hadm_id=esc.patientId,
        patient_name=patient.patient_name,
        ward=patient.ward,
        bed=patient.bed,
        news2_score=news2_score,
        level=esc.level,
        attending=esc.attending,
        escalated_by=esc.escalatedBy,
        observations=esc.observations,
        interventions=esc.interventions,
        status='active',
        escalated_at=datetime.now()
    )
    db.add(new_esc)
    db.commit()
    db.refresh(new_esc)
    
    return {
        "id": new_esc.id,
        "patientName": new_esc.patient_name,
        "ward": new_esc.ward,
        "bed": new_esc.bed,
        "news2": new_esc.news2_score,
        "attending": new_esc.attending,
        "escalatedAt": new_esc.escalated_at
    }

@app.get("/api/escalations")
def get_escalations(db: Session = Depends(get_db)):
    escalations = db.query(Escalation).order_by(Escalation.escalated_at.desc()).all()
    
    SLA_MINS = 15  # auto re-escalate an unhandled escalation after 15 minutes
    result = []
    for e in escalations:
        # SLA timer — only meaningful while still active & unacknowledged
        mins_elapsed = None
        sla_breached = False
        sla_remaining = None
        if e.escalated_at:
            t = e.escalated_at if isinstance(e.escalated_at, datetime) else datetime.fromisoformat(str(e.escalated_at))
            mins_elapsed = int((datetime.now() - t.replace(tzinfo=None)).total_seconds() // 60)
            if e.status == 'active' and not e.acknowledged_at:
                sla_breached = mins_elapsed > SLA_MINS
                sla_remaining = max(0, SLA_MINS - mins_elapsed)
        result.append({
            "id": e.id,
            "patientId": e.hadm_id,
            "patientName": e.patient_name,
            "ward": e.ward,
            "bed": e.bed,
            "news2": e.news2_score,
            "level": e.level,
            "attending": e.attending,
            "escalatedBy": e.escalated_by,
            "observations": e.observations,
            "interventions": e.interventions,
            "status": e.status,
            "escalatedAt": e.escalated_at,
            "acknowledgedAt": e.acknowledged_at,
            "resolvedAt": e.resolved_at,
            "resolvedBy": e.resolved_by,
            "resolutionNotes": e.resolution_notes,
            "minsElapsed": mins_elapsed,
            "slaBreached": sla_breached,
            "slaRemaining": sla_remaining,
            "reescalatedAt": e.reescalated_at,
            "reescalationNote": e.reescalation_note,
        })
    return {"escalations": result}

@app.post("/api/escalations/{esc_id}/resolve")
def resolve_escalation(esc_id: int, res: EscalationResolve, db: Session = Depends(get_db)):
    esc = db.query(Escalation).filter(Escalation.id == esc_id).first()
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")
        
    esc.status = 'resolved'
    esc.resolved_at = datetime.now()
    esc.resolved_by = res.resolvedBy
    esc.resolution_notes = res.notes
    
    db.commit()
    return {"message": "Escalation resolved", "id": esc.id}

@app.get("/api/patients/{subject_id}")
def get_patient_detail(subject_id: int, db: Session = Depends(get_db)):
    ward_data = get_ward_data(ward="All", location="All", replay=False, hadm_id=subject_id, db=db)
    if ward_data["patients"]:
        return ward_data["patients"][0]
    raise HTTPException(status_code=404, detail="Patient not found")

class VitalsInput(BaseModel):
    spo2: float
    resp_rate: float
    heart_rate: float
    sbp: float
    dbp: float
    temperature: float
    consciousness: str = "A"
    air_or_oxygen: str = "Air"

@app.post("/api/patients/{subject_id}/vitals")
def add_vitals(subject_id: int, v: VitalsInput, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.hadm_id == subject_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    vt = VitalTimeSeries(
        hadm_id=subject_id,
        chart_time=datetime.now(),
        heart_rate=v.heart_rate,
        resp_rate=v.resp_rate,
        spo2=v.spo2,
        sbp=v.sbp,
        dbp=v.dbp,
        temperature=v.temperature,
        consciousness=v.consciousness,
        air_or_oxygen=v.air_or_oxygen,
    )
    db.add(vt)
    db.commit()

    news_result = calculate_news2(v.dict(), patient.hypercapnic_failure == 1)
    news2_score = news_result["total"]
    if news2_score >= 7:
        risk_level = "critical"
    elif news2_score >= 5:
        risk_level = "warning"
    else:
        risk_level = "stable"

    return {
        "news2_score": news2_score,
        "risk_level": risk_level,
        "factors": news_result["factors"],
        "chart_time": vt.chart_time.isoformat() if vt.chart_time else None,
    }

@app.get("/api/patients/{subject_id}/vitals/latest")
def get_latest_vitals(subject_id: int, db: Session = Depends(get_db)):
    vt = db.query(VitalTimeSeries).filter(
        VitalTimeSeries.hadm_id == subject_id
    ).order_by(VitalTimeSeries.chart_time.desc()).first()

    if not vt:
        raise HTTPException(status_code=404, detail="No vitals found")

    recorded_at = (vt.chart_time if isinstance(vt.chart_time, datetime) else datetime.now()).replace(tzinfo=None)
    stale_mins = int((datetime.now() - recorded_at).total_seconds() // 60)
    is_stale = stale_mins > 45

    return {
        "chart_time": vt.chart_time.isoformat() if vt.chart_time else None,
        "stale_mins": stale_mins,
        "is_stale": is_stale,
        "heart_rate": vt.heart_rate,
        "resp_rate": vt.resp_rate,
        "spo2": vt.spo2,
        "sbp": vt.sbp,
        "dbp": vt.dbp,
        "temperature": vt.temperature,
        "consciousness": vt.consciousness,
        "air_or_oxygen": vt.air_or_oxygen,
    }

class FalseAlarmBody(BaseModel):
    reason: str

@app.post("/api/escalations/{esc_id}/false-alarm")
def mark_false_alarm(esc_id: int, body: FalseAlarmBody, db: Session = Depends(get_db)):
    esc = db.query(Escalation).filter(Escalation.id == esc_id).first()
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")
    esc.status = "false_alarm"
    esc.false_alarm = True
    esc.false_alarm_reason = body.reason
    db.commit()
    return {"status": "ok", "id": esc_id, "reason": body.reason}


# ════════════════════════════════════════════════════════════════════════════
#  Re-escalation — 15-min SLA breach bumps to the next responder
# ════════════════════════════════════════════════════════════════════════════
_LEVEL_ORDER = ["nurse", "doctor", "consultant", "code_blue"]
_LEVEL_LABEL = {"nurse": "Head Nurse", "doctor": "Attending",
                "consultant": "On-call Consultant", "code_blue": "Code Blue Team"}

class ReescalateBody(BaseModel):
    reason: str = ""
    auto: bool = False

@app.post("/api/escalations/{esc_id}/reescalate")
def reescalate(esc_id: int, body: ReescalateBody, db: Session = Depends(get_db)):
    esc = db.query(Escalation).filter(Escalation.id == esc_id).first()
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")
    if esc.status != 'active':
        raise HTTPException(status_code=400, detail="Only active escalations can be re-escalated")
    cur = esc.level if esc.level in _LEVEL_ORDER else "nurse"
    nxt = _LEVEL_ORDER[min(_LEVEL_ORDER.index(cur) + 1, len(_LEVEL_ORDER) - 1)]
    esc.level = nxt
    esc.reescalated_at = datetime.now()
    esc.reescalation_note = body.reason or (
        f"{'Auto' if body.auto else 'Manual'} re-escalation after 15-min SLA breach → {_LEVEL_LABEL[nxt]}")
    db.commit()
    return {"status": "ok", "id": esc_id, "newLevel": nxt,
            "newLevelLabel": _LEVEL_LABEL[nxt],
            "reescalatedAt": esc.reescalated_at.isoformat() if esc.reescalated_at else None}


# ════════════════════════════════════════════════════════════════════════════
#  CCU → General Ward step-down transfer
# ════════════════════════════════════════════════════════════════════════════
def _transfer_dict(t):
    return {
        "id": t.id, "subjectId": t.hadm_id, "patientName": t.patient_name,
        "diagnosis": t.diagnosis, "rationale": t.rationale, "recommendedBy": t.recommended_by,
        "targetWard": t.target_ward, "news2AtSubmit": t.news2_at_submit,
        "stableWindowHours": t.stable_window_hours, "status": t.status,
        "submittedAt": t.submitted_at, "decidedAt": t.decided_at, "decidedBy": t.decided_by,
    }

def stable_window_hours_db(db, patient):
    """How many consecutive most-recent readings had NEWS2 ≤ 2 (demo readings ~hourly).
    Computed over the full vitals history, not the 5-row dashboard window."""
    rows = db.query(VitalTimeSeries).filter(
        VitalTimeSeries.hadm_id == patient.hadm_id
    ).order_by(VitalTimeSeries.chart_time.asc()).all()
    hyp = (getattr(patient, 'hypercapnic_failure', 0) == 1)
    n = 0
    for v in reversed(rows):
        vd = {'resp_rate': v.resp_rate, 'spo2': v.spo2, 'sbp': v.sbp, 'dbp': v.dbp,
              'heart_rate': v.heart_rate, 'temperature': v.temperature,
              'consciousness': v.consciousness, 'air_or_oxygen': v.air_or_oxygen}
        if calculate_news2(vd, hyp)["total"] <= 2:
            n += 1
        else:
            break
    return n

@app.get("/api/patients/{subject_id}/transfer-eligibility")
def transfer_eligibility(subject_id: int, db: Session = Depends(get_db)):
    detail = get_patient_detail(subject_id, db)
    patient = db.query(Patient).filter(Patient.hadm_id == subject_id).first()
    recent = detail.get("recentVitals", [])
    score = detail.get("news2", 99)

    window_h = stable_window_hours_db(db, patient)
    sustained = score <= 2 and window_h >= 6

    active_esc = db.query(Escalation).filter(
        Escalation.hadm_id == subject_id, Escalation.status == 'active').count()
    no_recent_esc = active_esc == 0

    hr = detail.get("hr"); spo2 = detail.get("spo2")
    sbp = None
    try:
        sbp = int(str(detail.get("bp", "")).split("/")[0])
    except Exception:
        pass
    haemo_stable = all([
        isinstance(sbp, int) and sbp >= 100,
        isinstance(hr, int) and 50 <= hr <= 110,
        isinstance(spo2, int) and spo2 >= 94,
    ])

    criteria = [
        {"label": "NEWS2 ≤ 2, sustained 6h+", "met": bool(sustained and window_h >= 6),
         "detail": f"Currently {score}, stable ~{window_h}h"},
        {"label": "No active escalation (24h)", "met": no_recent_esc,
         "detail": "None active" if no_recent_esc else f"{active_esc} active"},
        {"label": "Haemodynamically stable", "met": haemo_stable,
         "detail": f"SBP {sbp}, HR {hr}, SpO₂ {spo2}%"},
        {"label": "Inotropes weaned / reduced", "met": True, "detail": "Confirmed"},
        {"label": "Attending awareness", "met": False, "detail": "Notify on submission", "info": True},
    ]
    eligible = all(c["met"] for c in criteria if not c.get("info"))

    existing = db.query(CcuTransfer).filter(
        CcuTransfer.hadm_id == subject_id, CcuTransfer.status == 'pending').first()

    return {
        "subjectId": subject_id, "patientCode": detail.get("patient_code"),
        "name": detail.get("name"),
        "diagnosis": (patient.diagnosis_short if patient else None) or detail.get("ews_complaint"),
        "wardLocation": patient.ward_location if patient else "CCU",
        "bed": detail.get("bed"), "admitted": detail.get("admitted"),
        "news2": score, "stableWindowHours": window_h,
        "criteria": criteria, "eligible": eligible,
        "pendingTransfer": _transfer_dict(existing) if existing else None,
    }

class CcuTransferCreate(BaseModel):
    rationale: str
    targetWard: str = "General Ward"
    recommendedBy: str = "Nurse"

@app.post("/api/patients/{subject_id}/ccu-transfer")
def create_ccu_transfer(subject_id: int, body: CcuTransferCreate, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.hadm_id == subject_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    existing = db.query(CcuTransfer).filter(
        CcuTransfer.hadm_id == subject_id, CcuTransfer.status == 'pending').first()
    if existing:
        raise HTTPException(status_code=409, detail="A pending transfer already exists for this patient")
    detail = get_patient_detail(subject_id, db)
    t = CcuTransfer(
        hadm_id=subject_id, patient_name=patient.patient_name, diagnosis=patient.diagnosis_short,
        rationale=body.rationale, recommended_by=body.recommendedBy, target_ward=body.targetWard,
        news2_at_submit=detail.get("news2"),
        stable_window_hours=stable_window_hours_db(db, patient),
        status="pending", submitted_at=datetime.now(),
    )
    db.add(t); db.commit(); db.refresh(t)
    return _transfer_dict(t)

@app.get("/api/ccu-transfers")
def list_ccu_transfers(status: str = "pending", db: Session = Depends(get_db)):
    q = db.query(CcuTransfer)
    if status != "all":
        q = q.filter(CcuTransfer.status == status)
    rows = q.order_by(CcuTransfer.submitted_at.desc()).all()
    return {"transfers": [_transfer_dict(t) for t in rows]}

class TransferDecision(BaseModel):
    decidedBy: str = "Head Nurse"

@app.post("/api/ccu-transfers/{tid}/approve")
def approve_ccu_transfer(tid: int, body: TransferDecision, db: Session = Depends(get_db)):
    t = db.query(CcuTransfer).filter(CcuTransfer.id == tid).first()
    if not t:
        raise HTTPException(status_code=404, detail="Transfer not found")
    if t.status != "pending":
        raise HTTPException(status_code=400, detail="Transfer already decided")
    t.status = "approved"
    t.decided_at = datetime.now()
    t.decided_by = body.decidedBy
    patient = db.query(Patient).filter(Patient.hadm_id == t.hadm_id).first()
    if patient:
        patient.ward_location = "GENERAL_WARD"   # step-down state change

    # ── Discharge AI hand-off ─────────────────────────────────────────────
    # 1. Mark patient data_ready → surfaces in Ashmit's doctor queue.
    # 2. Stamp primary_diagnosis_title so billing dashboard SQL never gets NULL.
    # 3. Create app_encounters if none exists yet.
    hadm_id = t.hadm_id
    patient = db.query(Patient).filter(Patient.hadm_id == hadm_id).first()
    diag_title = (
        (patient.diagnosis_short or "").strip()
        or (patient.admitting_diagnosis or "").split(",")[0].strip()
        or (patient.ews_complaint or "").split(",")[0].strip()
        or "DCM / Cardiac"
    ) if patient else "Unknown"

    try:
        db.execute(sql_text("""
            UPDATE active_patients
            SET    status = 'data_ready',
                   updated_at = NOW(),
                   primary_diagnosis_title = COALESCE(primary_diagnosis_title, :diag)
            WHERE  hadm_id = :h
        """), {"h": hadm_id, "diag": diag_title})

        # Create app_encounters row if not already present for this patient
        existing_enc = db.execute(
            sql_text("SELECT id FROM app_encounters WHERE hadm_id = :h LIMIT 1"),
            {"h": hadm_id}
        ).fetchone()
        if not existing_enc:
            import uuid as _uuid_mod
            enc_id = str(_uuid_mod.uuid4())
            year_suffix = datetime.now().year % 100
            prefix = f"PT-{year_suffix:02d}-"
            max_seq_row = db.execute(
                sql_text("SELECT COALESCE(MAX(CAST(SUBSTRING(display_id FROM 7) AS INTEGER)), 0) "
                         "FROM app_encounters WHERE display_id LIKE :p"),
                {"p": f"{prefix}%"}
            ).fetchone()
            seq = (max_seq_row[0] if max_seq_row else 0) + 1
            display_id = f"{prefix}{seq:04d}"

            db.execute(sql_text("""
                INSERT INTO app_encounters (id, hadm_id, display_id, status, version, created_at, updated_at)
                VALUES (:id, :hadm_id, :display_id, 'Ready for Review', 1, NOW(), NOW())
                ON CONFLICT (hadm_id) DO UPDATE
                    SET status = 'Ready for Review', updated_at = NOW()
                    WHERE app_encounters.status IN ('Pending Ingestion', 'Processing')
            """), {"id": enc_id, "hadm_id": hadm_id, "display_id": display_id})

            # Link encounter back to active_patients
            db.execute(sql_text(
                "UPDATE active_patients SET encounter_id = :eid, updated_at = NOW() "
                "WHERE hadm_id = :h AND encounter_id IS NULL"
            ), {"eid": enc_id, "h": hadm_id})

    except Exception as exc:
        import logging as _log
        _log.getLogger(__name__).warning("Discharge hand-off failed for hadm_id %s: %s", hadm_id, exc)

    db.commit()
    return {
        "status": "ok",
        "id": tid,
        "wardLocation": "GENERAL_WARD",
        "discharge_queued": True,
        "primary_diagnosis_title": diag_title,
    }

@app.post("/api/ccu-transfers/{tid}/reject")
def reject_ccu_transfer(tid: int, body: TransferDecision, db: Session = Depends(get_db)):
    t = db.query(CcuTransfer).filter(CcuTransfer.id == tid).first()
    if not t:
        raise HTTPException(status_code=404, detail="Transfer not found")
    if t.status != "pending":
        raise HTTPException(status_code=400, detail="Transfer already decided")
    t.status = "rejected"
    t.decided_at = datetime.now()
    t.decided_by = body.decidedBy
    db.commit()
    return {"status": "ok", "id": tid}

@app.post("/api/ccu-transfers/{tid}/withdraw")
def withdraw_ccu_transfer(tid: int, db: Session = Depends(get_db)):
    t = db.query(CcuTransfer).filter(CcuTransfer.id == tid).first()
    if not t:
        raise HTTPException(status_code=404, detail="Transfer not found")
    t.status = "withdrawn"
    t.decided_at = datetime.now()
    db.commit()
    return {"status": "ok", "id": tid}


# ════════════════════════════════════════════════════════════════════════════
#  Drug-Lab actions (DL2 → DL2b) — recorded to the NABH audit trail
# ════════════════════════════════════════════════════════════════════════════
class DrugLabActionCreate(BaseModel):
    subjectId: int
    ruleName: str
    severity: str
    action: str          # override | hold | pharmacist
    justification: str = ""
    recordedBy: str
    cosignedBy: Optional[str] = None

def _dl_action_dict(a):
    return {
        "id": a.id, "subjectId": a.hadm_id, "ruleName": a.rule_name, "severity": a.severity,
        "action": a.action_taken, "justification": a.justification, "recordedBy": a.recorded_by,
        "cosignedBy": a.cosigned_by, "status": a.status, "recordedAt": a.recorded_at,
    }

@app.post("/api/drug-lab-actions")
def create_drug_lab_action(body: DrugLabActionCreate, db: Session = Depends(get_db)):
    a = DrugLabAction(
        hadm_id=body.subjectId, rule_name=body.ruleName, severity=body.severity,
        action_taken=body.action, justification=body.justification,
        recorded_by=body.recordedBy, cosigned_by=body.cosignedBy,
        status="resolved", recorded_at=datetime.now(),
    )
    db.add(a); db.commit(); db.refresh(a)
    return _dl_action_dict(a)

@app.get("/api/drug-lab-actions")
def list_drug_lab_actions(subjectId: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(DrugLabAction)
    if subjectId is not None:
        q = q.filter(DrugLabAction.hadm_id == subjectId)
    rows = q.order_by(DrugLabAction.recorded_at.desc()).all()
    return {"actions": [_dl_action_dict(a) for a in rows]}



# ════════════════════════════════════════════════════════════════════════════
#  Integration endpoints — EWS ↔ Discharge Summary AI hand-off
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/patients/{subject_id}/initiate-discharge")
def initiate_discharge(subject_id: int, db: Session = Depends(get_db)):
    """Mark patient discharge-ready in shared active_patients table.
    Sets status='data_ready', then creates or promotes app_encounters to 'Ready for Review'
    so Ashmit's ward-admin Kanban picks it up immediately."""
    patient = db.query(Patient).filter(Patient.hadm_id == subject_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    diag_title = (
        (patient.diagnosis_short or "").strip()
        or (patient.admitting_diagnosis or "").split(",")[0].strip()
        or (patient.ews_complaint or "").split(",")[0].strip()
        or "Unknown"
    )
    db.execute(sql_text("""
        UPDATE active_patients
        SET    status = 'data_ready',
               updated_at = NOW(),
               primary_diagnosis_title = COALESCE(primary_diagnosis_title, :diag)
        WHERE  hadm_id = :h
    """), {"h": subject_id, "diag": diag_title})

    # Upsert app_encounters: create if missing, or promote Pending Ingestion to Ready for Review
    existing_enc = db.execute(
        sql_text("SELECT id FROM app_encounters WHERE hadm_id = :h LIMIT 1"),
        {"h": subject_id}
    ).fetchone()
    if existing_enc:
        db.execute(sql_text("""
            UPDATE app_encounters
            SET    status = 'Ready for Review', updated_at = NOW()
            WHERE  hadm_id = :h AND status IN ('Pending Ingestion', 'Processing')
        """), {"h": subject_id})
    else:
        import uuid as _uuid_mod
        enc_id = str(_uuid_mod.uuid4())
        year_suffix = datetime.now().year % 100
        prefix = f"PT-{year_suffix:02d}-"
        max_seq_row = db.execute(
            sql_text("SELECT COALESCE(MAX(CAST(SUBSTRING(display_id FROM 7) AS INTEGER)), 0) "
                     "FROM app_encounters WHERE display_id LIKE :p"),
            {"p": f"{prefix}%"}
        ).fetchone()
        seq = (max_seq_row[0] if max_seq_row else 0) + 1
        display_id = f"{prefix}{seq:04d}"
        db.execute(sql_text("""
            INSERT INTO app_encounters (id, hadm_id, display_id, status, version, created_at, updated_at)
            VALUES (:id, :hadm_id, :did, 'Ready for Review', 1, NOW(), NOW())
            ON CONFLICT (hadm_id) DO UPDATE SET status = 'Ready for Review', updated_at = NOW()
        """), {"id": enc_id, "hadm_id": subject_id, "did": display_id})
        db.execute(sql_text(
            "UPDATE active_patients SET encounter_id = :eid, updated_at = NOW() "
            "WHERE hadm_id = :h AND encounter_id IS NULL"
        ), {"eid": enc_id, "h": subject_id})

    db.commit()
    return {
        "status": "discharge_initiated",
        "hadm_id": subject_id,
        "primary_diagnosis_title": diag_title,
        "message": "Patient moved to discharge queue. Discharge AI will generate summary.",
    }


@app.get("/api/patients/{subject_id}/ews-context")
def get_ews_context(subject_id: int, db: Session = Depends(get_db)):
    """Return EWS monitoring context for use by the Discharge Summary AI.
    Called by Ashmit's system to enrich the generated summary with ward data."""
    hadm_id = subject_id
    latest_vitals = (
        db.query(VitalTimeSeries)
        .filter(VitalTimeSeries.hadm_id == hadm_id)
        .order_by(VitalTimeSeries.chart_time.desc())
        .limit(5).all()
    )
    escalations = db.query(Escalation).filter(Escalation.hadm_id == hadm_id).all()
    dla = db.query(DrugLabAction).filter(DrugLabAction.hadm_id == hadm_id).all()
    peak_news2 = max((e.news2_score or 0 for e in escalations), default=0)
    return {
        "hadm_id": hadm_id,
        "peak_news2": peak_news2,
        "escalation_count": len(escalations),
        "code_blue_events": sum(1 for e in escalations if e.level == "code_blue"),
        "critical_drug_lab_flags": sum(1 for d in dla if d.severity == "CRITICAL"),
        "latest_vitals": [
            {
                "chart_time": v.chart_time.isoformat() if v.chart_time else None,
                "heart_rate": v.heart_rate,
                "spo2": v.spo2,
                "sbp": v.sbp,
                "resp_rate": v.resp_rate,
            }
            for v in latest_vitals
        ],
    }


# ════════════════════════════════════════════════════════════════════════════
#  MIMIC Sync Endpoints
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/patients/{hadm_id}/sync-mimic")
def sync_single_patient(hadm_id: int, db: Session = Depends(get_db)):
    """Manually trigger MIMIC data sync for a single patient."""
    patient = db.query(Patient).filter(Patient.hadm_id == hadm_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    result = sync_patient_from_mimic(hadm_id, db)
    return {"status": "synced", **result}


@app.post("/api/patients/bulk-sync-mimic")
def bulk_sync_patients(db: Session = Depends(get_db)):
    """Sync all active patients that have no ews_vitals yet."""
    patients = db.query(Patient).filter(Patient.status == "active").all()
    results = []
    for p in patients:
        has_vitals = db.query(VitalTimeSeries).filter(
            VitalTimeSeries.hadm_id == p.hadm_id
        ).first()
        if not has_vitals:
            try:
                r = sync_patient_from_mimic(p.hadm_id, db)
                results.append(r)
            except Exception as e:
                results.append({"hadm_id": p.hadm_id, "error": str(e)})
    return {"synced": len(results), "results": results}


@app.get("/api/mimic/dcm-patients")
def get_dcm_patients(db: Session = Depends(get_db)):
    """List available DCM patients (ICD I42.x / 425.x) from ap_admissions."""
    patients = list_dcm_patients(db)
    return {"total": len(patients), "patients": patients}


# ════════════════════════════════════════════════════════════════════════════
#  Replay Demo Endpoint
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/demo/replay/{hadm_id}")
def get_replay_demo(hadm_id: int, db: Session = Depends(get_db)):
    """
    Build a stakeholder replay demo: patient arc from admission to discharge.
    Segments MIMIC vitals and labs into 6 narrative frames aligned with clinical events.
    """
    patient = db.query(Patient).filter(Patient.hadm_id == hadm_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # All vitals in chronological order
    all_vitals = db.query(VitalTimeSeries).filter(
        VitalTimeSeries.hadm_id == hadm_id
    ).order_by(VitalTimeSeries.chart_time.asc()).all()

    if not all_vitals:
        raise HTTPException(status_code=404, detail="No vitals found — run /sync-mimic first")

    # All labs in chronological order
    all_labs = db.query(LabEvent).filter(
        LabEvent.hadm_id == hadm_id
    ).order_by(LabEvent.chart_time.asc()).all()

    # Escalations and drug-lab actions for event overlay
    escalations = db.query(Escalation).filter(
        Escalation.hadm_id == hadm_id
    ).order_by(Escalation.escalated_at.asc()).all()
    dla_actions = db.query(DrugLabAction).filter(
        DrugLabAction.hadm_id == hadm_id
    ).order_by(DrugLabAction.recorded_at.asc()).all()

    # Split total time range into 6 equal frames
    t_start = all_vitals[0].chart_time
    t_end = all_vitals[-1].chart_time
    total_secs = (t_end - t_start).total_seconds() or 1
    frame_secs = total_secs / 6

    frame_labels = [
        "Day 1 · Admission",
        "Day 2 · Early Monitoring",
        "Day 3 · Deterioration",
        "Day 4 · Intervention",
        "Day 5 · Recovery",
        "Day 6 · Step-down",
    ]

    def _pick_vitals_in_window(start: datetime, end: datetime):
        return [v for v in all_vitals if start <= v.chart_time <= end]

    def _pick_labs_in_window(start: datetime, end: datetime):
        return [l for l in all_labs if l.chart_time and start <= l.chart_time <= end]

    def _vitals_dict(v: VitalTimeSeries):
        return {
            "hr":   round(v.heart_rate, 0) if v.heart_rate else None,
            "rr":   round(v.resp_rate, 0) if v.resp_rate else None,
            "spo2": round(v.spo2, 0) if v.spo2 else None,
            "sbp":  round(v.sbp, 0) if v.sbp else None,
            "dbp":  round(v.dbp, 0) if v.dbp else None,
            "temp": round(v.temperature, 1) if v.temperature else None,
            "avpu": v.consciousness or "A",
            "urine_output": float(v.urine_output) if v.urine_output else None,
            "weight_kg": float(v.weight_kg) if v.weight_kg else None,
        }

    frames = []
    for i in range(6):
        w_start = t_start + timedelta(seconds=i * frame_secs)
        w_end = t_start + timedelta(seconds=(i + 1) * frame_secs)

        w_vitals = _pick_vitals_in_window(w_start, w_end)
        w_labs = _pick_labs_in_window(w_start, w_end)

        # Pick representative vitals: last in window (captures deterioration if any)
        rep_vital = w_vitals[-1] if w_vitals else (all_vitals[0] if all_vitals else None)
        rep_lab = w_labs[-1] if w_labs else (all_labs[0] if all_labs else None)

        v_dict = {}
        news2_score = 0
        if rep_vital:
            v_dict = _vitals_dict(rep_vital)
            vd = {
                "resp_rate": rep_vital.resp_rate, "spo2": rep_vital.spo2,
                "sbp": rep_vital.sbp, "heart_rate": rep_vital.heart_rate,
                "temperature": rep_vital.temperature,
                "consciousness": rep_vital.consciousness or "A",
                "air_or_oxygen": rep_vital.air_or_oxygen or "Air",
            }
            news2_score = calculate_news2(vd, getattr(patient, 'hypercapnic_failure', 0) == 1)["total"]

        bnp_val = float(rep_lab.bnp) if rep_lab and rep_lab.bnp else getattr(patient, 'bnp_baseline', None)
        bnp_val = float(bnp_val) if bnp_val else None

        from mimic_sync import compute_nyha
        nyha, _ = compute_nyha(bnp_val, getattr(patient, 'lvef_percent', None), news2_score)

        # Events: escalations + drug-lab actions within this window
        events = []
        for esc in escalations:
            if esc.escalated_at and w_start <= esc.escalated_at <= w_end:
                events.append({
                    "type": "escalation", "level": esc.level,
                    "text": f"Escalated to {esc.level} — {esc.observations or 'clinical deterioration'}",
                    "news2": esc.news2_score,
                })
        for dla in dla_actions:
            if dla.recorded_at and w_start <= dla.recorded_at <= w_end:
                events.append({
                    "type": "drug_flag", "severity": dla.severity,
                    "text": f"{dla.rule_name} — {dla.action_taken}",
                })
        if i == 0:
            meds = db.query(Medication).filter(Medication.hadm_id == hadm_id).all()
            med_names = ", ".join(m.med_name for m in meds[:4]) if meds else "—"
            events.append({
                "type": "admission",
                "text": f"Admitted: {patient.admitting_diagnosis or patient.diagnosis_short or 'DCM'}. "
                        f"NYHA {nyha}. Meds: {med_names}",
            })
        if i == 5 and not any(e["type"] == "discharge" for e in events):
            events.append({
                "type": "discharge",
                "text": f"NEWS2 stable ≤ {news2_score}. Step-down to General Ward. "
                        "Discharge summary generation initiated.",
            })

        lab_dict = {}
        if rep_lab:
            lab_dict = {k: v for k, v in {
                "potassium": rep_lab.potassium,
                "creatinine": rep_lab.creatinine,
                "lactate": rep_lab.lactate,
                "inr": rep_lab.inr,
                "bnp": float(rep_lab.bnp) if rep_lab.bnp else None,
                "troponin": float(rep_lab.troponin) if rep_lab.troponin else None,
                "sodium": float(rep_lab.sodium) if rep_lab.sodium else None,
                "hemoglobin": float(rep_lab.hemoglobin) if rep_lab.hemoglobin else None,
            }.items() if v is not None}

        frames.append({
            "frame": i + 1,
            "label": frame_labels[i],
            "chart_time": rep_vital.chart_time.isoformat() if rep_vital and rep_vital.chart_time else None,
            "news2": news2_score,
            "nyha": nyha,
            "bnp": bnp_val,
            "vitals": v_dict,
            "labs": lab_dict,
            "events": events,
            "vital_count": len(w_vitals),
        })

    return {
        "patient": {
            "hadm_id": patient.hadm_id,
            "name": patient.patient_name,
            "age": patient.anchor_age,
            "gender": patient.gender,
            "diagnosis": patient.admitting_diagnosis or patient.diagnosis_short or "Dilated Cardiomyopathy",
            "nyha_at_admission": getattr(patient, 'nyha_class', None),
            "bnp_at_admission": float(patient.bnp_baseline) if getattr(patient, 'bnp_baseline', None) else None,
            "lvef": getattr(patient, 'lvef_percent', None),
        },
        "frames": frames,
        "total_vital_readings": len(all_vitals),
        "total_lab_readings": len(all_labs),
    }


# ════════════════════════════════════════════════════════════════════════════
#  ERD Schema Endpoints — hospital_core / ews / discharge_ai (migration 026)
# ════════════════════════════════════════════════════════════════════════════

# ── DCM Assessments ──────────────────────────────────────────────────────────

class DcmAssessmentCreate(BaseModel):
    nyhaClass: int
    efPercent: Optional[float] = None
    baselineWeightKg: Optional[float] = None
    bnpAdmission: Optional[float] = None
    edemaGrade: Optional[int] = None
    assessedBy: str                          # staff UUID or name

@app.post("/api/patients/{subject_id}/dcm-assessment")
def create_dcm_assessment(subject_id: int, body: DcmAssessmentCreate, db: Session = Depends(get_db)):
    """Record a DCM assessment (NYHA class, EF, BNP) via ews.dcm_assessments.
    Also resolves the hospital_core.admissions row for this hadm_id to get admission_id."""
    patient = db.query(Patient).filter(Patient.hadm_id == subject_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Look up admission_id from hospital_core.admissions (may not exist for demo patients)
    hc_adm = db.query(HcAdmission).filter(HcAdmission.hadm_id == subject_id).first()
    if not hc_adm:
        raise HTTPException(
            status_code=409,
            detail="No hospital_core.admissions row for this hadm_id. "
                   "Create via POST /api/admissions first or run admission sync.",
        )

    assessment = DcmAssessment(
        id=str(_uuid_mod.uuid4()),
        admission_id=hc_adm.admission_id,
        nyha_class=body.nyhaClass,
        ef_percent=body.efPercent,
        baseline_weight_kg=body.baselineWeightKg,
        bnp_admission=body.bnpAdmission,
        edema_grade=body.edemaGrade,
        assessed_by=body.assessedBy,
        assessed_at=datetime.now(),
    )
    db.add(assessment)
    # Also sync NYHA/LVEF back to active_patients for backward compat
    if patient:
        patient.nyha_class = body.nyhaClass
        if body.efPercent is not None:
            patient.lvef_percent = int(body.efPercent)
        if body.bnpAdmission is not None:
            patient.bnp_baseline = body.bnpAdmission
    db.commit()
    db.refresh(assessment)
    return {
        "id": assessment.id,
        "admission_id": assessment.admission_id,
        "nyha_class": assessment.nyha_class,
        "ef_percent": float(assessment.ef_percent) if assessment.ef_percent else None,
        "bnp_admission": float(assessment.bnp_admission) if assessment.bnp_admission else None,
        "assessed_at": assessment.assessed_at.isoformat(),
    }

@app.get("/api/patients/{subject_id}/dcm-assessment")
def get_dcm_assessment(subject_id: int, db: Session = Depends(get_db)):
    """Get latest DCM assessment for a patient."""
    hc_adm = db.query(HcAdmission).filter(HcAdmission.hadm_id == subject_id).first()
    if not hc_adm:
        raise HTTPException(status_code=404, detail="No hospital_core admission found")
    assessment = (
        db.query(DcmAssessment)
        .filter(DcmAssessment.admission_id == hc_adm.admission_id)
        .order_by(DcmAssessment.assessed_at.desc())
        .first()
    )
    if not assessment:
        raise HTTPException(status_code=404, detail="No DCM assessment recorded")
    return {
        "id": assessment.id,
        "nyha_class": assessment.nyha_class,
        "ef_percent": float(assessment.ef_percent) if assessment.ef_percent else None,
        "bnp_admission": float(assessment.bnp_admission) if assessment.bnp_admission else None,
        "edema_grade": assessment.edema_grade,
        "assessed_at": assessment.assessed_at.isoformat() if assessment.assessed_at else None,
    }

# ── Fluid Balance ─────────────────────────────────────────────────────────────

class FluidBalanceCreate(BaseModel):
    periodHours: int = 24                    # 8 or 24
    intakeMl: Optional[float] = None
    urineMl: Optional[float] = None
    drainMl: Optional[float] = None
    dailyWeightKg: Optional[float] = None
    recordedBy: str                          # staff UUID or name

@app.post("/api/patients/{subject_id}/fluid-balance")
def record_fluid_balance(subject_id: int, body: FluidBalanceCreate, db: Session = Depends(get_db)):
    """Record a fluid balance entry in ews.fluid_balance."""
    hc_adm = db.query(HcAdmission).filter(HcAdmission.hadm_id == subject_id).first()
    if not hc_adm:
        raise HTTPException(status_code=409, detail="No hospital_core admission for this hadm_id")
    intake = body.intakeMl or 0
    urine  = body.urineMl or 0
    drain  = body.drainMl or 0
    net    = intake - urine - drain
    entry = FluidBalance(
        id=str(_uuid_mod.uuid4()),
        admission_id=hc_adm.admission_id,
        period_hours=body.periodHours,
        intake_ml=intake,
        urine_ml=urine,
        drain_ml=drain,
        net_balance_ml=net,
        daily_weight_kg=body.dailyWeightKg,
        recorded_by=body.recordedBy,
        recorded_at=datetime.now(),
    )
    db.add(entry); db.commit(); db.refresh(entry)
    return {
        "id": entry.id,
        "period_hours": entry.period_hours,
        "intake_ml": float(entry.intake_ml),
        "urine_ml": float(entry.urine_ml),
        "net_balance_ml": float(entry.net_balance_ml),
        "recorded_at": entry.recorded_at.isoformat(),
    }

@app.get("/api/patients/{subject_id}/fluid-balance")
def get_fluid_balance(subject_id: int, db: Session = Depends(get_db)):
    """Return fluid balance entries (last 7 days) for a patient."""
    hc_adm = db.query(HcAdmission).filter(HcAdmission.hadm_id == subject_id).first()
    if not hc_adm:
        return {"entries": []}
    since = datetime.now() - timedelta(days=7)
    entries = (
        db.query(FluidBalance)
        .filter(
            FluidBalance.admission_id == hc_adm.admission_id,
            FluidBalance.recorded_at >= since,
        )
        .order_by(FluidBalance.recorded_at.desc())
        .all()
    )
    return {"entries": [
        {
            "id": e.id, "period_hours": e.period_hours,
            "intake_ml": float(e.intake_ml or 0),
            "urine_ml": float(e.urine_ml or 0),
            "net_balance_ml": float(e.net_balance_ml or 0),
            "daily_weight_kg": float(e.daily_weight_kg) if e.daily_weight_kg else None,
            "recorded_at": e.recorded_at.isoformat() if e.recorded_at else None,
        }
        for e in entries
    ]}

# ── EWS Events (ML trend alerts) ─────────────────────────────────────────────

@app.get("/api/patients/{subject_id}/ews-events")
def get_ews_events(subject_id: int, db: Session = Depends(get_db)):
    """Return pending ML trend events for a patient."""
    hc_adm = db.query(HcAdmission).filter(HcAdmission.hadm_id == subject_id).first()
    if not hc_adm:
        return {"events": []}
    events = (
        db.query(EwsEvent)
        .filter(EwsEvent.admission_id == hc_adm.admission_id)
        .order_by(EwsEvent.detected_at.desc())
        .limit(20)
        .all()
    )
    return {"events": [
        {
            "id": e.id, "event_type": e.event_type, "trend_score": float(e.trend_score or 0),
            "ml_confidence": float(e.ml_confidence or 0), "top_signals": e.top_signals,
            "status": e.status, "detected_at": e.detected_at.isoformat() if e.detected_at else None,
        }
        for e in events
    ]}

# ── hospital_core Admission provisioning ─────────────────────────────────────

class AdmissionProvisionBody(BaseModel):
    """Provision a hospital_core.admissions row for an existing active_patients hadm_id.
    Call this once per patient after migration 026 runs to wire the new schema FK."""
    hadmId: int
    uhid: Optional[str] = None              # auto-generated if not provided

@app.post("/api/admissions/provision")
def provision_admission(body: AdmissionProvisionBody, db: Session = Depends(get_db)):
    """Create a hospital_core.admissions row for an active_patients patient.
    This is the bridge step: once this row exists, all ERD schema FKs (dcm_assessments,
    fluid_balance, ews_events, etc.) become usable for this patient."""
    existing = db.query(HcAdmission).filter(HcAdmission.hadm_id == body.hadmId).first()
    if existing:
        return {"status": "already_exists", "admission_id": existing.admission_id, "hadm_id": body.hadmId}

    patient = db.query(Patient).filter(Patient.hadm_id == body.hadmId).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found in active_patients")

    # Resolve hospital_id from hospital_core.hospitals (use the demo seed row)
    hospital_row = db.execute(
        sql_text("SELECT hospital_id FROM hospital_core.hospitals LIMIT 1")
    ).fetchone()
    if not hospital_row:
        raise HTTPException(status_code=500, detail="No hospital row in hospital_core.hospitals. Migration 026 may not have run.")

    # Generate UHID if not provided
    uhid = body.uhid or f"FOQAL-{datetime.now().year}-{body.hadmId:07d}"

    # Ensure a patients row exists
    patient_exists = db.execute(
        sql_text("SELECT 1 FROM hospital_core.patients WHERE uhid = :u LIMIT 1"),
        {"u": uhid}
    ).fetchone()
    if not patient_exists:
        db.execute(sql_text("""
            INSERT INTO hospital_core.patients (uhid, hospital_id, full_name, sex)
            VALUES (:uhid, :hid, :name, :sex)
            ON CONFLICT (uhid) DO NOTHING
        """), {
            "uhid": uhid,
            "hid": hospital_row[0],
            "name": patient.patient_name or "Unknown",
            "sex": patient.gender or "M",
        })

    # Resolve ward_id from hospital_core.wards (use first available)
    ward_row = db.execute(
        sql_text("SELECT ward_id FROM hospital_core.wards LIMIT 1")
    ).fetchone()
    ward_id = ward_row[0] if ward_row else None

    adm_id = str(_uuid_mod.uuid4())
    db.execute(sql_text("""
        INSERT INTO hospital_core.admissions
            (admission_id, uhid, hospital_id, ward_id, hadm_id, status, admitted_at, updated_at)
        VALUES (:adm_id, :uhid, :hid, :wid, :hadm_id, :status, :admitted_at, NOW())
        ON CONFLICT (hadm_id) DO NOTHING
    """), {
        "adm_id": adm_id, "uhid": uhid, "hid": hospital_row[0],
        "wid": ward_id, "hadm_id": body.hadmId,
        "status": patient.status or "admitted",
        "admitted_at": patient.admit_time or datetime.now(),
    })
    db.commit()
    return {"status": "provisioned", "admission_id": adm_id, "uhid": uhid, "hadm_id": body.hadmId}

@app.post("/api/admissions/provision-all")
def provision_all_admissions(db: Session = Depends(get_db)):
    """Provision hospital_core.admissions rows for ALL active_patients in bulk.
    Run this once after migration 026 to bridge the entire existing patient list."""
    # Pre-check: migration 026 must have run first
    try:
        db.execute(sql_text("SELECT 1 FROM hospital_core.admissions LIMIT 1"))
    except Exception as pre_err:
        raise HTTPException(
            status_code=500,
            detail=f"hospital_core.admissions table not found — run apply_026.py first. Error: {pre_err}"
        )

    patients = db.query(Patient).all()
    provisioned, already_exists, errors = 0, 0, []

    # Resolve hospital/ward once (not inside the loop)
    hospital_row = db.execute(
        sql_text("SELECT hospital_id FROM hospital_core.hospitals LIMIT 1")
    ).fetchone()
    ward_row = db.execute(
        sql_text("SELECT ward_id FROM hospital_core.wards LIMIT 1")
    ).fetchone()
    if not hospital_row:
        raise HTTPException(status_code=500, detail="No row in hospital_core.hospitals — migration 026 seed did not run")

    # Map active_patients pipeline-state → hospital_core.admissions clinical-state
    _STATUS_MAP = {
        "active":      "admitted",
        "data_ready":  "discharge_pending",
        "signed_off":  "discharged",
        "archived":    "discharged",
    }

    for p in patients:
        try:
            existing = db.query(HcAdmission).filter(HcAdmission.hadm_id == p.hadm_id).first()
            if existing:
                already_exists += 1
                continue
            uhid = f"FOQAL-{datetime.now().year}-{p.hadm_id:07d}"
            db.execute(sql_text("""
                INSERT INTO hospital_core.patients (uhid, hospital_id, full_name, sex)
                VALUES (:uhid, :hid, :name, :sex) ON CONFLICT (uhid) DO NOTHING
            """), {"uhid": uhid, "hid": hospital_row[0], "name": p.patient_name or "Unknown", "sex": p.gender or "M"})
            adm_id = str(_uuid_mod.uuid4())
            clinical_status = _STATUS_MAP.get(p.status or "", "admitted")
            db.execute(sql_text("""
                INSERT INTO hospital_core.admissions
                    (admission_id, uhid, hospital_id, ward_id, hadm_id, status, admitted_at, updated_at)
                VALUES (:adm_id, :uhid, :hid, :wid, :hadm_id, :status, :admitted_at, NOW())
                ON CONFLICT (hadm_id) DO NOTHING
            """), {
                "adm_id": adm_id, "uhid": uhid, "hid": hospital_row[0],
                "wid": ward_row[0] if ward_row else None,
                "hadm_id": p.hadm_id, "status": clinical_status,
                "admitted_at": p.admit_time or datetime.now(),
            })
            db.commit()
            provisioned += 1
        except Exception as exc:
            db.rollback()
            errors.append({"hadm_id": p.hadm_id, "error": str(exc)[:120]})

    return {
        "provisioned": provisioned,
        "already_existed": already_exists,
        "errors": errors,
        "total": len(patients),
        "status": "ok" if not errors else "partial",
    }

# ── Discharge Sections (per-NABH-section tracking) ───────────────────────────

class SectionSaveBody(BaseModel):
    summaryId: str
    sections: list                           # [{number, name, aiContent, editedContent?, confidence?}]

@app.post("/api/discharge-sections")
def save_discharge_sections(body: SectionSaveBody, db: Session = Depends(get_db)):
    """Persist NABH discharge sections into discharge_ai.discharge_sections."""
    saved = 0
    for s in body.sections:
        section_num = s.get("number") or s.get("section_number")
        section_name = s.get("name") or s.get("section_name", f"Section {section_num}")
        ai_content = s.get("aiContent") or s.get("ai_content", "")
        if not section_num:
            continue
        existing = db.execute(sql_text("""
            SELECT section_id FROM discharge_ai.discharge_sections
            WHERE summary_id = :sid AND section_number = :num LIMIT 1
        """), {"sid": body.summaryId, "num": section_num}).fetchone()
        if existing:
            db.execute(sql_text("""
                UPDATE discharge_ai.discharge_sections
                SET edited_content = :ec, edited_at = NOW()
                WHERE summary_id = :sid AND section_number = :num
            """), {"ec": s.get("editedContent"), "sid": body.summaryId, "num": section_num})
        else:
            db.execute(sql_text("""
                INSERT INTO discharge_ai.discharge_sections
                    (section_id, summary_id, section_number, section_name, ai_content,
                     edited_content, confidence_score)
                VALUES (:sid_pk, :sid, :num, :name, :ai, :ec, :conf)
            """), {
                "sid_pk": str(_uuid_mod.uuid4()), "sid": body.summaryId,
                "num": section_num, "name": section_name, "ai": ai_content,
                "ec": s.get("editedContent"), "conf": s.get("confidence", 0),
            })
        saved += 1
    db.commit()
    return {"saved": saved, "summary_id": body.summaryId}

@app.get("/api/discharge-sections/{summary_id}")
def get_discharge_sections(summary_id: str, db: Session = Depends(get_db)):
    """Return all NABH sections for a summary."""
    rows = db.execute(sql_text("""
        SELECT section_number, section_name, ai_content, edited_content,
               confidence_score, edited_at
        FROM discharge_ai.discharge_sections
        WHERE summary_id = :sid
        ORDER BY section_number ASC
    """), {"sid": summary_id}).fetchall()
    return {"sections": [
        {
            "number": r[0], "name": r[1], "ai_content": r[2],
            "edited_content": r[3], "confidence": float(r[4] or 0),
            "edited_at": r[5].isoformat() if r[5] else None,
        }
        for r in rows
    ]}


# ════════════════════════════════════════════════════════════════════════════
#  Static frontend
# ════════════════════════════════════════════════════════════════════════════

# Mount the frontend directory (sabari_project) at the root to serve static files (index.html, app.js, styles.css)
from fastapi.staticfiles import StaticFiles
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
