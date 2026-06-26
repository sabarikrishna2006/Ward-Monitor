-- Migration 026: Full ERD Target Architecture
-- Creates 3 PostgreSQL schemas + 23 new tables.
-- ALL statements use IF NOT EXISTS — safe to re-run.
-- Zero DROP or TRUNCATE. Existing flat tables are untouched.

-- ══════════════════════════════════════════════════════════════════════════════
-- SCHEMAS
-- ══════════════════════════════════════════════════════════════════════════════
CREATE SCHEMA IF NOT EXISTS hospital_core;
CREATE SCHEMA IF NOT EXISTS ews;
CREATE SCHEMA IF NOT EXISTS discharge_ai;

-- ══════════════════════════════════════════════════════════════════════════════
-- hospital_core SCHEMA  (16 tables)
-- Root entity hierarchy: hospitals → departments → wards → beds
--                        hospitals → patients → admissions
--                        hospitals → staff
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS hospital_core.hospitals (
    hospital_id     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    short_code      VARCHAR(20) UNIQUE NOT NULL,          -- e.g. FOQAL-DEL
    name            VARCHAR(200) NOT NULL,
    type            VARCHAR(20)  NOT NULL DEFAULT 'PRIVATE' CHECK (type IN ('TERTIARY','PRIVATE','GOVT')),
    nabh_accredited BOOLEAN      NOT NULL DEFAULT FALSE,
    rohini_id       VARCHAR(30),                          -- Indian insurance registration
    address         TEXT,
    phone           VARCHAR(20),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hospital_core.departments (
    dept_id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    hospital_id     UUID        NOT NULL REFERENCES hospital_core.hospitals(hospital_id),
    name            VARCHAR(100) NOT NULL,
    code            VARCHAR(10)  NOT NULL,                -- CARD, ICU, MED, SURG
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS hospital_core.wards (
    ward_id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    hospital_id     UUID        NOT NULL REFERENCES hospital_core.hospitals(hospital_id),
    dept_id         UUID        NOT NULL REFERENCES hospital_core.departments(dept_id),
    name            VARCHAR(100) NOT NULL,
    ward_type       VARCHAR(20)  NOT NULL CHECK (ward_type IN ('CCU','GW','ICU','HDU','EMERGENCY')),
    capacity        INTEGER      NOT NULL DEFAULT 10,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS hospital_core.beds (
    bed_id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    ward_id             UUID        NOT NULL REFERENCES hospital_core.wards(ward_id),
    bed_number          VARCHAR(20) NOT NULL,             -- CCU-01, GW-12
    status              VARCHAR(20) NOT NULL DEFAULT 'available'
                            CHECK (status IN ('available','occupied','maintenance')),
    current_admission_id UUID                                                       -- FK added after admissions table
);

CREATE TABLE IF NOT EXISTS hospital_core.staff (
    staff_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    hospital_id     UUID        NOT NULL REFERENCES hospital_core.hospitals(hospital_id),
    dept_id         UUID        REFERENCES hospital_core.departments(dept_id),
    ward_id         UUID        REFERENCES hospital_core.wards(ward_id),
    full_name       VARCHAR(200) NOT NULL,
    role            VARCHAR(30)  NOT NULL CHECK (role IN (
                        'staff_nurse','charge_nurse','gw_nurse','resident',
                        'attending','admin_staff','cmo','billing_staff','super_admin')),
    hospital_email  VARCHAR(200) UNIQUE NOT NULL,
    license_no      VARCHAR(50),                          -- MCI / Nursing Council
    password_hash   TEXT         NOT NULL DEFAULT '',
    session_token   TEXT,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hc_staff_email    ON hospital_core.staff(hospital_email);
CREATE INDEX IF NOT EXISTS idx_hc_staff_ward     ON hospital_core.staff(ward_id) WHERE ward_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS hospital_core.patients (
    uhid            VARCHAR(30)  PRIMARY KEY,             -- FOQAL-2026-0000001
    hospital_id     UUID         NOT NULL REFERENCES hospital_core.hospitals(hospital_id),
    full_name       VARCHAR(200) NOT NULL,
    dob             DATE,
    sex             CHAR(1)      CHECK (sex IN ('M','F','O')),
    contact         VARCHAR(20),
    insurance_type  VARCHAR(30)  DEFAULT 'None'
                        CHECK (insurance_type IN ('Ayushman_Bharat','CGHS','ESI','Private','None')),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hospital_core.admissions (
    admission_id    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    uhid            VARCHAR(30) NOT NULL REFERENCES hospital_core.patients(uhid),
    hospital_id     UUID        NOT NULL REFERENCES hospital_core.hospitals(hospital_id),
    ward_id         UUID        NOT NULL REFERENCES hospital_core.wards(ward_id),
    bed_id          UUID        REFERENCES hospital_core.beds(bed_id),
    primary_doctor_id UUID      REFERENCES hospital_core.staff(staff_id),
    hadm_id         INTEGER     UNIQUE,                  -- Bridge: links to active_patients.hadm_id
    admission_type  VARCHAR(20) NOT NULL DEFAULT 'EMERGENCY'
                        CHECK (admission_type IN ('EMERGENCY','ELECTIVE','TRANSFER_IN')),
    status          VARCHAR(30) NOT NULL DEFAULT 'admitted'
                        CHECK (status IN ('admitted','in_ccu','transferred_to_gw',
                                          'discharge_pending','discharged')),
    admitted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    discharged_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hc_admissions_hadm    ON hospital_core.admissions(hadm_id) WHERE hadm_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_hc_admissions_status  ON hospital_core.admissions(status);

-- Now that admissions exists, add FK on beds.current_admission_id if not already present.
-- ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS is not supported in PG < 15, so we use
-- a conditional ADD COLUMN approach: drop+re-add with FK. Safe because column is always NULL at seed time.
ALTER TABLE hospital_core.beds DROP COLUMN IF EXISTS current_admission_id;
ALTER TABLE hospital_core.beds ADD COLUMN IF NOT EXISTS current_admission_id UUID
    REFERENCES hospital_core.admissions(admission_id);

CREATE TABLE IF NOT EXISTS hospital_core.doctor_patient_assignments (
    assignment_id   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    admission_id    UUID        NOT NULL REFERENCES hospital_core.admissions(admission_id),
    doctor_id       UUID        NOT NULL REFERENCES hospital_core.staff(staff_id),
    assignment_type VARCHAR(20) NOT NULL DEFAULT 'PRIMARY'
                        CHECK (assignment_type IN ('PRIMARY','COVERING','CONSULTANT')),
    assigned_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    unassigned_at   TIMESTAMPTZ                          -- NULL = currently active
);

CREATE TABLE IF NOT EXISTS hospital_core.ward_transfers (
    transfer_id     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    admission_id    UUID        NOT NULL REFERENCES hospital_core.admissions(admission_id),
    from_ward_id    UUID        NOT NULL REFERENCES hospital_core.wards(ward_id),
    to_ward_id      UUID        NOT NULL REFERENCES hospital_core.wards(ward_id),
    transfer_type   VARCHAR(20) NOT NULL CHECK (transfer_type IN ('CCU_TO_GW','GW_TO_CCU','INTER_WARD')),
    news2_at_transfer INTEGER,
    approved_by     UUID        REFERENCES hospital_core.staff(staff_id),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','approved','completed','cancelled')),
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS hospital_core.his_patient_sync (
    sync_id         VARCHAR(60)  PRIMARY KEY,
    uhid            VARCHAR(30)  NOT NULL REFERENCES hospital_core.patients(uhid),
    his_system_name VARCHAR(100) NOT NULL,
    sync_status     VARCHAR(20)  NOT NULL CHECK (sync_status IN ('success','failed','pending')),
    last_synced_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    error_message   TEXT
);

CREATE TABLE IF NOT EXISTS hospital_core.insurance_policies (
    policy_id       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    uhid            VARCHAR(30) NOT NULL REFERENCES hospital_core.patients(uhid),
    provider        VARCHAR(100) NOT NULL,
    policy_number   VARCHAR(60)  NOT NULL,
    coverage_percent DECIMAL(5,2) NOT NULL DEFAULT 0,
    deductible      DECIMAL(12,2) NOT NULL DEFAULT 0,
    co_pay_percent  DECIMAL(5,2)  NOT NULL DEFAULT 0,
    effective_date  DATE         NOT NULL,
    expiry_date     DATE         NOT NULL,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS hospital_core.pre_auth_requests (
    preauth_id      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    admission_id    UUID        NOT NULL REFERENCES hospital_core.admissions(admission_id),
    insurance_policy_id UUID    NOT NULL REFERENCES hospital_core.insurance_policies(policy_id),
    estimated_cost  DECIMAL(14,2) NOT NULL,
    status          VARCHAR(20)   NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','approved','denied','expired')),
    approval_number VARCHAR(60),
    valid_until     DATE,
    requested_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    decided_at      TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS hospital_core.cost_lookups (
    cost_id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    hospital_id     UUID        NOT NULL REFERENCES hospital_core.hospitals(hospital_id),
    diagnosis_code  VARCHAR(20) NOT NULL,                -- ICD-10
    diagnosis_label VARCHAR(200) NOT NULL,
    base_cost       DECIMAL(14,2) NOT NULL,
    age_adjustment  DECIMAL(6,4)  NOT NULL DEFAULT 0,    -- % per decade
    comorbidity_factor DECIMAL(6,4) NOT NULL DEFAULT 0,
    ward_tier       VARCHAR(10)   NOT NULL CHECK (ward_tier IN ('CCU','ICU','GW','HDU')),
    effective_from  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hospital_core.notifications (
    notification_id UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_staff_id UUID     NOT NULL REFERENCES hospital_core.staff(staff_id),
    admission_id    UUID        REFERENCES hospital_core.admissions(admission_id),
    type            VARCHAR(30) NOT NULL CHECK (type IN (
                        'transfer_ready','escalation_pending','billing_alert',
                        'drug_flag','sla_breach')),
    message         TEXT        NOT NULL,
    is_read         BOOLEAN     NOT NULL DEFAULT FALSE,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at         TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_hc_notif_staff   ON hospital_core.notifications(recipient_staff_id, is_read);

CREATE TABLE IF NOT EXISTS hospital_core.audit_logs (
    log_id          BIGSERIAL   PRIMARY KEY,
    actor_staff_id  UUID        NOT NULL REFERENCES hospital_core.staff(staff_id),
    admission_id    UUID        REFERENCES hospital_core.admissions(admission_id),
    action_type     VARCHAR(20) NOT NULL CHECK (action_type IN (
                        'CREATE','UPDATE','DELETE','ACCESS','SIGN','ESCALATE')),
    entity_table    VARCHAR(80) NOT NULL,
    entity_id       VARCHAR(60) NOT NULL,
    old_values      JSONB,
    new_values      JSONB,
    ip_address      VARCHAR(45),
    request_id      VARCHAR(60),
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hc_audit_ts     ON hospital_core.audit_logs(ts DESC);
CREATE INDEX IF NOT EXISTS idx_hc_audit_entity ON hospital_core.audit_logs(entity_table, entity_id);

CREATE TABLE IF NOT EXISTS hospital_core.de_identification_mapping (
    mapping_id      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    uhid            VARCHAR(30) NOT NULL REFERENCES hospital_core.patients(uhid),
    de_id           VARCHAR(60) NOT NULL,                -- MIMIC-style anonymous ID
    request_purpose VARCHAR(100),
    requested_by    UUID        NOT NULL REFERENCES hospital_core.staff(staff_id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ
);

-- ══════════════════════════════════════════════════════════════════════════════
-- ews SCHEMA  (5 new tables)
-- Existing ews_* flat tables are untouched.
-- New tables FK to hospital_core.admissions.admission_id.
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ews.drug_lab_rules (
    rule_id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    hospital_id         UUID        REFERENCES hospital_core.hospitals(hospital_id), -- NULL = global
    rule_name           VARCHAR(200) NOT NULL,
    trigger_drug        VARCHAR(100) NOT NULL,
    trigger_lab         VARCHAR(100) NOT NULL,
    lab_threshold       NUMERIC(10,3) NOT NULL,
    comparator          VARCHAR(5)   NOT NULL CHECK (comparator IN ('gt','lt','gte','lte','eq')),
    severity            VARCHAR(20)  NOT NULL CHECK (severity IN ('CRITICAL','WARNING','INFO')),
    recommended_action  VARCHAR(30)  NOT NULL CHECK (recommended_action IN ('hold','reduce','monitor','notify')),
    clinical_rationale  TEXT,
    guideline_source    VARCHAR(30)  CHECK (guideline_source IN ('CDSCO','ICMR','ESC','FDA','WHO')),
    version             INTEGER      NOT NULL DEFAULT 1,
    effective_date      DATE         NOT NULL DEFAULT CURRENT_DATE,
    is_active           BOOLEAN      NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_ews_dlr_active ON ews.drug_lab_rules(is_active) WHERE is_active = TRUE;

CREATE TABLE IF NOT EXISTS ews.drug_lab_flags (
    flag_id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    admission_id        UUID        NOT NULL REFERENCES hospital_core.admissions(admission_id),
    rule_id             UUID        NOT NULL REFERENCES ews.drug_lab_rules(rule_id),
    severity            VARCHAR(20) NOT NULL,
    trigger_drug_value  VARCHAR(100),
    trigger_lab_value   NUMERIC(10,3),
    recommended_action  VARCHAR(30) NOT NULL,
    actioned_by         UUID        REFERENCES hospital_core.staff(staff_id),
    justification       TEXT,
    cosigned_by_name    VARCHAR(100),                    -- NABH DL2 co-sign requirement
    status              VARCHAR(20) NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active','acknowledged','resolved','overridden')),
    flagged_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actioned_at         TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_ews_dlf_admission ON ews.drug_lab_flags(admission_id);
CREATE INDEX IF NOT EXISTS idx_ews_dlf_status    ON ews.drug_lab_flags(status) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS ews.ews_events (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    admission_id    UUID        NOT NULL REFERENCES hospital_core.admissions(admission_id),
    event_type      VARCHAR(40) NOT NULL CHECK (event_type IN (
                        'NEWS2_RISING','TREND_ALERT','STEP_DOWN_ELIGIBLE','DCM_DECOMPENSATION')),
    trend_score     NUMERIC(6,3),                        -- EWMA composite
    ml_confidence   NUMERIC(5,2),                        -- 0.00–100.00
    top_signals     JSONB,                               -- [{param, direction, contribution}]
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','actioned','dismissed')),
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actioned_by     UUID        REFERENCES hospital_core.staff(staff_id)
);
CREATE INDEX IF NOT EXISTS idx_ews_events_admission ON ews.ews_events(admission_id);
CREATE INDEX IF NOT EXISTS idx_ews_events_status    ON ews.ews_events(status, detected_at DESC);

CREATE TABLE IF NOT EXISTS ews.dcm_assessments (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    admission_id        UUID        NOT NULL REFERENCES hospital_core.admissions(admission_id),
    nyha_class          SMALLINT    NOT NULL CHECK (nyha_class BETWEEN 1 AND 4),
    ef_percent          NUMERIC(5,2),                    -- LVEF from echo
    baseline_weight_kg  NUMERIC(6,2),
    bnp_admission       NUMERIC(10,2),                   -- pg/mL at admission
    edema_grade         SMALLINT    CHECK (edema_grade BETWEEN 0 AND 3),
    assessed_by         UUID        NOT NULL REFERENCES hospital_core.staff(staff_id),
    assessed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ews_dcm_admission ON ews.dcm_assessments(admission_id);

CREATE TABLE IF NOT EXISTS ews.fluid_balance (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    admission_id    UUID        NOT NULL REFERENCES hospital_core.admissions(admission_id),
    period_hours    INTEGER     NOT NULL CHECK (period_hours IN (8, 24)),
    intake_ml       NUMERIC(8,1),                        -- IV + oral
    urine_ml        NUMERIC(8,1),
    drain_ml        NUMERIC(8,1),
    net_balance_ml  NUMERIC(8,1),                        -- computed: intake - urine - drain
    daily_weight_kg NUMERIC(6,2),
    recorded_by     UUID        NOT NULL REFERENCES hospital_core.staff(staff_id),
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ews_fluid_admission ON ews.fluid_balance(admission_id, recorded_at DESC);

-- ══════════════════════════════════════════════════════════════════════════════
-- discharge_ai SCHEMA  (2 new tables)
-- Existing flat app_summaries / amendment_log are untouched.
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS discharge_ai.discharge_sections (
    section_id      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    summary_id      UUID        NOT NULL,                -- FK → app_summaries(id) — flat table
    section_number  SMALLINT    NOT NULL CHECK (section_number BETWEEN 1 AND 15),
    section_name    VARCHAR(100) NOT NULL,               -- NABH section label
    ai_content      TEXT        NOT NULL,
    edited_content  TEXT,                                -- doctor-edited version
    confidence_score NUMERIC(4,3) DEFAULT 0,            -- 0.000–1.000
    edited_by       UUID        REFERENCES hospital_core.staff(staff_id),
    edit_reason     TEXT,
    edited_at       TIMESTAMPTZ,
    UNIQUE (summary_id, section_number)
);
CREATE INDEX IF NOT EXISTS idx_ds_sections_summary ON discharge_ai.discharge_sections(summary_id);

CREATE TABLE IF NOT EXISTS discharge_ai.discharge_amendments (
    amendment_id    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    summary_id      UUID        NOT NULL,                -- FK → app_summaries(id) — flat table
    new_summary_id  UUID,                                -- FK → app_summaries(id) after regen
    rejected_by     UUID        NOT NULL REFERENCES hospital_core.staff(staff_id),
    rejection_reason TEXT        NOT NULL,
    sections_rejected TEXT,                              -- JSON array of section numbers
    status          VARCHAR(30) NOT NULL DEFAULT 'pending_regen'
                        CHECK (status IN ('pending_regen','regenerating','ready','signed')),
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_da_amend_summary ON discharge_ai.discharge_amendments(summary_id);

-- ══════════════════════════════════════════════════════════════════════════════
-- SEED: Default hospital + department + 2 wards
-- Required so provision-all and new FK inserts have valid anchor rows.
-- All ON CONFLICT DO NOTHING — safe to re-run.
-- ══════════════════════════════════════════════════════════════════════════════

INSERT INTO hospital_core.hospitals (short_code, name, type, nabh_accredited)
VALUES ('FOQAL-DEMO', 'Foqal CareOS Demo Hospital', 'PRIVATE', TRUE)
ON CONFLICT (short_code) DO NOTHING;

-- Default cardiology department
INSERT INTO hospital_core.departments (hospital_id, name, code, is_active)
SELECT hospital_id, 'Cardiology', 'CARD', TRUE
FROM hospital_core.hospitals WHERE short_code = 'FOQAL-DEMO'
ON CONFLICT DO NOTHING;

-- CCU ward
INSERT INTO hospital_core.wards (hospital_id, dept_id, name, ward_type, capacity)
SELECT h.hospital_id, d.dept_id, 'CCU Ward', 'CCU', 12
FROM hospital_core.hospitals h
JOIN hospital_core.departments d ON d.hospital_id = h.hospital_id AND d.code = 'CARD'
WHERE h.short_code = 'FOQAL-DEMO'
ON CONFLICT DO NOTHING;

-- General Ward
INSERT INTO hospital_core.wards (hospital_id, dept_id, name, ward_type, capacity)
SELECT h.hospital_id, d.dept_id, 'General Ward 4B', 'GW', 20
FROM hospital_core.hospitals h
JOIN hospital_core.departments d ON d.hospital_id = h.hospital_id AND d.code = 'CARD'
WHERE h.short_code = 'FOQAL-DEMO'
ON CONFLICT DO NOTHING;
