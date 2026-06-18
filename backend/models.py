from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class Patient(Base):
    __tablename__ = "patients"

    subject_id   = Column(Integer, primary_key=True, index=True)
    patient_code = Column(String(20))
    name         = Column(String)
    age          = Column(Integer)
    sex          = Column(String)
    ward         = Column(String, default="Ward 4B")
    room         = Column(String)
    bed          = Column(String)
    admitted     = Column(String)
    complaint    = Column(String)          # full diagnosis text (→ MIMIC ICD long title)
    diagnosis_short = Column(String(60))   # short chip for dashboard, e.g. "DCM · HFrEF (EF 25%)"
    # CCU = Critical Care Unit (continuous monitoring); GENERAL_WARD = stepped-down (slower cadence)
    ward_location   = Column(String(20), default="CCU")
    hypercapnic_failure = Column(Integer, default=0)


class VitalTimeSeries(Base):
    __tablename__ = "vitals_timeseries"

    id           = Column(Integer, primary_key=True, index=True, autoincrement=True)
    subject_id   = Column(Integer, ForeignKey("patients.subject_id"), index=True)
    chart_hour   = Column(String, index=True)
    heart_rate   = Column(Float)
    resp_rate    = Column(Float)
    spo2         = Column(Float)
    sbp          = Column(Float)
    dbp          = Column(Float)
    temperature  = Column(Float)
    consciousness    = Column(String, default="A")
    air_or_oxygen    = Column(String, default="Air")
    # DCM / heart-failure nursing params (→ MIMIC outputevents / intake-output)
    urine_output  = Column(Float)   # ml over last ~4h
    fluid_balance = Column(Float)   # net ml over last 24h (positive = fluid overload)


class LabEvent(Base):
    __tablename__ = "lab_events"

    id           = Column(Integer, primary_key=True, index=True, autoincrement=True)
    subject_id   = Column(Integer, ForeignKey("patients.subject_id"), index=True)
    chart_hour   = Column(String, index=True)
    potassium    = Column(Float)
    creatinine   = Column(Float)
    lactate      = Column(Float)
    inr          = Column(Float)
    egfr         = Column(Float)
    alt          = Column(Float)


class Medication(Base):
    __tablename__ = "medications"

    id           = Column(Integer, primary_key=True, index=True, autoincrement=True)
    subject_id   = Column(Integer, ForeignKey("patients.subject_id"), index=True)
    med_name     = Column(String)
    dose         = Column(String)
    frequency    = Column(String)


class Escalation(Base):
    __tablename__ = "escalations"

    id               = Column(Integer, primary_key=True, index=True, autoincrement=True)
    subject_id       = Column(Integer, ForeignKey("patients.subject_id"), index=True)
    patient_name     = Column(String)
    ward             = Column(String)
    bed              = Column(String)
    news2_score      = Column(Integer)
    level            = Column(String)           # nurse | doctor | code_blue
    attending        = Column(String)
    escalated_by     = Column(String)
    observations     = Column(String)
    interventions    = Column(String)
    status              = Column(String, default="active")  # active | acknowledged | resolved | false_alarm
    escalated_at        = Column(String)
    acknowledged_at     = Column(String, nullable=True)
    resolved_at         = Column(String, nullable=True)
    resolved_by         = Column(String, nullable=True)
    resolution_notes    = Column(String, nullable=True)
    false_alarm         = Column(Boolean, default=False)
    false_alarm_reason  = Column(String, nullable=True)
    reescalated_at      = Column(String, nullable=True)   # set when 15-min SLA breach auto-bumps level
    reescalation_note   = Column(String, nullable=True)


class CcuTransfer(Base):
    """CCU → General Ward step-down recommendation (nurse raises, Head Nurse approves)."""
    __tablename__ = "ccu_transfers"

    id                  = Column(Integer, primary_key=True, index=True, autoincrement=True)
    subject_id          = Column(Integer, ForeignKey("patients.subject_id"), index=True)
    patient_name        = Column(String)
    diagnosis           = Column(String)
    rationale           = Column(String)
    recommended_by      = Column(String)
    target_ward         = Column(String, default="General Ward")
    news2_at_submit     = Column(Integer)
    stable_window_hours = Column(Integer)
    status              = Column(String, default="pending")  # pending | approved | rejected | withdrawn
    submitted_at        = Column(String)
    decided_at          = Column(String, nullable=True)
    decided_by          = Column(String, nullable=True)


class DrugLabAction(Base):
    """Records the action taken on a Drug-Lab flag (DL2 → DL2b) for the NABH audit trail."""
    __tablename__ = "drug_lab_actions"

    id            = Column(Integer, primary_key=True, index=True, autoincrement=True)
    subject_id    = Column(Integer, ForeignKey("patients.subject_id"), index=True)
    rule_name     = Column(String)
    severity      = Column(String)                       # CRITICAL | WARNING
    action_taken  = Column(String)                       # override | hold | pharmacist
    justification = Column(String, nullable=True)
    recorded_by   = Column(String)
    cosigned_by   = Column(String, nullable=True)        # Head Nurse, required for T1 override
    status        = Column(String, default="recorded")   # recorded | resolved
    recorded_at   = Column(String)
