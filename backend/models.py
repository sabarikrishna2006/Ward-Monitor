from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Numeric, BigInteger
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Patient(Base):
    """Maps to active_patients — the shared Cloud SQL admission master hub.

    For EWS demo patients, hadm_id == subject_id (both set to the same integer).
    For real MIMIC patients ingested by Ashmit's system, hadm_id is the MIMIC
    admission ID which may differ from subject_id (patient ID).
    """
    __tablename__ = "active_patients"

    hadm_id             = Column(Integer, primary_key=True, index=True)
    subject_id          = Column(Integer)

    # Demographics — mapped from old Patient fields
    anchor_age          = Column(Integer)          # was: age
    gender              = Column(String(1))        # was: sex (stored as 'M'/'F')

    # EWS-specific fields (added via ews_migration.sql)
    patient_name        = Column(String(200))      # was: name
    patient_code        = Column(String(20))
    ward                = Column(String(30), default="Ward 4B")
    room                = Column(String(20))
    bed                 = Column(String(20))
    ward_location       = Column(String(20), default="CCU")
    hypercapnic_failure = Column(Integer, default=0)
    diagnosis_short     = Column(String(80))
    ews_complaint       = Column(String)           # was: complaint

    # Shared fields with Ashmit's discharge AI
    admitting_diagnosis = Column(String)
    admit_time          = Column(DateTime)         # was: admitted (String)
    status              = Column(String(30), default="active")
    data_fetch_status   = Column(String(20), default="fetched")

    # MIMIC integration — cardiology metrics (added by schema_migration_v2.sql)
    nyha_class          = Column(Integer)          # 1-4, derived from BNP/EF/NEWS2
    lvef_percent        = Column(Integer)          # % from echo; NULL if unavailable
    bnp_baseline        = Column(Numeric(10, 2))   # BNP at admission (pg/mL)


class VitalTimeSeries(Base):
    __tablename__ = "ews_vitals_timeseries"

    id            = Column(Integer, primary_key=True, index=True, autoincrement=True)
    hadm_id       = Column(Integer, index=True)   # was: subject_id FK
    chart_time    = Column(DateTime, index=True)  # was: chart_hour (String)
    heart_rate    = Column(Float)
    resp_rate     = Column(Float)
    spo2          = Column(Float)
    sbp           = Column(Float)
    dbp           = Column(Float)
    temperature   = Column(Float)
    consciousness = Column(String(1), default="A")
    air_or_oxygen = Column(String(10), default="Air")
    urine_output  = Column(Float)
    fluid_balance = Column(Float)
    weight_kg     = Column(Numeric(6, 2))          # daily weight (kg)


class LabEvent(Base):
    __tablename__ = "ews_lab_events"

    id         = Column(Integer, primary_key=True, index=True, autoincrement=True)
    hadm_id    = Column(Integer, index=True)
    chart_time = Column(DateTime, index=True)
    potassium  = Column(Float)
    creatinine = Column(Float)
    lactate    = Column(Float)
    inr        = Column(Float)
    egfr       = Column(Float)
    alt        = Column(Float)
    # MIMIC integration — added by schema_migration_v2.sql
    bnp        = Column(Numeric(10, 2))   # BNP pg/mL (itemids 50963, 51921)
    troponin   = Column(Numeric(10, 4))   # Troponin T ng/mL (itemid 51003)
    sodium     = Column(Numeric(6, 2))    # Na mmol/L (itemid 50983)
    hemoglobin = Column(Numeric(6, 2))    # Hgb g/dL (itemid 51222)


class Medication(Base):
    __tablename__ = "ews_medications"

    id        = Column(Integer, primary_key=True, index=True, autoincrement=True)
    hadm_id   = Column(Integer, index=True)
    med_name  = Column(String)
    dose      = Column(String)
    frequency = Column(String)


class Escalation(Base):
    __tablename__ = "ews_escalations"

    id                 = Column(Integer, primary_key=True, index=True, autoincrement=True)
    hadm_id            = Column(Integer, index=True)
    patient_name       = Column(String)
    ward               = Column(String)
    bed                = Column(String)
    news2_score        = Column(Integer)
    level              = Column(String)
    attending          = Column(String)
    escalated_by       = Column(String)
    observations       = Column(String)
    interventions      = Column(String)
    status             = Column(String, default="active")
    escalated_at       = Column(DateTime)
    acknowledged_at    = Column(DateTime, nullable=True)
    resolved_at        = Column(DateTime, nullable=True)
    resolved_by        = Column(String, nullable=True)
    resolution_notes   = Column(String, nullable=True)
    false_alarm        = Column(Boolean, default=False)
    false_alarm_reason = Column(String, nullable=True)
    reescalated_at     = Column(DateTime, nullable=True)
    reescalation_note  = Column(String, nullable=True)


class CcuTransfer(Base):
    """CCU to General Ward step-down recommendation."""
    __tablename__ = "ews_ccu_transfers"

    id                  = Column(Integer, primary_key=True, index=True, autoincrement=True)
    hadm_id             = Column(Integer, index=True)
    patient_name        = Column(String)
    diagnosis           = Column(String)
    rationale           = Column(String)
    recommended_by      = Column(String)
    target_ward         = Column(String, default="General Ward")
    news2_at_submit     = Column(Integer)
    stable_window_hours = Column(Integer)
    status              = Column(String, default="pending")
    submitted_at        = Column(DateTime)
    decided_at          = Column(DateTime, nullable=True)
    decided_by          = Column(String, nullable=True)


class DrugLabAction(Base):
    """Drug-Lab flag action — NABH DL2 audit trail."""
    __tablename__ = "ews_drug_lab_actions"

    id            = Column(Integer, primary_key=True, index=True, autoincrement=True)
    hadm_id       = Column(Integer, index=True)
    rule_name     = Column(String)
    severity      = Column(String)
    action_taken  = Column(String)
    justification = Column(String, nullable=True)
    recorded_by   = Column(String)
    cosigned_by   = Column(String, nullable=True)
    status        = Column(String, default="recorded")
    recorded_at   = Column(DateTime)


# ── Read-only ORM mirrors of Ashmit's ap_* tables ───────────────────────────
# These are declared so SQLAlchemy can query them; we never create/drop them.

class ApChartEvent(Base):
    __tablename__ = "ap_chartevents"
    __table_args__ = {"extend_existing": True}

    id        = Column(BigInteger, primary_key=True)
    hadm_id   = Column(Integer, index=True)
    itemid    = Column(Integer)
    charttime = Column(DateTime)
    valuenum  = Column(Numeric(14, 4))
    valueuom  = Column(String)


class ApLabEvent(Base):
    __tablename__ = "ap_labevents"
    __table_args__ = {"extend_existing": True}

    labevent_id = Column(BigInteger, primary_key=True)
    hadm_id     = Column(Integer, index=True)
    itemid      = Column(Integer)
    charttime   = Column(DateTime)
    valuenum    = Column(Numeric(14, 4))
    valueuom    = Column(String)


class ApPrescription(Base):
    __tablename__ = "ap_prescriptions"
    __table_args__ = {"extend_existing": True}

    id              = Column(BigInteger, primary_key=True)
    hadm_id         = Column(Integer, index=True)
    drug            = Column(String)
    drug_type       = Column(String)
    dose_val_rx     = Column(String)
    dose_unit_rx    = Column(String)
    doses_per_24_hrs = Column(Float)
    route           = Column(String)
    starttime       = Column(DateTime)
    stoptime        = Column(DateTime)


class ApOutputEvent(Base):
    __tablename__ = "ap_outputevents"
    __table_args__ = {"extend_existing": True}

    id        = Column(BigInteger, primary_key=True)
    hadm_id   = Column(Integer, index=True)
    itemid    = Column(Integer)
    charttime = Column(DateTime)
    value     = Column(Float)
    valueuom  = Column(String)
