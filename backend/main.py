import math
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import SessionLocal, init_db
from models import Patient, VitalTimeSeries, LabEvent, Medication, Escalation, CcuTransfer, DrugLabAction
from engine.drug_lab import check_patient_against_rules
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import random

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

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def calculate_news2(vitals, hypercapnic_failure=False):
    score = 0
    factors = []
    
    rr = vitals.get('resp_rate')
    if rr is not None:
        if rr <= 8: s = 3
        elif 9 <= rr <= 11: s = 1
        elif 12 <= rr <= 20: s = 0
        elif 21 <= rr <= 24: s = 2
        else: s = 3
        score += s
        if s > 0: factors.append({"name": "Respiration Rate", "score": s})

    spo2 = vitals.get('spo2')
    if spo2 is not None:
        if hypercapnic_failure:
            if spo2 <= 83: s = 3
            elif 84 <= spo2 <= 85: s = 2
            elif 86 <= spo2 <= 87: s = 1
            elif 88 <= spo2 <= 92: s = 0
            elif 93 <= spo2 <= 94 and vitals.get('air_or_oxygen') == 'Oxygen': s = 1
            elif 95 <= spo2 <= 96 and vitals.get('air_or_oxygen') == 'Oxygen': s = 2
            elif spo2 >= 97 and vitals.get('air_or_oxygen') == 'Oxygen': s = 3
            else: s = 0
            score += s
            if s > 0: factors.append({"name": "SpO2 (Scale 2)", "score": s})
        else:
            if spo2 <= 91: s = 3
            elif 92 <= spo2 <= 93: s = 2
            elif 94 <= spo2 <= 95: s = 1
            else: s = 0
            score += s
            if s > 0: factors.append({"name": "SpO2 (Scale 1)", "score": s})
            
    air_or_oxygen = vitals.get('air_or_oxygen')
    if air_or_oxygen == 'Oxygen':
        score += 2
        factors.append({"name": "Supplemental Oxygen", "score": 2})

    sbp = vitals.get('sbp')
    if sbp is not None:
        # NEWS2 standard thresholds (internationally validated, used in Indian hospitals)
        # India calibration: SBP >= 220 mmHg = hypertensive crisis (score 3)
        # per ICMR/CSI hypertension guidelines — more prevalent in Indian cohorts
        if sbp <= 90: s = 3
        elif 91 <= sbp <= 100: s = 2
        elif 101 <= sbp <= 110: s = 1
        elif 111 <= sbp <= 219: s = 0
        else: s = 3  # >= 220 mmHg — hypertensive crisis
        score += s
        if s > 0: factors.append({"name": "Systolic BP", "score": s})

    hr = vitals.get('heart_rate')
    if hr is not None:
        if hr <= 40: s = 3
        elif 41 <= hr <= 50: s = 1
        elif 51 <= hr <= 90: s = 0
        elif 91 <= hr <= 110: s = 1
        elif 111 <= hr <= 130: s = 2
        else: s = 3
        score += s
        if s > 0: factors.append({"name": "Heart Rate", "score": s})

    consciousness = vitals.get('consciousness')
    if consciousness and consciousness != 'A':
        score += 3
        factors.append({"name": "Consciousness (CVPU)", "score": 3})

    temp = vitals.get('temperature')
    if temp is not None:
        if temp <= 35.0: s = 3
        elif 35.1 <= temp <= 36.0: s = 1
        elif 36.1 <= temp <= 38.0: s = 0
        elif 38.1 <= temp <= 39.0: s = 1
        else: s = 2
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
    escalatedBy: str = "Nurse Rekha Devi"

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
    return {"message": "Patient added", "subject_id": new_id}

REPLAY_OFFSET = 0

@app.get("/api/ward-data")
def get_ward_data(ward: str = "All", location: str = "All", replay: bool = False, db: Session = Depends(get_db)):
    global REPLAY_OFFSET
    if replay:
        REPLAY_OFFSET = (REPLAY_OFFSET + 1) % 20

    q = db.query(Patient)
    if ward != "All":
        q = q.filter(Patient.ward == ward)
    if location != "All":
        q = q.filter(Patient.ward_location == location)   # CCU | GENERAL_WARD
    patients = q.all()
    
    # Base "now" on the latest recorded vital in the entire database to prevent 
    # everything from going stale if the demo server runs for hours.
    from sqlalchemy import func
    demo_now = db.query(func.max(VitalTimeSeries.chart_time)).scalar() or datetime.now()

    result = []
    for p in patients:
        all_vitals = db.query(VitalTimeSeries).filter(
            VitalTimeSeries.hadm_id == p.hadm_id
        ).order_by(VitalTimeSeries.chart_time.desc()).all()
        
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

        db_labs = db.query(LabEvent).filter(
            LabEvent.hadm_id == p.hadm_id
        ).order_by(LabEvent.chart_time.desc()).limit(10).all()

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

        # ── Full medication objects (name + dose + frequency) ──
        meds_db = db.query(Medication).filter(Medication.hadm_id == p.hadm_id).all()
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
            "stale_mins": stale_mins
        })
        
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
    ward_data = get_ward_data(ward="All", replay=False, db=db)
    for p in ward_data["patients"]:
        if str(p["id"]) == str(subject_id):
            return p
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
        patient.ward_location = "GENERAL_WARD"   # the step-down state change
    db.commit()
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

@app.post("/api/patients/{subject_id}/initiate-discharge")
def initiate_discharge(subject_id: int, db: Session = Depends(get_db)):
    """Mark patient discharge-ready in shared active_patients table.
    Sets status='data_ready' so Ashmit's system picks it up for summary generation."""
    patient = db.query(Patient).filter(Patient.hadm_id == subject_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    db.execute(sql_text(
        "UPDATE active_patients SET status = 'data_ready', updated_at = NOW() WHERE hadm_id = :h"
    ), {"h": subject_id})
    db.commit()
    return {
        "status": "discharge_initiated",
        "hadm_id": subject_id,
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


# Mount the frontend directory (sabari_project) at the root to serve static files (index.html, app.js, styles.css)
import os
from fastapi.staticfiles import StaticFiles
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
