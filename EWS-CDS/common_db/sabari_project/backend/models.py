from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Numeric, BigInteger, Text, SmallInteger, Date
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Patient(Base):
    """Maps to active_patients — the shared Cloud SQL admission master hub.

    Production schema has id (UUID) as the true PK and hadm_id (INTEGER UNIQUE)
    as the secondary lookup key. We declare hadm_id as PK here so SQLAlchemy can
    do session-level identity tracking by admission ID, which is sufficient for EWS
    use since all EWS queries filter by hadm_id, not the UUID.

    For EWS demo patients, hadm_id == subject_id (both set to the same integer).
    For real MIMIC patients ingested by Ashmit's system, hadm_id is the MIMIC
    admission ID which may differ from subject_id (patient ID).
    """
    __tablename__ = "active_patients"

    # Production PK is `id UUID DEFAULT gen_random_uuid()`.
    # We expose it here as a non-primary mapped column so SQL updates that set
    # encounter_id / summary_id (which reference app_users / app_encounters via UUID FKs)
    # can be issued safely via text() SQL without ORM involvement.
    id                  = Column(UUID(as_uuid=False), unique=True)   # DB PK, let DB default it
    hadm_id             = Column(Integer, primary_key=True, index=True)  # EWS lookup key
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

    # Cross-system bridge FKs — set by discharge hand-off logic, read by Ashmit's system
    encounter_id        = Column(UUID(as_uuid=False))   # FK → app_encounters(id)
    summary_id          = Column(UUID(as_uuid=False))   # FK → app_summaries(id)

    # MIMIC integration — cardiology metrics (added by schema_migration_v2.sql)
    nyha_class          = Column(Integer)          # 1-4, derived from BNP/EF/NEWS2
    lvef_percent        = Column(Integer)          # % from echo; NULL if unavailable
    bnp_baseline        = Column(Numeric(10, 2))   # BNP at admission (pg/mL)

    # Discharge workflow — added by migration 025 / 016_active_patients_expansion.sql
    primary_diagnosis_title = Column(String(255))  # synced from ap_diagnoses on CCU transfer
    discharge_type          = Column(String(20))   # Standard / LAMA / DAMA / Death / Referral
    discharge_time          = Column(DateTime)     # set when patient leaves ward
    los_days                = Column(Numeric(6, 2))  # computed: discharge_time - admit_time
    updated_at              = Column(DateTime)     # required by every handoff UPDATE


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


# ── New ERD schema tables — ews.* (migration 026) ─────────────────────────────
# These live in the `ews` PostgreSQL schema created by migration 026.
# __table_args__ sets schema= so SQLAlchemy emits `ews.table_name` in SQL.

class DrugLabRule(Base):
    """ews.drug_lab_rules — DB-driven rule table replacing YAML-only rules."""
    __tablename__  = "drug_lab_rules"
    __table_args__ = {"schema": "ews", "extend_existing": True}

    rule_id            = Column(UUID(as_uuid=False), primary_key=True)
    hospital_id        = Column(UUID(as_uuid=False))          # NULL = global rule
    rule_name          = Column(String(200), nullable=False)
    trigger_drug       = Column(String(100), nullable=False)
    trigger_lab        = Column(String(100), nullable=False)
    lab_threshold      = Column(Numeric(10, 3), nullable=False)
    comparator         = Column(String(5), nullable=False)     # gt/lt/gte/lte/eq
    severity           = Column(String(20), nullable=False)    # CRITICAL/WARNING/INFO
    recommended_action = Column(String(30), nullable=False)
    clinical_rationale = Column(Text)
    guideline_source   = Column(String(30))
    version            = Column(Integer, default=1)
    effective_date     = Column(Date)
    is_active          = Column(Boolean, default=True)


class DrugLabFlag(Base):
    """ews.drug_lab_flags — per-admission flag records with FK to rule."""
    __tablename__  = "drug_lab_flags"
    __table_args__ = {"schema": "ews", "extend_existing": True}

    flag_id            = Column(UUID(as_uuid=False), primary_key=True)
    admission_id       = Column(UUID(as_uuid=False), nullable=False, index=True)
    rule_id            = Column(UUID(as_uuid=False), nullable=False)
    severity           = Column(String(20), nullable=False)
    trigger_drug_value = Column(String(100))
    trigger_lab_value  = Column(Numeric(10, 3))
    recommended_action = Column(String(30), nullable=False)
    actioned_by        = Column(UUID(as_uuid=False))
    justification      = Column(Text)
    cosigned_by_name   = Column(String(100))
    status             = Column(String(20), default="active")
    flagged_at         = Column(DateTime)
    actioned_at        = Column(DateTime)


class EwsEvent(Base):
    """ews.ews_events — ML-generated trend alerts (NEWS2_RISING, STEP_DOWN_ELIGIBLE, etc.)."""
    __tablename__  = "ews_events"
    __table_args__ = {"schema": "ews", "extend_existing": True}

    id           = Column(UUID(as_uuid=False), primary_key=True)
    admission_id = Column(UUID(as_uuid=False), nullable=False, index=True)
    event_type   = Column(String(40), nullable=False)
    trend_score  = Column(Numeric(6, 3))
    ml_confidence = Column(Numeric(5, 2))
    top_signals  = Column(JSONB)                              # [{param, direction, contribution}]
    status       = Column(String(20), default="pending")
    detected_at  = Column(DateTime)
    actioned_by  = Column(UUID(as_uuid=False))


class DcmAssessment(Base):
    """ews.dcm_assessments — NYHA class, EF, BNP snapshot per CCU admission."""
    __tablename__  = "dcm_assessments"
    __table_args__ = {"schema": "ews", "extend_existing": True}

    id                 = Column(UUID(as_uuid=False), primary_key=True)
    admission_id       = Column(UUID(as_uuid=False), nullable=False, index=True)
    nyha_class         = Column(SmallInteger, nullable=False)
    ef_percent         = Column(Numeric(5, 2))
    baseline_weight_kg = Column(Numeric(6, 2))
    bnp_admission      = Column(Numeric(10, 2))
    edema_grade        = Column(SmallInteger)
    assessed_by        = Column(UUID(as_uuid=False), nullable=False)
    assessed_at        = Column(DateTime)


class FluidBalance(Base):
    """ews.fluid_balance — 8h and 24h fluid balance periods per admission."""
    __tablename__  = "fluid_balance"
    __table_args__ = {"schema": "ews", "extend_existing": True}

    id              = Column(UUID(as_uuid=False), primary_key=True)
    admission_id    = Column(UUID(as_uuid=False), nullable=False, index=True)
    period_hours    = Column(Integer, nullable=False)         # 8 or 24
    intake_ml       = Column(Numeric(8, 1))
    urine_ml        = Column(Numeric(8, 1))
    drain_ml        = Column(Numeric(8, 1))
    net_balance_ml  = Column(Numeric(8, 1))
    daily_weight_kg = Column(Numeric(6, 2))
    recorded_by     = Column(UUID(as_uuid=False), nullable=False)
    recorded_at     = Column(DateTime)


# ── New ERD schema tables — discharge_ai.* (migration 026) ───────────────────

class DischargeSection(Base):
    """discharge_ai.discharge_sections — per-section NABH tracking (15 sections)."""
    __tablename__  = "discharge_sections"
    __table_args__ = {"schema": "discharge_ai", "extend_existing": True}

    section_id       = Column(UUID(as_uuid=False), primary_key=True)
    summary_id       = Column(UUID(as_uuid=False), nullable=False, index=True)
    section_number   = Column(SmallInteger, nullable=False)   # 1–15
    section_name     = Column(String(100), nullable=False)
    ai_content       = Column(Text, nullable=False)
    edited_content   = Column(Text)
    confidence_score = Column(Numeric(4, 3), default=0)
    edited_by        = Column(UUID(as_uuid=False))
    edit_reason      = Column(Text)
    edited_at        = Column(DateTime)


class DischargeAmendment(Base):
    """discharge_ai.discharge_amendments — post-signoff FSM for section corrections."""
    __tablename__  = "discharge_amendments"
    __table_args__ = {"schema": "discharge_ai", "extend_existing": True}

    amendment_id      = Column(UUID(as_uuid=False), primary_key=True)
    summary_id        = Column(UUID(as_uuid=False), nullable=False, index=True)
    new_summary_id    = Column(UUID(as_uuid=False))
    rejected_by       = Column(UUID(as_uuid=False), nullable=False)
    rejection_reason  = Column(Text, nullable=False)
    sections_rejected = Column(Text)                          # JSON array of section numbers
    status            = Column(String(30), default="pending_regen")
    requested_at      = Column(DateTime)
    resolved_at       = Column(DateTime)


# ── hospital_core mirror (read-only) — admission_id FK lookups ────────────────

class HcAdmission(Base):
    """hospital_core.admissions — universal cross-system FK anchor."""
    __tablename__  = "admissions"
    __table_args__ = {"schema": "hospital_core", "extend_existing": True}

    admission_id   = Column(UUID(as_uuid=False), primary_key=True)
    uhid           = Column(String(30), nullable=False)
    hospital_id    = Column(UUID(as_uuid=False), nullable=False)
    ward_id        = Column(UUID(as_uuid=False))
    bed_id         = Column(UUID(as_uuid=False))
    hadm_id        = Column(Integer, unique=True, index=True) # bridge to active_patients
    status         = Column(String(30), default="admitted")
    admitted_at    = Column(DateTime)
    discharged_at  = Column(DateTime)
    updated_at     = Column(DateTime)
