import math
import os
import threading
import yaml
from collections import defaultdict
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import SessionLocal, init_db
from models import Patient, VitalTimeSeries, LabEvent, Medication, Escalation, CcuTransfer, DrugLabAction
from engine.drug_lab import check_patient_against_rules
from mimic_sync import sync_patient_from_mimic, list_dcm_patients
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import random

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

# EscalationCreate is defined below at the proper location (line ~284) with full field defaults.
# Duplicate class removed — Python would silently override with the second definition anyway.

def is_valid(val):
    """Return True if the value is a real, non-null, non-NaN numeric reading.
    NOTE: We intentionally do NOT reject val==0 here — zero is physiologically
    possible (e.g. urine output=0) and blocking it silently drops real readings.
    Per-column range guards are applied at the NEWS2 calculation level instead."""
    if val is None:
        return False
    if isinstance(val, (float, int)) and math.isnan(val):
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

def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
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
    # BUG-05 FIX: Default is empty string — frontend must always send the real
    # logged-in nurse name. "Nurse Rekha Devi" was a hardcoded demo placeholder
    # that would pollute the NABH audit trail with a fake name.
    escalatedBy: str = ""

class EscalationResolve(BaseModel):
    resolvedBy: str
    notes: str

@app.post("/api/patients")
def add_patient(patient: PatientCreate, db: Session = Depends(get_db)):
    max_row = db.query(Patient).order_by(Patient.hadm_id.desc()).first()
    new_id = (max_row.hadm_id + 1) if max_row else 10100

    year_suffix = datetime.now().year % 100
    new_patient = Patient(
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

    import uuid
    from sqlalchemy import text as sql_text

    # 1. Fetch or provision FOQAL-DEMO hospital
    h_row = db.execute(sql_text("SELECT hospital_id FROM hospital_core.hospitals WHERE short_code = 'FOQAL-DEMO'")).fetchone()
    if not h_row:
        hospital_id = str(uuid.uuid4())
        db.execute(sql_text("""
            INSERT INTO hospital_core.hospitals (hospital_id, short_code, name, type, nabh_accredited)
            VALUES (:id, 'FOQAL-DEMO', 'Foqal CareOS Demo Hospital', 'PRIVATE', TRUE)
        """), {"id": hospital_id})
    else:
        hospital_id = h_row[0]

    # 2. Fetch or provision ward
    w_row = db.execute(sql_text("SELECT ward_id FROM hospital_core.wards WHERE name = :name"), {"name": patient.ward}).fetchone()
    if not w_row:
        # Get cardiology department
        d_row = db.execute(sql_text("SELECT dept_id FROM hospital_core.departments WHERE code = 'CARD' LIMIT 1")).fetchone()
        if d_row:
            dept_id = d_row[0]
        else:
            dept_id = str(uuid.uuid4())
            db.execute(sql_text("""
                INSERT INTO hospital_core.departments (dept_id, hospital_id, name, code)
                VALUES (:did, :hid, 'Cardiology', 'CARD')
            """), {"did": dept_id, "hid": hospital_id})
        
        ward_id = str(uuid.uuid4())
        db.execute(sql_text("""
            INSERT INTO hospital_core.wards (ward_id, hospital_id, dept_id, name, ward_type)
            VALUES (:wid, :hid, :did, :name, 'GW')
        """), {"wid": ward_id, "hid": hospital_id, "did": dept_id, "name": patient.ward})
    else:
        ward_id = w_row[0]

    # 3. Create or get patient in hospital_core.patients
    uhid = f"FOQAL-{datetime.now().year}-{new_id:07d}"
    sex_char = (patient.sex or "M")[0].upper()
    if sex_char not in ('M', 'F', 'O'):
        sex_char = 'M'
    
    db.execute(sql_text("""
        INSERT INTO hospital_core.patients (uhid, hospital_id, full_name, sex, insurance_type)
        VALUES (:uhid, :hid, :name, :sex, 'None')
        ON CONFLICT (uhid) DO NOTHING
    """), {"uhid": uhid, "hid": hospital_id, "name": patient.name, "sex": sex_char})

    # 4. Create admission bridge
    admission_id = str(uuid.uuid4())
    db.execute(sql_text("""
        INSERT INTO hospital_core.admissions (admission_id, uhid, hospital_id, ward_id, hadm_id, status, admitted_at)
        VALUES (:aid, :uhid, :hid, :wid, :hadm, 'admitted', NOW())
        ON CONFLICT (hadm_id) DO NOTHING
    """), {"aid": admission_id, "uhid": uhid, "hid": hospital_id, "wid": ward_id, "hadm": new_id})

    # Find admission_id if skipped due to conflict
    actual_aid_row = db.execute(sql_text("SELECT admission_id FROM hospital_core.admissions WHERE hadm_id = :hadm"), {"hadm": new_id}).fetchone()
    if actual_aid_row:
        admission_id = actual_aid_row[0]

    # 5. Create app_encounter
    encounter_id = str(uuid.uuid4())
    year = datetime.now().year
    prefix = f"PT-{year % 100:02d}-"
    seq_row = db.execute(sql_text("""
        SELECT COALESCE(MAX(CAST(SUBSTRING(display_id FROM 7) AS INTEGER)), 0)
        FROM app_encounters WHERE display_id LIKE :p
    """), {"p": f"{prefix}%"}).fetchone()
    seq = (seq_row[0] if seq_row else 0) + 1
    display_id = f"{prefix}{seq:04d}"

    db.execute(sql_text("""
        INSERT INTO app_encounters (id, hadm_id, status, display_id, created_at, updated_at)
        VALUES (:eid, :hadm, 'Pending Ingestion', :did, NOW(), NOW())
        ON CONFLICT (hadm_id) DO NOTHING
    """), {"eid": encounter_id, "hadm": new_id, "did": display_id})

    actual_eid_row = db.execute(sql_text("SELECT id FROM app_encounters WHERE hadm_id = :hadm"), {"hadm": new_id}).fetchone()
    if actual_eid_row:
        encounter_id = actual_eid_row[0]

    db.commit()

    return {
        "message": "Patient added",
        "subject_id": new_id,
        "encounter_id": str(encounter_id),
        "admission_id": str(admission_id)
    }

REPLAY_OFFSET = 0

# ── Ward-data response cache — avoids 4× Cloud SQL round-trips on every poll ──
import time as _time
_ward_cache: dict = {}          # key: (ward, location) → {"ts": float, "data": dict}
_WARD_CACHE_TTL = 45            # seconds; raised from 20s — Cloud SQL round-trips are expensive

def _invalidate_ward_cache(ward: str):
    """Invalidates cache for a specific ward and the 'All' ward to prevent data leaks/performance drops."""
    keys_to_remove = [k for k in _ward_cache.keys() if k[0] in ("All", ward)]
    for k in keys_to_remove:
        _ward_cache.pop(k, None)

@app.get("/api/ward-data")
def get_ward_data(ward: str = "All", location: str = "All", replay: bool = False,
                  hadm_id: Optional[int] = None, db: Session = Depends(get_db)):
    global REPLAY_OFFSET
    if replay:
        REPLAY_OFFSET = (REPLAY_OFFSET + 1) % 20

    # Return cached result if fresh and not a single-patient lookup or replay
    _cache_key = (ward, location)
    if not replay and hadm_id is None:
        _cached = _ward_cache.get(_cache_key)
        if _cached and (_time.time() - _cached["ts"]) < _WARD_CACHE_TTL:
            return _cached["data"]
        # Derive location-filtered views from a fresh "All" cache so each role's
        # first screen (CCU / GENERAL_WARD / charge) doesn't pay its own cold
        # Cloud SQL pipeline — one warm "All" entry serves every location.
        if ward == "All" and location != "All":
            _all = _ward_cache.get(("All", "All"))
            if _all and (_time.time() - _all["ts"]) < _WARD_CACHE_TTL:
                if location == "CCU":
                    _pts = [p for p in _all["data"]["patients"]
                            if p.get("ward_location") in (None, "CCU")]
                else:
                    _pts = [p for p in _all["data"]["patients"]
                            if p.get("ward_location") == location]
                _derived = {"patients": _pts, "ward": ward}
                _ward_cache[_cache_key] = {"ts": _all["ts"], "data": _derived}
                return _derived

    q = db.query(Patient).filter(Patient.status.notin_(["signed_off", "archived"]))
    if ward != "All":
        q = q.filter(Patient.ward == ward)
    if location != "All":
        if location == "CCU":
            # NULL ward_location defaults to CCU (existing patients before billing provisioning)
            q = q.filter((Patient.ward_location == "CCU") | (Patient.ward_location == None))
        else:
            q = q.filter(Patient.ward_location == location)
    if hadm_id is not None:
        q = q.filter(Patient.hadm_id == hadm_id)
    patients = q.all()

    if not patients:
        return {"patients": [], "ward": ward}

    patient_ids = [p.hadm_id for p in patients]

    from sqlalchemy import func

    # Bulk-fetch vitals/labs/meds in 3 queries instead of 3×N Cloud SQL round-trips
    demo_now = db.query(func.max(VitalTimeSeries.chart_time)).scalar() or datetime.now()

    # LIMIT prevents pulling thousands of MIMIC ICU rows per patient.
    # 96 = 24 readings × 4 patients safety factor — well above dashboard needs (6 readings).
    # Using a raw SQL window query so the LIMIT applies per hadm_id, not globally.
    from sqlalchemy import text as _vt
    _vrows_raw = db.execute(_vt("""
        SELECT id, hadm_id, chart_time, heart_rate, resp_rate, spo2, sbp, dbp,
               temperature, consciousness, air_or_oxygen, urine_output, fluid_balance, weight_kg
        FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY hadm_id ORDER BY chart_time DESC) AS rn
            FROM ews_vitals_timeseries
            WHERE hadm_id = ANY(:ids)
        ) sub
        WHERE rn <= 96
        ORDER BY hadm_id, chart_time DESC
    """), {"ids": patient_ids}).fetchall()
    # Re-hydrate as ORM-like objects using a simple namespace wrapper
    class _VRow:
        __slots__ = ('hadm_id','chart_time','heart_rate','resp_rate','spo2','sbp','dbp',
                     'temperature','consciousness','air_or_oxygen','urine_output','fluid_balance','weight_kg')
        def __init__(self, r):
            self.hadm_id=r[1]; self.chart_time=r[2]; self.heart_rate=r[3]; self.resp_rate=r[4]
            self.spo2=r[5]; self.sbp=r[6]; self.dbp=r[7]; self.temperature=r[8]
            self.consciousness=r[9]; self.air_or_oxygen=r[10]; self.urine_output=r[11]
            self.fluid_balance=r[12]; self.weight_kg=r[13]
    _vrows = [_VRow(r) for r in _vrows_raw]
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

        _p_location = getattr(p, 'ward_location', None) or 'CCU'
        _fetch_status = getattr(p, 'data_fetch_status', 'fetched') or 'fetched'

        # While billing's prefetch-all or vitals sync is running, show as "loading"
        if _fetch_status in ('pending', 'fetching', 'partial'):
            result.append({
                "id": str(p.hadm_id),
                "name": getattr(p, 'patient_name', None) or getattr(p, 'name', 'Unknown'),
                "age": getattr(p, 'anchor_age', '--'),
                "gender": getattr(p, 'gender', '--'),
                "ward": getattr(p, 'ward', '--') or '--',
                "room": getattr(p, 'room', '--') or '--',
                "bed": getattr(p, 'bed', '--') or '--',
                "admit_time": p.admit_time.strftime("%Y-%m-%d %H:%M") if getattr(p, 'admit_time', None) else '--',
                "ward_location": _p_location,
                "status": "loading",
                "news2": "--",
                "trajectory": [],
                "vitals_history": [],
                "due_label": "Syncing data…",
                "monitoring_interval": "--",
                "vitals": {},
                "monitoring": {},
                "alerts": [],
                "primary_diagnosis": getattr(p, 'primary_diagnosis_title', '') or '',
            })
            continue

        # Trigger MIMIC sync in background thread — CCU only, never General Ward
        if not all_vitals and _p_location != 'GENERAL_WARD' and _fetch_status == 'fetched':
            def _bg_sync(hid):
                try:
                    _db = SessionLocal()
                    sync_patient_from_mimic(hid, _db)
                    _db.close()
                except Exception:
                    pass
            threading.Thread(target=_bg_sync, args=(p.hadm_id,), daemon=True).start()

        # REPLAY_OFFSET must only shift history on explicit replay requests —
        # applying the global to normal reads makes every dashboard poll skip
        # the newest vitals rows once anyone has used the replay endpoint.
        safe_offset = min(REPLAY_OFFSET, max(len(all_vitals) - 1, 0)) if replay else 0
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
            
        # Calculate time diff for stale check (guard empty vitals — patient just admitted)
        latest_time = vitals_history[-1].chart_time if vitals_history else demo_now
        latest_time = latest_time or demo_now
        time_diff_secs = (demo_now - latest_time).total_seconds()
        stale_mins = int(time_diff_secs // 60)

        news_data = calculate_news2(latest_vitals, getattr(p, 'hypercapnic_failure', 0) == 1)
        news2_score = news_data["total"]

        # Monitoring cadence + "vitals due/overdue" — adapts to CCU vs General Ward
        ward_location = getattr(p, 'ward_location', 'CCU') or 'CCU'
        monitoring = monitoring_plan(news2_score, news_data["factors"], ward_location)
        no_vitals_yet = len(vitals_history) == 0
        is_overdue = stale_mins > monitoring["interval_mins"] and not no_vitals_yet
        
        if no_vitals_yet:
            due_label = "Awaiting first vitals"
        else:
            due_label = ("Overdue " + fmt_mins(stale_mins - monitoring["interval_mins"])) if is_overdue \
                        else ("Due in " + fmt_mins(monitoring["interval_mins"] - stale_mins))

        if no_vitals_yet: status = 'stable'
        elif is_overdue: status = 'stale'
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
                is_valid(v.spo2), is_valid(v.sbp), is_valid(v.temperature)
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
            "diagnosis_short": p.diagnosis_short or getattr(p, 'primary_diagnosis_title', None) or (p.ews_complaint.split(',')[0] if p.ews_complaint else "—"),
            "ward_location": ward_location,
            "ewsReason": ews_reason,
            "monitoring": monitoring,
            "isOverdue": is_overdue,
            "noVitalsYet": no_vitals_yet,
            "dueLabel": due_label,
            "urineOutput": int(latest_vitals['urine_output']) if latest_vitals['urine_output'] is not None else None,
            "fluidBalance": int(latest_vitals['fluid_balance']) if latest_vitals['fluid_balance'] is not None else None,
            "mlContributors": ml["contributors"],
            "mlWindow": ml["window"],
            "name": p.patient_name or f"Patient {p.hadm_id}",
            "age": p.anchor_age,
            "sex": p.gender,
            "ward": p.ward,
            "room": p.room,
            "bed": p.bed,
            "admitted": p.admit_time.strftime("%d %b %Y") if p.admit_time else "--",
            "complaint": p.ews_complaint,
            "briefFlag": brief_flag,
            "status": status,
            # Raw active_patients.status — the "status" above is the computed
            # clinical tier; the discharge badge needs the DB lifecycle state.
            "db_status": getattr(p, 'status', 'active'),
            "vitals": {"bp_time": vitals_history[-1].chart_time.strftime("%H:%M") if vitals_history and vitals_history[-1].chart_time else "--"},
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

    _response = {"patients": result, "ward": ward}
    if hadm_id is None:
        _ward_cache[_cache_key] = {"ts": _time.time(), "data": _response}
    return _response

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

@app.get("/api/escalations/{esc_id}")
def get_escalation_detail(esc_id: int, db: Session = Depends(get_db)):
    """Single-escalation detail for the N4 status-log timeline.
    Returns snake_case keys — that is what the N4 timeline renderer reads."""
    e = db.query(Escalation).filter(Escalation.id == esc_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Escalation not found")
    return {
        "id": e.id,
        "patient_id": e.hadm_id,
        "patient_name": e.patient_name,
        "ward": e.ward,
        "bed": e.bed,
        "news2_score": e.news2_score,
        "level": e.level,
        "attending": e.attending,
        "escalated_by": e.escalated_by,
        "observations": e.observations,
        "interventions": e.interventions,
        "status": e.status,
        "escalated_at": e.escalated_at,
        "acknowledged_at": e.acknowledged_at,
        "resolved_at": e.resolved_at,
        "resolved_by": e.resolved_by,
        "resolution_notes": e.resolution_notes,
        "reescalated_at": e.reescalated_at,
        "reescalation_note": e.reescalation_note,
    }

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
    # BUG-07 FIX: Invalidate the ward cache so the next dashboard poll returns
    # fresh NEWS2 scores. Without this, the nurse returns to the dashboard and
    # sees the old score for up to 20 seconds.
    _invalidate_ward_cache(patient.ward)

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

    patient = db.query(Patient).filter(Patient.hadm_id == subject_id).first()
    v_dict = {
        "heart_rate": vt.heart_rate, "resp_rate": vt.resp_rate,
        "spo2": vt.spo2, "sbp": vt.sbp, "temperature": vt.temperature,
        "air_or_oxygen": vt.air_or_oxygen
    }
    news_result = calculate_news2(v_dict, patient.hypercapnic_failure == 1 if patient else False)
    plan = monitoring_plan(news_result["total"], news_result["factors"], patient.ward_location if patient else "GW")

    recorded_at = (vt.chart_time if isinstance(vt.chart_time, datetime) else datetime.now()).replace(tzinfo=None)
    stale_mins = int((datetime.now() - recorded_at).total_seconds() // 60)
    is_stale = stale_mins > plan["interval_mins"]

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
    sustained = score <= 2 and window_h >= 2

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
        {"label": "NEWS2 ≤ 2, sustained 2h+", "met": bool(sustained and window_h >= 2),
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
        "diagnosis": (patient.diagnosis_short if patient else None) or getattr(patient, 'primary_diagnosis_title', None) or detail.get("ews_complaint"),
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
        hadm_id=subject_id, patient_name=patient.patient_name,
        diagnosis=patient.diagnosis_short or patient.primary_diagnosis_title or patient.ews_complaint,
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
    try:
        t.status = "approved"
        t.decided_at = datetime.now()
        t.decided_by = body.decidedBy
        db.commit()
    except Exception:
        db.rollback()
    try:
        patient = db.query(Patient).filter(Patient.hadm_id == t.hadm_id).first()
        if patient:
            patient.ward_location = "GENERAL_WARD"
            db.commit()
    except Exception:
        db.rollback()
    return {"status": "ok", "id": tid, "wardLocation": "GENERAL_WARD"}

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
from sqlalchemy import text as sql_text

@app.get("/api/billing-notify/pending")
def billing_notify_pending_stub():
    """Stub — old browser tabs may still poll this. Returns empty so no 404 spam."""
    return {"notifications": []}

@app.post("/api/patients/{hadm_id}/sync-vitals")
def sync_vitals_now(hadm_id: int, db: Session = Depends(get_db)):
    """
    Called by billing.html after prefetch-all completes.
    Immediately runs sync_patient_from_mimic: reads ap_chartevents → ews_vitals_timeseries.
    Ward board then shows real vitals on next poll instead of waiting 15 min.
    """
    try:
        result = sync_patient_from_mimic(hadm_id, db)
        # Mark fully fetched now that vitals are synced — ward board stops showing loader
        db.execute(sql_text(
            "UPDATE active_patients SET data_fetch_status='fetched' WHERE hadm_id=:h AND data_fetch_status IN ('partial','fetching','pending')"
        ), {"h": hadm_id})
        db.commit()
        patient = db.query(Patient).filter(Patient.hadm_id == hadm_id).first()
        if patient:
            _invalidate_ward_cache(patient.ward)
        else:
            _ward_cache.clear()
        return {"status": "ok", "hadm_id": hadm_id, "vitals_inserted": result.get("vitals_inserted", 0)}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.post("/api/patients/{subject_id}/initiate-discharge")
def initiate_discharge(subject_id: int, db: Session = Depends(get_db)):
    """Mark patient discharge-ready in shared active_patients table.
    Creates an app_encounter with 'Pending Ingestion' so the resident sees it in dashboard.html."""
    patient = db.query(Patient).filter(Patient.hadm_id == subject_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    # Resolve the real patient name: hospital_core first, then Sabari's own table
    resolved_name = None
    try:
        name_row = db.execute(sql_text("""
            SELECT hcp.full_name FROM hospital_core.admissions hca
            JOIN hospital_core.patients hcp ON hca.uhid = hcp.uhid
            WHERE hca.hadm_id = :h LIMIT 1
        """), {"h": subject_id}).fetchone()
        if name_row and name_row[0]:
            resolved_name = name_row[0]
    except Exception:
        pass
    # Fallback: use Sabari's own patient record (always populated on registration)
    if not resolved_name and patient.patient_name:
        resolved_name = patient.patient_name
    if resolved_name:
        try:
            db.execute(sql_text(
                "UPDATE active_patients SET patient_name = :n WHERE hadm_id = :h"
            ), {"n": resolved_name, "h": subject_id})
        except Exception:
            pass

    db.execute(sql_text(
        "UPDATE active_patients SET status = 'discharge_initiated', data_fetch_status = 'fetched', updated_at = NOW() WHERE hadm_id = :h"
    ), {"h": subject_id})

    # Create or reset the app_encounter to 'Pending Ingestion' so it appears
    # in the resident's dashboard.html queue for discharge summary generation.
    existing_enc = db.execute(sql_text(
        "SELECT id, status FROM app_encounters WHERE hadm_id = :h ORDER BY created_at DESC LIMIT 1"
    ), {"h": subject_id}).fetchone()

    if existing_enc:
        if existing_enc[1] not in ('Processing', 'Awaiting Review', 'Signed Off', 'Files Ready'):
            db.execute(sql_text(
                "UPDATE app_encounters SET status = 'Ready for Review', updated_at = NOW() WHERE id = :id"
            ), {"id": existing_enc[0]})
    else:
        db.execute(sql_text("""
            INSERT INTO app_encounters (hadm_id, status, created_at, updated_at)
            VALUES (:h, 'Ready for Review', NOW(), NOW())
            ON CONFLICT DO NOTHING
        """), {"h": subject_id})

    db.commit()
    _invalidate_ward_cache(patient.ward)  # invalidate so next poll reflects discharge
    return {
        "status": "discharge_initiated",
        "hadm_id": subject_id,
        "message": "Patient moved to discharge queue. Resident notified via dashboard.",
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

@app.get("/api/on-call-doctors")
def get_on_call_doctors(db: Session = Depends(get_db)):
    """Return a list of on-call doctors (or consultants) from app_users."""
    try:
        users = db.execute(sql_text(
            "SELECT full_name, role FROM app_users WHERE is_active = TRUE AND role IN ('doctor', 'consultant')"
        )).fetchall()
        if not users:
            raise Exception("No doctors found")
        return [{"name": u[0], "role": u[1]} for u in users]
    except Exception:
        return [
            {"name": "Dr. Anand Sharma", "role": "Cardiology"},
            {"name": "Dr. Priya Mehta", "role": "doctor"},
            {"name": "Dr. Deepak Rao", "role": "doctor"}
        ]


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
def bulk_sync_patients(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Sync all active patients that have no ews_vitals yet in the background."""
    patients = db.query(Patient).filter(Patient.status == "active").all()
    
    def run_sync(hadm_ids):
        db_bg = SessionLocal()
        try:
            for hadm_id in hadm_ids:
                try:
                    sync_patient_from_mimic(hadm_id, db_bg)
                except Exception:
                    pass
        finally:
            db_bg.close()

    hadm_ids_to_sync = []
    for p in patients:
        has_vitals = db.query(VitalTimeSeries).filter(
            VitalTimeSeries.hadm_id == p.hadm_id
        ).first()
        if not has_vitals:
            hadm_ids_to_sync.append(p.hadm_id)
            
    if hadm_ids_to_sync:
        background_tasks.add_task(run_sync, hadm_ids_to_sync)
        
    return {"status": "sync_started", "patients_queued": len(hadm_ids_to_sync)}


# ════════════════════════════════════════════════════════════════════════════
#  Ward cache warmup — called on login to prime cache before first screen render
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/ward-data/warmup")
def warmup_ward_cache(db: Session = Depends(get_db)):
    """Pre-warm the ward-data cache for all locations so the first dashboard load is fast."""
    # "All" first — CCU/GENERAL_WARD are then derived from its cache entry
    # instead of running the full Cloud SQL pipeline three times.
    for loc in ["All", "CCU", "GENERAL_WARD"]:
        cache_key = ("All", loc)
        cached = _ward_cache.get(cache_key)
        if not cached or (_time.time() - cached["ts"]) >= _WARD_CACHE_TTL:
            try:
                get_ward_data(ward="All", location=loc, db=db)
            except Exception:
                pass
    return {"status": "warmed"}


# ════════════════════════════════════════════════════════════════════════════
#  Shift Handoff endpoints
# ════════════════════════════════════════════════════════════════════════════

_FALLBACK_NURSES = [
    {"name": "Nurse Prathima M", "role": "nurse", "shift": "Night"},
    {"name": "Nurse Kavita Rao", "role": "nurse", "shift": "Night"},
    {"name": "Nurse Anitha S", "role": "nurse", "shift": "Morning"},
    {"name": "Nurse Deepa K", "role": "nurse", "shift": "Evening"},
]

@app.get("/api/nurses-on-shift")
def get_nurses_on_shift(db: Session = Depends(get_db)):
    """Return list of nurses available for handoff selection. Queries app_users; falls back to defaults."""
    try:
        rows = db.execute(sql_text(
            "SELECT full_name, role FROM app_users WHERE is_active = TRUE AND role = 'nurse' ORDER BY full_name"
        )).fetchall()
        if rows:
            return {"nurses": [{"name": r[0], "role": r[1], "shift": ""} for r in rows]}
    except Exception:
        pass
    return {"nurses": _FALLBACK_NURSES}


class ShiftHandoffCreate(BaseModel):
    outgoingNurse: str
    incomingNurse: str
    ward: str = "Ward 4B/4C"
    shift: str = "Day"
    notes: str = ""
    pendingTasks: list = []

@app.post("/api/shift-handoffs")
def create_shift_handoff(body: ShiftHandoffCreate, db: Session = Depends(get_db)):
    """Persist a shift handoff record. Creates table if not exists. Returns reference ID."""
    try:
        db.execute(sql_text("""
            CREATE TABLE IF NOT EXISTS shift_handoffs (
                id SERIAL PRIMARY KEY,
                ward TEXT,
                shift TEXT,
                outgoing_nurse TEXT,
                incoming_nurse TEXT,
                notes TEXT,
                pending_tasks JSONB,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db.commit()
    except Exception:
        db.rollback()

    import json as _json
    try:
        result = db.execute(sql_text("""
            INSERT INTO shift_handoffs (ward, shift, outgoing_nurse, incoming_nurse, notes, pending_tasks, created_at)
            VALUES (:ward, :shift, :out, :inc, :notes, :tasks, NOW())
            RETURNING id, created_at
        """), {
            "ward": body.ward, "shift": body.shift,
            "out": body.outgoingNurse, "inc": body.incomingNurse,
            "notes": body.notes,
            "tasks": _json.dumps(body.pendingTasks)
        }).fetchone()
        db.commit()
        ref_id = result[0] if result else 0
        created_at = result[1].isoformat() if result and result[1] else datetime.now().isoformat()
        ref_code = f"HO-{body.ward[:2].upper()}-{ref_id:06d}"
    except Exception as e:
        db.rollback()
        # Fallback — return an in-memory reference so the UI doesn't break
        import random as _r
        ref_id = _r.randint(100000, 999999)
        created_at = datetime.now().isoformat()
        ref_code = f"HO-WD-{ref_id}"

    return {
        "status": "ok",
        "referenceId": ref_code,
        "outgoingNurse": body.outgoingNurse,
        "incomingNurse": body.incomingNurse,
        "ward": body.ward,
        "shift": body.shift,
        "notes": body.notes,
        "createdAt": created_at,
    }


@app.get("/api/shift-handoffs/latest")
def get_latest_handoff(ward: str = "Ward 4B/4C", db: Session = Depends(get_db)):
    """Return the most recent handoff for a ward — used by N6b to show handoff details on reload."""
    try:
        row = db.execute(sql_text("""
            SELECT id, ward, shift, outgoing_nurse, incoming_nurse, notes, created_at
            FROM shift_handoffs
            WHERE ward = :ward
            ORDER BY created_at DESC
            LIMIT 1
        """), {"ward": ward}).fetchone()
        if row:
            ref_code = f"HO-{row[1][:2].upper()}-{row[0]:06d}"
            return {
                "referenceId": ref_code,
                "outgoingNurse": row[3],
                "incomingNurse": row[4],
                "ward": row[1],
                "shift": row[2],
                "notes": row[5] or "",
                "createdAt": row[6].isoformat() if row[6] else "",
            }
    except Exception:
        pass
    return None


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
#  Static frontend
# ════════════════════════════════════════════════════════════════════════════

# Mount the frontend directory (sabari_project) at the root to serve static files (index.html, app.js, styles.css)
from fastapi.staticfiles import StaticFiles
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
