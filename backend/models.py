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
    complaint    = Column(String)
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
