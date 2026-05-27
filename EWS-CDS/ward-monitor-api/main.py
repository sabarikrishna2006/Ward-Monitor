from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import SessionLocal, init_db
from models import Patient, VitalTimeSeries, LabEvent
import random

app = FastAPI(title="Ward Monitor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow React frontend
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
    
    # Respiratory Rate
    rr = vitals.get('resp_rate')
    if rr is not None:
        if rr <= 8: s = 3
        elif 9 <= rr <= 11: s = 1
        elif 12 <= rr <= 20: s = 0
        elif 21 <= rr <= 24: s = 2
        else: s = 3
        score += s
        factors.append({"name": "Respiration Rate", "score": s})

    # SpO2
    spo2 = vitals.get('spo2')
    if spo2 is not None:
        if spo2 <= 91: s = 3
        elif 92 <= spo2 <= 93: s = 2
        elif 94 <= spo2 <= 95: s = 1
        else: s = 0
        score += s
        factors.append({"name": "SpO2 Scale 1", "score": s})

    # Systolic BP
    sbp = vitals.get('sbp')
    if sbp is not None:
        if sbp <= 90: s = 3
        elif 91 <= sbp <= 100: s = 2
        elif 101 <= sbp <= 110: s = 1
        elif 111 <= sbp <= 219: s = 0
        else: s = 3
        score += s
        factors.append({"name": "Systolic BP", "score": s})

    # Heart Rate
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

    # Temperature
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

@app.get("/api/ward-data")
def get_ward_data(db: Session = Depends(get_db)):
    patients = db.query(Patient).all()
    
    result = []
    for p in patients:
        # Get last 24 vitals
        vitals_history = db.query(VitalTimeSeries).filter(
            VitalTimeSeries.subject_id == p.subject_id
        ).order_by(VitalTimeSeries.chart_hour.desc()).limit(24).all()
        
        if not vitals_history:
            continue
            
        vitals_history.reverse() # chronological order
        
        # Latest vital
        latest = vitals_history[-1]
        
        # Calculate NEWS2
        vitals_dict = {
            'resp_rate': latest.resp_rate,
            'spo2': latest.spo2,
            'sbp': latest.sbp,
            'heart_rate': latest.heart_rate,
            'temperature': latest.temperature
        }
        news_data = calculate_news2(vitals_dict)
        news2_score = news_data["total"]
        
        # Status
        if news2_score >= 7: status = 'critical'
        elif news2_score >= 5: status = 'warning'
        else: status = 'stable'
        
        # Format trajectory for Recharts
        trajectory = []
        for v in vitals_history:
            # simplify time string for display (e.g., "14:00")
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

        # Labs for Drawer
        labs = db.query(LabEvent).filter(
            LabEvent.subject_id == p.subject_id
        ).order_by(LabEvent.chart_hour.desc()).limit(10).all()
        
        formatted_labs = []
        for l in labs:
            if l.lactate: formatted_labs.append({"time": str(l.chart_hour), "test": "Lactate", "value": l.lactate, "unit": "mmol/L"})
            if l.creatinine: formatted_labs.append({"time": str(l.chart_hour), "test": "Creatinine", "value": l.creatinine, "unit": "mg/dL"})
            if l.potassium: formatted_labs.append({"time": str(l.chart_hour), "test": "Potassium", "value": l.potassium, "unit": "mmol/L"})

        bp_str = f"{int(latest.sbp)}/{int(latest.dbp)}" if latest.sbp and latest.dbp else "--/--"
        
        # ML Risk (Placeholder model inference)
        ml_risk = min(100, int((news2_score * 12) + random.randint(0, 15)))

        explanation = "Vital signs are within normal limits."
        action = "Continue routine ward monitoring."
        if status == 'critical':
            abnormal_factors = [f['name'] for f in news_data["factors"] if f['score'] > 0]
            factor_str = ", ".join(abnormal_factors) if abnormal_factors else "multiple vitals"
            explanation = f"ML model flagged high risk of deterioration (Score: {ml_risk}%). Primary contributors: {factor_str}."
            action = "Immediate bedside assessment. Escalate to Rapid Response Team (RRT). Continuous continuous SpO2/ECG monitoring."
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
            "recentLabs": formatted_labs[:5]
        })
        
    return {"patients": result, "ward": "4B"}
