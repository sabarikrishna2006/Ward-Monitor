-- =============================================================================
-- EWS Schema Migration for Foqal CareOS
-- Run ONCE against Cloud SQL (postgres database)
-- Adds EWS columns to active_patients + creates 6 ews_* tables
-- Instance: healthcare-project-496207:us-central1:foqal-healthcare-cloud-sql-db
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Extend active_patients with EWS-specific fields
-- ---------------------------------------------------------------------------
ALTER TABLE active_patients
    ADD COLUMN IF NOT EXISTS patient_code          VARCHAR(20),
    ADD COLUMN IF NOT EXISTS ward                  VARCHAR(30),
    ADD COLUMN IF NOT EXISTS room                  VARCHAR(20),
    ADD COLUMN IF NOT EXISTS bed                   VARCHAR(20),
    ADD COLUMN IF NOT EXISTS ward_location         VARCHAR(20) NOT NULL DEFAULT 'CCU',
    ADD COLUMN IF NOT EXISTS hypercapnic_failure   SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS diagnosis_short       VARCHAR(80),
    ADD COLUMN IF NOT EXISTS ews_complaint         TEXT;

-- ---------------------------------------------------------------------------
-- 2. ews_vitals_timeseries
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ews_vitals_timeseries (
    id            BIGSERIAL    PRIMARY KEY,
    hadm_id       INTEGER      NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    chart_time    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    heart_rate    NUMERIC(6,2),
    resp_rate     NUMERIC(6,2),
    spo2          NUMERIC(6,2),
    sbp           NUMERIC(6,2),
    dbp           NUMERIC(6,2),
    temperature   NUMERIC(5,2),
    consciousness VARCHAR(1)   NOT NULL DEFAULT 'A',
    air_or_oxygen VARCHAR(10)  NOT NULL DEFAULT 'Air',
    urine_output  NUMERIC(8,2),
    fluid_balance NUMERIC(8,2),
    recorded_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ews_vt_hadm  ON ews_vitals_timeseries (hadm_id);
CREATE INDEX IF NOT EXISTS idx_ews_vt_time  ON ews_vitals_timeseries (hadm_id, chart_time DESC);

-- ---------------------------------------------------------------------------
-- 3. ews_lab_events
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ews_lab_events (
    id          BIGSERIAL    PRIMARY KEY,
    hadm_id     INTEGER      NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    chart_time  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    potassium   NUMERIC(6,3),
    creatinine  NUMERIC(8,3),
    lactate     NUMERIC(6,3),
    inr         NUMERIC(6,3),
    egfr        NUMERIC(7,2),
    alt         NUMERIC(8,2),
    recorded_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ews_le_hadm ON ews_lab_events (hadm_id);
CREATE INDEX IF NOT EXISTS idx_ews_le_time ON ews_lab_events (hadm_id, chart_time DESC);

-- ---------------------------------------------------------------------------
-- 4. ews_medications
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ews_medications (
    id        BIGSERIAL    PRIMARY KEY,
    hadm_id   INTEGER      NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    med_name  VARCHAR(200) NOT NULL,
    dose      VARCHAR(50),
    frequency VARCHAR(20),
    added_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ews_med_hadm ON ews_medications (hadm_id);

-- ---------------------------------------------------------------------------
-- 5. ews_escalations
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ews_escalations (
    id                 BIGSERIAL    PRIMARY KEY,
    hadm_id            INTEGER      NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    patient_name       VARCHAR(200),
    ward               VARCHAR(30),
    bed                VARCHAR(20),
    news2_score        SMALLINT,
    level              VARCHAR(20)  NOT NULL DEFAULT 'nurse',
    attending          VARCHAR(200),
    escalated_by       VARCHAR(200),
    observations       TEXT,
    interventions      TEXT,
    status             VARCHAR(30)  NOT NULL DEFAULT 'active',
    escalated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    acknowledged_at    TIMESTAMPTZ,
    resolved_at        TIMESTAMPTZ,
    resolved_by        VARCHAR(200),
    resolution_notes   TEXT,
    false_alarm        BOOLEAN      NOT NULL DEFAULT FALSE,
    false_alarm_reason TEXT,
    reescalated_at     TIMESTAMPTZ,
    reescalation_note  TEXT
);

CREATE INDEX IF NOT EXISTS idx_ews_esc_hadm   ON ews_escalations (hadm_id);
CREATE INDEX IF NOT EXISTS idx_ews_esc_status ON ews_escalations (status);
CREATE INDEX IF NOT EXISTS idx_ews_esc_time   ON ews_escalations (escalated_at DESC);

-- ---------------------------------------------------------------------------
-- 6. ews_ccu_transfers
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ews_ccu_transfers (
    id                  BIGSERIAL    PRIMARY KEY,
    hadm_id             INTEGER      NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    patient_name        VARCHAR(200),
    diagnosis           TEXT,
    rationale           TEXT,
    recommended_by      VARCHAR(200),
    target_ward         VARCHAR(100) DEFAULT 'General Ward',
    news2_at_submit     SMALLINT,
    stable_window_hours SMALLINT,
    status              VARCHAR(20)  NOT NULL DEFAULT 'pending',
    submitted_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    decided_at          TIMESTAMPTZ,
    decided_by          VARCHAR(200)
);

CREATE INDEX IF NOT EXISTS idx_ews_ct_hadm   ON ews_ccu_transfers (hadm_id);
CREATE INDEX IF NOT EXISTS idx_ews_ct_status ON ews_ccu_transfers (status);

-- ---------------------------------------------------------------------------
-- 7. ews_drug_lab_actions  (NABH DL2 audit trail)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ews_drug_lab_actions (
    id            BIGSERIAL    PRIMARY KEY,
    hadm_id       INTEGER      NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    rule_name     VARCHAR(100),
    severity      VARCHAR(20)  NOT NULL DEFAULT 'WARNING',
    action_taken  VARCHAR(30)  NOT NULL DEFAULT 'hold',
    justification TEXT,
    recorded_by   VARCHAR(200),
    cosigned_by   VARCHAR(200),
    status        VARCHAR(20)  NOT NULL DEFAULT 'recorded',
    recorded_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ews_dla_hadm ON ews_drug_lab_actions (hadm_id);
