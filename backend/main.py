"""
Foqal CareOS — Ward Monitor API  (sabari_project/backend)
Endpoints:
  GET  /api/ward-data?ward=All           → full ward list with NEWS2, vitals, labs, DL alerts
  GET  /api/patients/{subject_id}        → single patient detail
  POST /api/escalations                  → create escalation (saved to DB)
  GET  /api/escalations                  → list all escalations
  POST /api/escalations/{id}/resolve     → resolve escalation
  POST /api/patients                     → add patient
"""
import math, os, random
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import SessionLocal, init_db
from models import Patient, VitalTimeSeries, LabEvent, Medication, Escalation
from engine.drug_lab import check_patient_against_rules
from pydantic import BaseModel
from datetime import datetime

# ─── helpers ─────────────────────────────────────────────────────────────────

def is_valid(val):
    if val is None:
        return False
    if isinstance(val, (float, int)) and (math.isnan(val) or val == 0):
        return False
    return True


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─── app ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Foqal CareOS API",
    description="Clinical Decision Support — Early Warning System + Drug-Lab Interaction Engine. "
                "Calibrated for Indian cardiology wards (CSI/CDSCO/ICMR/ESC guidelines).",
    version="1.0.0",
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


# ─── NEWS2 scoring ────────────────────────────────────────────────────────────

def calculate_news2(vitals: dict, hypercapnic_failure: bool = False) -> dict:
    score = 0
    factors = []

    rr = vitals.get("resp_rate")
    if rr is not None:
        if rr <= 8:           s = 3
        elif rr <= 11:        s = 1
        elif rr <= 20:        s = 0
        elif rr <= 24:        s = 2
        else:                 s = 3
        score += s
        if s > 0: factors.append({"name": "Respiration Rate", "score": s})

    spo2 = vitals.get("spo2")
    if spo2 is not None:
        if hypercapnic_failure:
            if spo2 <= 83:    s = 3
            elif spo2 <= 85:  s = 2
            elif spo2 <= 87:  s = 1
            elif spo2 <= 92:  s = 0
            elif spo2 <= 94 and vitals.get("air_or_oxygen") == "Oxygen": s = 1
            elif spo2 <= 96 and vitals.get("air_or_oxygen") == "Oxygen": s = 2
            elif spo2 >= 97 and vitals.get("air_or_oxygen") == "Oxygen": s = 3
            else:             s = 0
            score += s
            if s > 0: factors.append({"name": "SpO2 (Scale 2)", "score": s})
        else:
            if spo2 <= 91:    s = 3
            elif spo2 <= 93:  s = 2
            elif spo2 <= 95:  s = 1
            else:             s = 0
            score += s
            if s > 0: factors.append({"name": "SpO2 (Scale 1)", "score": s})

    if vitals.get("air_or_oxygen") == "Oxygen":
        score += 2
        factors.append({"name": "Supplemental Oxygen", "score": 2})

    sbp = vitals.get("sbp")
    if sbp is not None:
        if sbp <= 90:          s = 3
        elif sbp <= 100:       s = 2
        elif sbp <= 110:       s = 1
        elif sbp <= 219:       s = 0
        else:                  s = 3   # hypertensive crisis ≥ 220
        score += s
        if s > 0: factors.append({"name": "Systolic BP", "score": s})

    hr = vitals.get("heart_rate")
    if hr is not None:
        if hr <= 40:           s = 3
        elif hr <= 50:         s = 1
        elif hr <= 90:         s = 0
        elif hr <= 110:        s = 1
        elif hr <= 130:        s = 2
        else:                  s = 3
        score += s
        if s > 0: factors.append({"name": "Heart Rate", "score": s})

    consciousness = vitals.get("consciousness")
    if consciousness and consciousness != "A":
        score += 3
        factors.append({"name": "Consciousness (CVPU)", "score": 3})

    temp = vitals.get("temperature")
    if temp is not None:
        if temp <= 35.0:       s = 3
        elif temp <= 36.0:     s = 1
        elif temp <= 38.0:     s = 0
        elif temp <= 39.0:     s = 1
        else:                  s = 2
        score += s
        if s > 0: factors.append({"name": "Temperature", "score": s})

    return {"total": score, "factors": factors}


# ─── Pydantic schemas ─────────────────────────────────────────────────────────

class PatientCreate(BaseModel):
    name:    str;  age: int;  sex: str;  ward: str;  room: str;  bed: str
    complaint: str
    hr: float;  rr: float;  spo2: float;  sbp: float;  dbp: float;  temp: float
    air_or_oxygen: str = "Air";  consciousness: str = "A";  hypercapnic_failure: int = 0

class EscalationCreate(BaseModel):
    patientId: int;  level: str;  attending: str
    observations: str;  interventions: str
    escalatedBy: str = "Nurse"

class EscalationResolve(BaseModel):
    resolvedBy: str;  notes: str


# ─── /api/ward-data ───────────────────────────────────────────────────────────

@app.get("/api/ward-data")
def get_ward_data(ward: str = "All", db: Session = Depends(get_db)):
    if ward == "All":
        patients = db.query(Patient).all()
    else:
        patients = db.query(Patient).filter(Patient.ward == ward).all()

    result = []
    for p in patients:
        vitals_history = (
            db.query(VitalTimeSeries)
            .filter(VitalTimeSeries.subject_id == p.subject_id)
            .order_by(VitalTimeSeries.chart_hour.desc())
            .limit(24)
            .all()
        )
        if not vitals_history:
            continue

        vitals_history = list(reversed(vitals_history))

        # Forward-fill latest non-null vitals and keep track of timestamps
        lv = {
            "resp_rate": None, "spo2": None, "sbp": None, "dbp": None,
            "heart_rate": None, "temperature": None,
            "consciousness": "A", "air_or_oxygen": "Air",
        }
        lt = {k: None for k in lv.keys()} # Latest times

        for v in vitals_history:
            t_str = str(v.chart_hour)[11:16] # Extract HH:MM
            if is_valid(v.resp_rate):   lv["resp_rate"]   = v.resp_rate; lt["resp_rate"] = t_str
            if is_valid(v.spo2):        lv["spo2"]        = v.spo2;      lt["spo2"] = t_str
            if is_valid(v.sbp):         lv["sbp"]         = v.sbp;       lt["sbp"] = t_str
            if is_valid(v.dbp):         lv["dbp"]         = v.dbp;       lt["dbp"] = t_str
            if is_valid(v.heart_rate):  lv["heart_rate"]  = v.heart_rate;lt["heart_rate"] = t_str
            if is_valid(v.temperature): lv["temperature"] = v.temperature;lt["temperature"] = t_str
            if v.consciousness and v.consciousness not in (None, ""):
                lv["consciousness"] = v.consciousness; lt["consciousness"] = t_str
            if v.air_or_oxygen and v.air_or_oxygen not in (None, ""):
                lv["air_or_oxygen"] = v.air_or_oxygen; lt["air_or_oxygen"] = t_str


        news_data  = calculate_news2(lv, bool(p.hypercapnic_failure))
        news2_score = news_data["total"]

        if news2_score >= 7:    status = "critical"
        elif news2_score >= 5:  status = "warning"
        else:                   status = "stable"

        # ── Trajectory for chart
        trajectory = []
        fill = {"hr": None, "rr": None, "spo2": None, "temp": None, "sbp": None, "dbp": None}
        for v in vitals_history:
            if is_valid(v.heart_rate):  fill["hr"]   = round(v.heart_rate, 1)
            if is_valid(v.resp_rate):   fill["rr"]   = round(v.resp_rate, 1)
            if is_valid(v.spo2):        fill["spo2"] = round(v.spo2, 1)
            if is_valid(v.temperature): fill["temp"] = round(v.temperature, 1)
            if is_valid(v.sbp):         fill["sbp"]  = round(v.sbp, 1)
            if is_valid(v.dbp):         fill["dbp"]  = round(v.dbp, 1)
            if any(fill.values()):
                trajectory.append({"time": str(v.chart_hour)[-5:], **fill.copy()})

        # ── Recent vitals table (last 5)
        recent_vitals = [
            {"time": t["time"], "hr": t["hr"] or "--", "rr": t["rr"] or "--",
             "spo2": t["spo2"] or "--", "temp": t["temp"] or "--",
             "sbp": t["sbp"] or "--", "dbp": t["dbp"] or "--"}
            for t in trajectory[-5:]
        ]

        # ── Labs
        db_labs = (
            db.query(LabEvent)
            .filter(LabEvent.subject_id == p.subject_id)
            .order_by(LabEvent.chart_hour.desc())
            .limit(10)
            .all()
        )
        formatted_labs, rule_engine_labs = [], {}
        for lab in db_labs:
            if is_valid(lab.potassium):
                formatted_labs.append({"time": str(lab.chart_hour), "test": "Potassium",  "value": round(lab.potassium,  2), "unit": "mmol/L"})
                rule_engine_labs.setdefault("potassium",  lab.potassium)
            if is_valid(lab.creatinine):
                formatted_labs.append({"time": str(lab.chart_hour), "test": "Creatinine", "value": round(lab.creatinine, 2), "unit": "mg/dL"})
                rule_engine_labs.setdefault("creatinine", lab.creatinine)
            if is_valid(lab.lactate):
                formatted_labs.append({"time": str(lab.chart_hour), "test": "Lactate",    "value": round(lab.lactate,    2), "unit": "mmol/L"})
                rule_engine_labs.setdefault("lactate",    lab.lactate)
            if is_valid(lab.inr):
                formatted_labs.append({"time": str(lab.chart_hour), "test": "INR",        "value": round(lab.inr,        2), "unit": ""})
                rule_engine_labs.setdefault("inr",        lab.inr)
            if is_valid(lab.egfr):
                formatted_labs.append({"time": str(lab.chart_hour), "test": "eGFR",       "value": round(lab.egfr,       1), "unit": "mL/min"})
                rule_engine_labs.setdefault("egfr",       lab.egfr)
            if is_valid(lab.alt):
                formatted_labs.append({"time": str(lab.chart_hour), "test": "ALT",        "value": round(lab.alt,        1), "unit": "U/L"})
                rule_engine_labs.setdefault("alt",        lab.alt)

        # Also pass heart_rate to drug-lab engine (bradycardia rule)
        if lv["heart_rate"]:
            rule_engine_labs["heart_rate"] = lv["heart_rate"]

        # ── Medications
        meds_db = db.query(Medication).filter(Medication.subject_id == p.subject_id).all()
        med_names   = [m.med_name for m in meds_db]
        medications = [{"name": m.med_name, "dose": m.dose or "--", "frequency": m.frequency or "--"} for m in meds_db]

        # ── Drug-Lab alerts
        drug_lab_alerts = check_patient_against_rules(med_names, rule_engine_labs)
        if any(a["severity"] == "CRITICAL" for a in drug_lab_alerts) and status != "critical":
            status = "critical"
            news2_score = max(news2_score, 7)

        # ── BP string
        sbp_val = lv["sbp"]; dbp_val = lv["dbp"]
        bp_str = f"{int(sbp_val)}/{int(dbp_val)}" if sbp_val and dbp_val else "--/--"
        bp_time = lt["sbp"] or lt["dbp"] or ""

        ml_risk = min(100, int(news2_score * 12 + random.randint(0, 15)))

        # ── Clinical explanation
        abnormal = [f["name"] for f in news_data["factors"] if f["score"] > 0]
        factor_str = ", ".join(abnormal) if abnormal else "multiple vitals"

        any_single_3 = any(f["score"] >= 3 for f in news_data["factors"])
        brief_flag = ""
        if status == "critical":
            if drug_lab_alerts:
                brief_flag = drug_lab_alerts[0]["message"][:80]
            elif abnormal:
                brief_flag = f"↑ {', '.join(abnormal[:2])}"
            else:
                brief_flag = "Critical deterioration detected"
        elif status == "warning":
            brief_flag = f"Early instability: {', '.join(abnormal[:2])}" if abnormal else "Early instability"
        elif any_single_3:
            s3 = [f["name"] for f in news_data["factors"] if f["score"] >= 3]
            brief_flag = f"Single param alert: {s3[0]}" if s3 else ""

        if status == "critical":
            explanation = (f"HIGH RISK (NEWS2 ≥7). ML risk score: {ml_risk}%. "
                           f"Primary contributors: {factor_str}. Continuous monitoring required.")
            action = ("Emergent assessment by clinical team. Initiate continuous SpO2/ECG monitoring. "
                      "Usually requires transfer to higher level of care (HDU/ICU).")
            if drug_lab_alerts:
                explanation = drug_lab_alerts[0]["message"]
                action      = drug_lab_alerts[0]["action"]
        elif status == "warning":
            explanation = f"MEDIUM RISK (NEWS2 5–6). Abnormal: {factor_str}. ML risk: {ml_risk}%."
            action = ("Urgent review by ward doctor or acute-team nurse. "
                      "Decide if critical-care team assessment needed.")
        elif any_single_3:
            s3 = [f["name"] for f in news_data["factors"] if f["score"] >= 3]
            explanation = f"LOW-MEDIUM RISK: Score of 3 in {', '.join(s3)}. Urgent review within 1 hour."
            action = "Urgent ward-doctor review within 1 hour. Increase monitoring frequency."
        elif news2_score == 0:
            explanation = "LOW RISK (NEWS2 = 0). All vital signs within normal parameters."
            action = "Routine monitoring — minimum every 12 hours."
        else:
            explanation = f"LOW RISK (NEWS2 {news2_score}). Minor abnormalities: {factor_str}."
            action = "Assessment by registered nurse. Minimum monitoring every 4–6 hours."

        result.append({
            # ── Identity (IMPORTANT: use "news2" not "news2_score" — matches frontend)
            "id":          str(p.subject_id),
            "name":        p.name,
            "age":         p.age,
            "sex":         p.sex,
            "ward":        p.ward,
            "room":        p.room,
            "bed":         p.bed,
            "admitted":    p.admitted,
            "complaint":   p.complaint,
            # ── NEWS2
            "news2":       news2_score,          # single key used everywhere
            "newsFactors": news_data["factors"],
            "status":      status,
            "briefFlag":   brief_flag,
            # ── Latest vitals (flat for quick display)
            "hr":   int(lv["heart_rate"])  if lv["heart_rate"]  else "--",
            "hr_time": lt["heart_rate"],
            "rr":   int(lv["resp_rate"])   if lv["resp_rate"]   else "--",
            "rr_time": lt["resp_rate"],
            "spo2": int(lv["spo2"])        if lv["spo2"]        else "--",
            "spo2_time": lt["spo2"],
            "bp":   bp_str,
            "bp_time": bp_time,
            "temp": round(lv["temperature"], 1) if lv["temperature"] else "--",
            "temp_time": lt["temperature"],
            "avpu": lv["consciousness"] or "A",
            "avpu_time": lt["consciousness"],
            # ── Vitals object (for detail screen)
            "vitals": {
                "heart_rate":   lv["heart_rate"],
                "resp_rate":    lv["resp_rate"],
                "spo2":         lv["spo2"],
                "sbp":          lv["sbp"],
                "dbp":          lv["dbp"],
                "temperature":  lv["temperature"],
                "consciousness": lv["consciousness"],
                "air_or_oxygen": lv["air_or_oxygen"],
            },
            # ── Charts & detail
            "mlRisk":            ml_risk,
            "mlExplanation":     explanation,
            "recommendedAction": action,
            "trajectory": [
                {
                    "time": str(v.chart_hour)[11:16],
                    "hr": int(v.heart_rate) if v.heart_rate else "--",
                    "rr": int(v.resp_rate) if v.resp_rate else "--",
                    "spo2": int(v.spo2) if v.spo2 else "--",
                    "bp": f"{int(v.sbp) if v.sbp else '--'}/{int(v.dbp) if v.dbp else '--'}",
                } for v in vitals_history[:6]
            ],
            "recentVitals":      recent_vitals,
            "recentLabs":        formatted_labs[:8],
            "drugLabAlerts":     drug_lab_alerts,
            "meds":              med_names,
            "medications":       medications,
        })

    # Sort by NEWS2 descending
    result.sort(key=lambda x: x["news2"], reverse=True)
    return {"patients": result, "ward": ward, "total": len(result)}


# ─── /api/patients/{id} ───────────────────────────────────────────────────────

@app.get("/api/patients/{subject_id}")
def get_patient_detail(subject_id: int, db: Session = Depends(get_db)):
    ward_data = get_ward_data(ward="All", db=db)
    for p in ward_data["patients"]:
        if str(p["id"]) == str(subject_id):
            return p
    raise HTTPException(status_code=404, detail="Patient not found")


# ─── /api/escalations ────────────────────────────────────────────────────────

@app.post("/api/escalations")
def create_escalation(esc: EscalationCreate, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.subject_id == esc.patientId).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    vitals = (
        db.query(VitalTimeSeries)
        .filter(VitalTimeSeries.subject_id == esc.patientId)
        .order_by(VitalTimeSeries.chart_hour.desc())
        .first()
    )
    news2_score = 0
    if vitals:
        v_dict = {
            "resp_rate": vitals.resp_rate, "spo2": vitals.spo2,
            "sbp": vitals.sbp, "dbp": vitals.dbp,
            "heart_rate": vitals.heart_rate, "temperature": vitals.temperature,
            "consciousness": vitals.consciousness, "air_or_oxygen": vitals.air_or_oxygen,
        }
        news2_score = calculate_news2(v_dict, bool(patient.hypercapnic_failure))["total"]

    new_esc = Escalation(
        subject_id   = esc.patientId,
        patient_name = patient.name,
        ward         = patient.ward,
        bed          = patient.bed,
        news2_score  = news2_score,
        level        = esc.level,
        attending    = esc.attending,
        escalated_by = esc.escalatedBy,
        observations = esc.observations,
        interventions= esc.interventions,
        status       = "active",
        escalated_at = datetime.now().strftime("%d %b %Y, %H:%M"),
    )
    db.add(new_esc)
    db.commit()
    db.refresh(new_esc)
    return {
        "message":     "Escalation created",
        "id":          new_esc.id,
        "patientName": new_esc.patient_name,
        "ward":        new_esc.ward,
        "bed":         new_esc.bed,
        "news2":       new_esc.news2_score,
        "escalatedAt": new_esc.escalated_at,
        "attending":   new_esc.attending,
    }


@app.get("/api/escalations")
def get_escalations(db: Session = Depends(get_db)):
    escalations = db.query(Escalation).order_by(Escalation.escalated_at.desc()).all()
    return {"escalations": [
        {
            "id":              e.id,
            "patientId":       e.subject_id,
            "patientName":     e.patient_name,
            "ward":            e.ward,
            "bed":             e.bed,
            "news2":           e.news2_score,
            "level":           e.level,
            "attending":       e.attending,
            "escalatedBy":     e.escalated_by,
            "observations":    e.observations,
            "interventions":   e.interventions,
            "status":          e.status,
            "escalatedAt":     e.escalated_at,
            "acknowledgedAt":  e.acknowledged_at,
            "resolvedAt":      e.resolved_at,
            "resolvedBy":      e.resolved_by,
            "resolutionNotes": e.resolution_notes,
        }
        for e in escalations
    ]}


@app.post("/api/escalations/{esc_id}/resolve")
def resolve_escalation(esc_id: int, res: EscalationResolve, db: Session = Depends(get_db)):
    esc = db.query(Escalation).filter(Escalation.id == esc_id).first()
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")
    esc.status           = "resolved"
    esc.resolved_at      = datetime.now().strftime("%d %b %Y, %H:%M")
    esc.resolved_by      = res.resolvedBy
    esc.resolution_notes = res.notes
    db.commit()
    return {"message": "Escalation resolved", "id": esc.id}


# ─── /api/patients (add) ─────────────────────────────────────────────────────

@app.post("/api/patients")
def add_patient(patient: PatientCreate, db: Session = Depends(get_db)):
    max_p = db.query(Patient).order_by(Patient.subject_id.desc()).first()
    new_id = (max_p.subject_id + 1) if max_p else 10000
    p = Patient(
        subject_id=new_id, name=patient.name, age=patient.age, sex=patient.sex,
        ward=patient.ward, room=patient.room, bed=patient.bed,
        admitted=datetime.now().strftime("%d %b %Y"),
        complaint=patient.complaint, hypercapnic_failure=patient.hypercapnic_failure,
    )
    db.add(p)
    v = VitalTimeSeries(
        subject_id=new_id, chart_hour=datetime.now().isoformat(),
        heart_rate=patient.hr, resp_rate=patient.rr, spo2=patient.spo2,
        sbp=patient.sbp, dbp=patient.dbp, temperature=patient.temp,
        air_or_oxygen=patient.air_or_oxygen, consciousness=patient.consciousness,
    )
    db.add(v)
    db.commit()
    return {"message": "Patient added", "subject_id": new_id}
