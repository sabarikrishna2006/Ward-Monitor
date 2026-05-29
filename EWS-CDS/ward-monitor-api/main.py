from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import SessionLocal, init_db
from models import Patient, VitalTimeSeries, LabEvent, Medication
from engine.drug_lab import check_patient_against_rules
from pydantic import BaseModel
from datetime import datetime
import random

app = FastAPI(title="Ward Monitor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def calculate_news2(vitals):
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
        factors.append({"name": "Respiration Rate", "score": s})

    spo2 = vitals.get('spo2')
    if spo2 is not None:
        if spo2 <= 91: s = 3
        elif 92 <= spo2 <= 93: s = 2
        elif 94 <= spo2 <= 95: s = 1
        else: s = 0
        score += s
        factors.append({"name": "SpO2 Scale 1", "score": s})

    sbp = vitals.get('sbp')
    if sbp is not None:
        if sbp <= 90: s = 3
        elif 91 <= sbp <= 100: s = 2
        elif 101 <= sbp <= 110: s = 1
        elif 111 <= sbp <= 219: s = 0
        else: s = 3
        score += s
        factors.append({"name": "Systolic BP", "score": s})

    hr = vitals.get('heart_rate')
    if hr is not None:
        if hr <= 40: s = 3
        elif 41 <= hr <= 50: s = 1
        elif 51 <= hr <= 90: s = 0
        elif 91 <= hr <= 110: s = 1
        elif 111 <= hr <= 130: s = 2
        else: s = 3
        score += s
        factors.append({"name": "Heart Rate", "score": s})

    temp = vitals.get('temperature')
    if temp is not None:
        if temp <= 35.0: s = 3
        elif 35.1 <= temp <= 36.0: s = 1
        elif 36.1 <= temp <= 38.0: s = 0
        elif 38.1 <= temp <= 39.0: s = 1
        else: s = 2
        score += s
        factors.append({"name": "Temperature", "score": s})

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
        complaint=patient.complaint
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
        temperature=patient.temp
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
    
    result = []
    for p in patients:
        # Replay offset applied here
        vitals_history = db.query(VitalTimeSeries).filter(
            VitalTimeSeries.subject_id == p.subject_id
        ).order_by(VitalTimeSeries.chart_hour.desc()).offset(REPLAY_OFFSET).limit(24).all()
        
        if not vitals_history:
            continue
            
        vitals_history.reverse()
        latest = vitals_history[-1]
        
        vitals_dict = {
            'resp_rate': latest.resp_rate,
            'spo2': latest.spo2,
            'sbp': latest.sbp,
            'heart_rate': latest.heart_rate,
            'temperature': latest.temperature
        }
        news_data = calculate_news2(vitals_dict)
        news2_score = news_data["total"]
        
        if news2_score >= 7: status = 'critical'
        elif news2_score >= 5: status = 'warning'
        else: status = 'stable'
        
        trajectory = []
        for v in vitals_history:
            time_str = str(v.chart_hour).split('T')[-1][:5] if 'T' in str(v.chart_hour) else str(v.chart_hour)
            trajectory.append({
                "time": time_str,
                "hr": v.heart_rate if v.heart_rate else 0,
                "rr": v.resp_rate if v.resp_rate else 0,
                "spo2": v.spo2 if v.spo2 else 0,
                "temp": v.temperature if v.temperature else 0,
                "sbp": v.sbp,
                "dbp": v.dbp
            })

        db_labs = db.query(LabEvent).filter(
            LabEvent.subject_id == p.subject_id
        ).order_by(LabEvent.chart_hour.desc()).limit(10).all()
        
        formatted_labs = []
        rule_engine_labs = {}
        for l in db_labs:
            if l.lactate: 
                formatted_labs.append({"time": str(l.chart_hour), "test": "Lactate", "value": l.lactate, "unit": "mmol/L"})
                if "lactate" not in rule_engine_labs: rule_engine_labs["lactate"] = l.lactate
            if l.creatinine: 
                formatted_labs.append({"time": str(l.chart_hour), "test": "Creatinine", "value": l.creatinine, "unit": "mg/dL"})
                if "creatinine" not in rule_engine_labs: rule_engine_labs["creatinine"] = l.creatinine
            if l.potassium: 
                formatted_labs.append({"time": str(l.chart_hour), "test": "Potassium", "value": l.potassium, "unit": "mmol/L"})
                if "potassium" not in rule_engine_labs: rule_engine_labs["potassium"] = l.potassium

        meds = db.query(Medication).filter(Medication.subject_id == p.subject_id).all()
        med_names = [m.med_name for m in meds]
        
        # Run drug-lab rules
        drug_lab_alerts = check_patient_against_rules(med_names, rule_engine_labs)
        # If there are critical drug-lab alerts, escalate status
        if any(a['severity'] == 'CRITICAL' for a in drug_lab_alerts) and status != 'critical':
            status = 'critical'
            news2_score = max(news2_score, 7)

        bp_str = f"{int(latest.sbp)}/{int(latest.dbp)}" if latest.sbp and latest.dbp else "--/--"
        ml_risk = min(100, int((news2_score * 12) + random.randint(0, 15)))

        explanation = "Vital signs are within normal limits."
        action = "Continue routine ward monitoring."
        if status == 'critical':
            abnormal_factors = [f['name'] for f in news_data["factors"] if f['score'] > 0]
            factor_str = ", ".join(abnormal_factors) if abnormal_factors else "multiple vitals"
            explanation = f"ML model flagged high risk of deterioration (Score: {ml_risk}%). Primary contributors: {factor_str}."
            action = "Immediate bedside assessment. Escalate to Rapid Response Team (RRT). Continuous continuous SpO2/ECG monitoring."
            
            if drug_lab_alerts:
                action = drug_lab_alerts[0]['action']
                explanation = drug_lab_alerts[0]['message']

        elif status == 'warning':
            abnormal_factors = [f['name'] for f in news_data["factors"] if f['score'] > 0]
            factor_str = ", ".join(abnormal_factors) if abnormal_factors else "vitals"
            explanation = f"Warning: Early signs of instability. Abnormal {factor_str} detected."
            action = "Increase monitoring frequency to Q2H. Notify attending physician for review."

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
            "status": status,
            "hr": int(latest.heart_rate) if latest.heart_rate else "--",
            "rr": int(latest.resp_rate) if latest.resp_rate else "--",
            "spo2": int(latest.spo2) if latest.spo2 else "--",
            "bp": bp_str,
            "temp": round(latest.temperature, 1) if latest.temperature else "--",
            "news2": news2_score,
            "newsFactors": news_data["factors"],
            "mlRisk": ml_risk,
            "mlExplanation": explanation,
            "recommendedAction": action,
            "trajectory": trajectory,
            "recentVitals": trajectory[-5:],
            "recentLabs": formatted_labs[:5],
            "drugLabAlerts": drug_lab_alerts,
            "meds": med_names
        })
        
    return {"patients": result, "ward": ward}
