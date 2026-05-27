from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Patient(Base):
    __tablename__ = "patients"

    subject_id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    age = Column(Integer)
    sex = Column(String)
    room = Column(String)
    bed = Column(String)
    admitted = Column(String)
    complaint = Column(String)

class VitalTimeSeries(Base):
    __tablename__ = "vitals_timeseries"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    subject_id = Column(Integer, ForeignKey("patients.subject_id"), index=True)
    chart_hour = Column(String, index=True) # Storing as ISO string for simplicity
    heart_rate = Column(Float)
    resp_rate = Column(Float)
    spo2 = Column(Float)
    sbp = Column(Float)
    dbp = Column(Float)
    temperature = Column(Float)

class LabEvent(Base):
    __tablename__ = "lab_events"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    subject_id = Column(Integer, ForeignKey("patients.subject_id"), index=True)
    chart_hour = Column(String, index=True)
    potassium = Column(Float)
    creatinine = Column(Float)
    lactate = Column(Float)
