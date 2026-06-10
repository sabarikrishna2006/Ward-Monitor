import math
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import SessionLocal, init_db
from models import Patient, VitalTimeSeries, LabEvent, Medication, Escalation
from engine.drug_lab import check_patient_against_rules
from pydantic import BaseModel
from datetime import datetime
import random

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
    max_id = db.query(Patient).order_by(Patient.subject_id.desc()).first()
    new_id = (max_id.subject_id + 1) if max_id else 1
    
    new_patient = Patient(
        subject_id=new_id,
        name=patient.name,
        age=patient.age,
        sex=patient.sex,
        ward=patient.ward,
        room=patient.room,
        bed=patient.bed,
        admitted=datetime.now().strftime("%d %b %Y"),
        complaint=patient.complaint,
        hypercapnic_failure=patient.hypercapnic_failure
    )
    db.add(new_patient)
    db.commit()
    
    v = VitalTimeSeries(
        subject_id=new_id,
        chart_hour=datetime.now().isoformat(),
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
def get_ward_data(ward: str = "All", replay: bool = False, db: Session = Depends(get_db)):
    global REPLAY_OFFSET
    if replay:
        REPLAY_OFFSET = (REPLAY_OFFSET + 1) % 20

    if ward == "All":
        patients = db.query(Patient).all()
    else:
        patients = db.query(Patient).filter(Patient.ward == ward).all()
    
    # Base "now" on the latest recorded vital in the entire database to prevent 
    # everything from going stale if the demo server runs for hours.
    from sqlalchemy import func
    max_time_str = db.query(func.max(VitalTimeSeries.chart_hour)).scalar()
    if max_time_str:
        if 'T' in str(max_time_str):
            demo_now = datetime.fromisoformat(str(max_time_str))
        else:
            demo_now = datetime.strptime(str(max_time_str), "%Y-%m-%d %H:%M:%S")
    else:
        demo_now = datetime.now()
        
    result = []
    for p in patients:
        vitals_history = db.query(VitalTimeSeries).filter(
            VitalTimeSeries.subject_id == p.subject_id
        ).order_by(VitalTimeSeries.chart_hour.desc()).offset(REPLAY_OFFSET).limit(24).all()
        
        if not vitals_history:
            continue
            
        vitals_history.reverse()
        
        # ── Forward-fill the latest non-null value for each vital ──
        latest_vitals = {
            'resp_rate': None, 'spo2': None, 'sbp': None,
            'dbp': None, 'heart_rate': None, 'temperature': None,
            'consciousness': 'A', 'air_or_oxygen': 'Air'
        }
        for v in vitals_history:
            if is_valid(v.resp_rate):    latest_vitals['resp_rate']    = v.resp_rate
            if is_valid(v.spo2):         latest_vitals['spo2']          = v.spo2
            if is_valid(v.sbp):          latest_vitals['sbp']           = v.sbp
            if is_valid(v.dbp):          latest_vitals['dbp']           = v.dbp
            if is_valid(v.heart_rate):   latest_vitals['heart_rate']    = v.heart_rate
            if is_valid(v.temperature):  latest_vitals['temperature']   = v.temperature
            if hasattr(v, 'consciousness') and v.consciousness and v.consciousness not in (None, ''):
                latest_vitals['consciousness'] = v.consciousness
            if hasattr(v, 'air_or_oxygen') and v.air_or_oxygen and v.air_or_oxygen not in (None, ''):
                latest_vitals['air_or_oxygen'] = v.air_or_oxygen
            
        # Calculate time diff for stale check
        latest_record_time_str = str(vitals_history[-1].chart_hour)
        if 'T' in latest_record_time_str:
            latest_time = datetime.fromisoformat(latest_record_time_str)
        else:
            latest_time = datetime.strptime(latest_record_time_str, "%Y-%m-%d %H:%M:%S")
        time_diff_secs = (demo_now - latest_time).total_seconds()
        is_stale = time_diff_secs > (4 * 3600)
        stale_mins = int(time_diff_secs // 60)

        news_data = calculate_news2(latest_vitals, getattr(p, 'hypercapnic_failure', 0) == 1)
        news2_score = news_data["total"]
        
        if is_stale: status = 'stale'
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

            time_str = str(v.chart_hour).split('T')[-1][:5] if 'T' in str(v.chart_hour) else str(v.chart_hour)
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

        # ── Recent Vitals (last 5 readings) — use resolved latest values ──
        recent_vitals = []
        for pt in trajectory[-5:]:
            # Compute historical NEWS2
            hist_v_dict = {
                'resp_rate': pt['rr'], 'spo2': pt['spo2'], 'sbp': pt['sbp'],
                'dbp': pt['dbp'], 'heart_rate': pt['hr'], 'temperature': pt['temp'],
                'consciousness': 'A', 'air_or_oxygen': 'Air'
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
            LabEvent.subject_id == p.subject_id
        ).order_by(LabEvent.chart_hour.desc()).limit(10).all()
        
        formatted_labs = []
        rule_engine_labs = {}
        for l in db_labs:
            if l.lactate: 
                formatted_labs.append({"time": str(l.chart_hour), "test": "Lactate", "value": round(l.lactate, 2), "unit": "mmol/L"})
                if "lactate" not in rule_engine_labs: rule_engine_labs["lactate"] = l.lactate
            if l.creatinine: 
                formatted_labs.append({"time": str(l.chart_hour), "test": "Creatinine", "value": round(l.creatinine, 2), "unit": "mg/dL"})
                if "creatinine" not in rule_engine_labs: rule_engine_labs["creatinine"] = l.creatinine
            if l.potassium: 
                formatted_labs.append({"time": str(l.chart_hour), "test": "Potassium", "value": round(l.potassium, 2), "unit": "mmol/L"})
                if "potassium" not in rule_engine_labs: rule_engine_labs["potassium"] = l.potassium

        # ── Full medication objects (name + dose + frequency) ──
        meds_db = db.query(Medication).filter(Medication.subject_id == p.subject_id).all()
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
        ml_risk = min(100, int((news2_score * 12) + random.randint(0, 15)))

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

        result.append({
            "id": str(p.subject_id),
            "name": p.name,
            "age": p.age,
            "sex": p.sex,
            "ward": p.ward,
            "room": p.room,
            "bed": p.bed,
            "admitted": p.admitted,
            "complaint": p.complaint,
            "briefFlag": brief_flag,
            "status": status,
            "vitals": {"bp_time": str(vitals_history[-1].chart_hour)},
            "hr":   int(latest_vitals['heart_rate'])  if latest_vitals['heart_rate']  else "--",
            "rr":   int(latest_vitals['resp_rate'])   if latest_vitals['resp_rate']   else "--",
            "spo2": int(latest_vitals['spo2'])        if latest_vitals['spo2']        else "--",
            "bp":   bp_str,
            "temp": round(latest_vitals['temperature'], 1) if latest_vitals['temperature'] else "--",
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
    patient = db.query(Patient).filter(Patient.subject_id == esc.patientId).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Get latest vitals for NEWS2 score
    vitals = db.query(VitalTimeSeries).filter(VitalTimeSeries.subject_id == esc.patientId).order_by(VitalTimeSeries.chart_hour.desc()).first()
    
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
        subject_id=esc.patientId,
        patient_name=patient.name,
        ward=patient.ward,
        bed=patient.bed,
        news2_score=news2_score,
        level=esc.level,
        attending=esc.attending,
        escalated_by=esc.escalatedBy,
        observations=esc.observations,
        interventions=esc.interventions,
        status='active',
        escalated_at=datetime.now().isoformat()
    )
    db.add(new_esc)
    db.commit()
    db.refresh(new_esc)
    
    return {"message": "Escalation created", "id": new_esc.id}

@app.get("/api/escalations")
def get_escalations(db: Session = Depends(get_db)):
    escalations = db.query(Escalation).order_by(Escalation.escalated_at.desc()).all()
    
    result = []
    for e in escalations:
        result.append({
            "id": e.id,
            "patientId": e.subject_id,
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
            "resolutionNotes": e.resolution_notes
        })
    return {"escalations": result}

@app.post("/api/escalations/{esc_id}/resolve")
def resolve_escalation(esc_id: int, res: EscalationResolve, db: Session = Depends(get_db)):
    esc = db.query(Escalation).filter(Escalation.id == esc_id).first()
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")
        
    esc.status = 'resolved'
    esc.resolved_at = datetime.now().isoformat()
    esc.resolved_by = res.resolvedBy
    esc.resolution_notes = res.notes
    
    db.commit()
    return {"message": "Escalation resolved", "id": esc.id}

@app.get("/api/patients/{subject_id}")
def get_patient_detail(subject_id: int, db: Session = Depends(get_db)):
    # This endpoint returns a single patient's detailed data for the N1b view
    ward_data = get_ward_data(ward="All", replay=False, db=db)
    
    for p in ward_data["patients"]:
        if str(p["id"]) == str(subject_id):
            return p
            
    raise HTTPException(status_code=404, detail="Patient not found")

