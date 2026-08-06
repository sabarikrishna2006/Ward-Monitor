BEGIN;

-- Extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";     -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements"; -- query performance





-- Shared trigger: auto-update updated_at on any row change

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;




-- 1.1  USERS

CREATE TABLE IF NOT EXISTS app_users (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    hospital_email  VARCHAR(255) NOT NULL,
    role            VARCHAR(30)  NOT NULL
        CHECK (role IN ('Doctor', 'Admin Staff', 'Billing Staff', 'Super Admin')),
    full_name       VARCHAR(120) NOT NULL,
    password_hash   TEXT         NOT NULL,
    session_token   TEXT,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (hospital_email, role)
);

CREATE INDEX IF NOT EXISTS idx_users_email ON app_users (hospital_email);
CREATE INDEX IF NOT EXISTS idx_users_role  ON app_users (role);

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON app_users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 1.2  ACTIVE PATIENTS  (master hub — one row per registered hadm_id)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS active_patients (
    id                          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    hadm_id                     INTEGER      NOT NULL,
    subject_id                  INTEGER      NOT NULL,

    -- Demographics snapshot (denormalised from BigQuery for fast list view)
    gender                      CHAR(1),
    anchor_age                  SMALLINT,
    race                        VARCHAR(80),
    marital_status              VARCHAR(50),
    language                    VARCHAR(20),
    insurance                   VARCHAR(50),

    -- Admission metadata
    admission_type              VARCHAR(50),
    admission_location          VARCHAR(60),
    discharge_location          VARCHAR(60),
    admit_time                  TIMESTAMPTZ,
    discharge_time              TIMESTAMPTZ,
    los_days                    NUMERIC(6,2),
    hospital_expire_flag        SMALLINT     CHECK (hospital_expire_flag IN (0, 1)),
    admitting_diagnosis         TEXT,
    edregtime                   TIMESTAMPTZ,
    edouttime                   TIMESTAMPTZ,

    -- Denormalised fast-access billing fields
    primary_diagnosis_code      VARCHAR(10),
    primary_diagnosis_title     TEXT,
    principal_drg_code          VARCHAR(10),
    principal_drg_description   TEXT,
    drg_severity                SMALLINT,
    drg_mortality               SMALLINT,

    -- App workflow status
    status                      VARCHAR(30)  NOT NULL DEFAULT 'active'
        CHECK (status IN (
            'active', 'data_fetching', 'data_ready',
            'summary_generated', 'signed_off', 'archived'
        )),
    discharge_type              VARCHAR(20)
        CHECK (discharge_type IN ('Standard', 'LAMA', 'DAMA', 'Death', 'Referral')),
    assigned_doctor_id          UUID         REFERENCES app_users (id) ON DELETE SET NULL,
    created_by_staff_id         UUID         REFERENCES app_users (id) ON DELETE SET NULL,

    -- BigQuery fetch tracking
    data_fetch_status           VARCHAR(20)  NOT NULL DEFAULT 'pending'
        CHECK (data_fetch_status IN ('pending', 'fetching', 'fetched', 'partial', 'failed')),
    data_fetched_at             TIMESTAMPTZ,
    fetch_round2_done           BOOLEAN      NOT NULL DEFAULT FALSE,
    fetch_icu_done              BOOLEAN      NOT NULL DEFAULT FALSE,
    fetch_error                 TEXT,

    -- FK links to encounter/summary (set after creation)
    encounter_id                UUID,
    summary_id                  UUID,

    -- Claims / sign-off
    claim_verification_status   VARCHAR(30)  NOT NULL DEFAULT 'Needs Review'
        CHECK (claim_verification_status IN ('Needs Review', 'Verified', 'Manual')),
    nli_score                   NUMERIC(5,4),
    signed_by                   UUID         REFERENCES app_users (id) ON DELETE SET NULL,
    signed_at                   TIMESTAMPTZ,

    created_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_active_patients_hadm_id UNIQUE (hadm_id)
);

-- General lookup
CREATE INDEX IF NOT EXISTS idx_ap_subject_id       ON active_patients (subject_id);
CREATE INDEX IF NOT EXISTS idx_ap_status           ON active_patients (status);
CREATE INDEX IF NOT EXISTS idx_ap_fetch_status     ON active_patients (data_fetch_status);
CREATE INDEX IF NOT EXISTS idx_ap_assigned_doctor  ON active_patients (assigned_doctor_id);
CREATE INDEX IF NOT EXISTS idx_ap_created_by_staff ON active_patients (created_by_staff_id);
-- Partial indexes for queue views (avoids full scans on filtered lists)
CREATE INDEX IF NOT EXISTS idx_ap_queue_active     ON active_patients (created_at DESC)
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_ap_queue_review     ON active_patients (updated_at DESC)
    WHERE status = 'summary_generated';
CREATE INDEX IF NOT EXISTS idx_ap_fetch_pending    ON active_patients (created_at)
    WHERE data_fetch_status IN ('pending', 'failed');

CREATE TRIGGER trg_active_patients_updated_at
    BEFORE UPDATE ON active_patients
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 1.3  ENCOUNTERS
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_encounters (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    hadm_id          INTEGER      NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    status           VARCHAR(40)  NOT NULL DEFAULT 'Pending Ingestion'
        CHECK (status IN (
            'Pending Ingestion', 'Processing', 'Data Incomplete',
            'Ready for Review', 'Awaiting Confirmation',
            'Verifying Claims', 'Signed Off', 'Revision Requested'
        )),
    complexity       VARCHAR(20)
        CHECK (complexity IN ('Low', 'Medium', 'High')),
    assigned_to      UUID         REFERENCES app_users (id) ON DELETE SET NULL,
    version          INTEGER      NOT NULL DEFAULT 1,
    last_accessed_at TIMESTAMPTZ,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_encounters_hadm_id UNIQUE (hadm_id)
);

CREATE INDEX IF NOT EXISTS idx_enc_status      ON app_encounters (status);
CREATE INDEX IF NOT EXISTS idx_enc_assigned_to ON app_encounters (assigned_to);
CREATE INDEX IF NOT EXISTS idx_enc_updated     ON app_encounters (updated_at DESC)
    WHERE status IN ('Ready for Review', 'Awaiting Confirmation');

CREATE TRIGGER trg_encounters_updated_at
    BEFORE UPDATE ON app_encounters
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Add FK from active_patients.encounter_id once app_encounters exists
ALTER TABLE active_patients
    ADD CONSTRAINT fk_ap_encounter_id
    FOREIGN KEY (encounter_id) REFERENCES app_encounters (id) ON DELETE SET NULL
    NOT VALID;          -- NOT VALID: validated lazily, no full-table lock

-- ---------------------------------------------------------------------------
-- 1.4  SUMMARIES
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_summaries (
    id                        UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    encounter_id              UUID         NOT NULL
        REFERENCES app_encounters (id) ON DELETE CASCADE,
    hadm_id                   INTEGER      NOT NULL,
    content                   TEXT,
    clinical_context          TEXT,
    nli_score                 NUMERIC(5,4),
    claim_verification_status VARCHAR(30)  NOT NULL DEFAULT 'Needs Review'
        CHECK (claim_verification_status IN ('Needs Review', 'Verified', 'Manual')),
    signed_by                 UUID         REFERENCES app_users (id) ON DELETE SET NULL,
    signed_at                 TIMESTAMPTZ,
    created_at                TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_summaries_encounter_id UNIQUE (encounter_id)
);

CREATE INDEX IF NOT EXISTS idx_sum_hadm_id   ON app_summaries (hadm_id);
CREATE INDEX IF NOT EXISTS idx_sum_signed_by ON app_summaries (signed_by);

CREATE TRIGGER trg_summaries_updated_at
    BEFORE UPDATE ON app_summaries
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Back-fill FK from active_patients.summary_id
ALTER TABLE active_patients
    ADD CONSTRAINT fk_ap_summary_id
    FOREIGN KEY (summary_id) REFERENCES app_summaries (id) ON DELETE SET NULL
    NOT VALID;

-- ---------------------------------------------------------------------------
-- 1.5  UPLOADED FILES
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_uploaded_files (
    id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    hadm_id        INTEGER      NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    encounter_id   UUID         REFERENCES app_encounters (id) ON DELETE SET NULL,
    file_type      VARCHAR(30)  NOT NULL
        CHECK (file_type IN (
            'labs', 'meds', 'notes', 'diagnoses', 'procedures',
            'icu', 'microbiology', 'transfers', 'icustays', 'drg',
            'emar', 'services', 'pharmacy', 'poe', 'fluids',
            'vitals', 'emar_detail', 'datetime'
        )),
    file_name      VARCHAR(255) NOT NULL,
    file_size      BIGINT,
    gcs_path       TEXT,
    indexed_status VARCHAR(20)  NOT NULL DEFAULT 'pending'
        CHECK (indexed_status IN ('pending', 'indexed', 'failed')),
    uploaded_by    UUID         REFERENCES app_users (id) ON DELETE SET NULL,
    upload_date    DATE,
    uploaded_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_files_hadm_id   ON app_uploaded_files (hadm_id);
CREATE INDEX IF NOT EXISTS idx_files_encounter ON app_uploaded_files (encounter_id);
CREATE INDEX IF NOT EXISTS idx_files_type      ON app_uploaded_files (file_type);

-- ---------------------------------------------------------------------------
-- 1.6  AUDIT LOG  (append-only, never updated)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_audit_log (
    id         BIGSERIAL    PRIMARY KEY,
    action     VARCHAR(80)  NOT NULL,
    hadm_id    INTEGER,
    user_id    UUID         REFERENCES app_users (id) ON DELETE SET NULL,
    details    JSONB,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_hadm_id ON app_audit_log (hadm_id);
CREATE INDEX IF NOT EXISTS idx_audit_user_id ON app_audit_log (user_id);
CREATE INDEX IF NOT EXISTS idx_audit_action  ON app_audit_log (action);
CREATE INDEX IF NOT EXISTS idx_audit_created ON app_audit_log (created_at DESC);

-- ---------------------------------------------------------------------------
-- 1.7  SETTINGS  (singleton — enforced by CHECK id = 1)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_settings (
    id                       INTEGER      PRIMARY KEY DEFAULT 1
        CONSTRAINT chk_settings_singleton CHECK (id = 1),
    hospital_name            VARCHAR(120),
    wing                     VARCHAR(60),
    city                     VARCHAR(60),
    mci_nabh_number          VARCHAR(40),
    footer_disclaimer        TEXT,
    nli_entailment_threshold NUMERIC(4,3) NOT NULL DEFAULT 0.5,
    k_retrieved_chunks       SMALLINT     NOT NULL DEFAULT 5,
    dense_retrieval_weight   NUMERIC(4,3) NOT NULL DEFAULT 0.7,
    auto_notify_doctor       BOOLEAN      NOT NULL DEFAULT FALSE,
    updated_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

INSERT INTO app_settings (id)
    VALUES (1)
    ON CONFLICT DO NOTHING;

CREATE TRIGGER trg_settings_updated_at
    BEFORE UPDATE ON app_settings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- =============================================================================
-- SECTION 2: CLINICAL DATA TABLES  (fetched from BigQuery MIMIC-IV v3.1)
--
-- Naming: ap_<mimic_table>
-- Every table:
--   • FK → active_patients(hadm_id) ON DELETE CASCADE
--   • source_fetched_at TIMESTAMPTZ  (when this row was pulled from BigQuery)
--   • INSERT … ON CONFLICT DO NOTHING  (idempotent; safe to re-fetch)
--   • Index on (hadm_id)  +  (hadm_id, time_col DESC) for tab queries
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 2.1  ADMISSIONS  (admissions + patients merged)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ap_admissions (
    hadm_id              INTEGER     PRIMARY KEY
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    subject_id           INTEGER     NOT NULL,

    -- From mimiciv_hosp.admissions
    admittime            TIMESTAMPTZ,
    dischtime            TIMESTAMPTZ,
    deathtime            TIMESTAMPTZ,
    admission_type       VARCHAR(50),
    admit_provider_id    VARCHAR(20),
    admission_location   VARCHAR(60),
    discharge_location   VARCHAR(60),
    insurance            VARCHAR(50),
    language             VARCHAR(20),
    marital_status       VARCHAR(50),
    race                 VARCHAR(80),
    edregtime            TIMESTAMPTZ,
    edouttime            TIMESTAMPTZ,
    hospital_expire_flag SMALLINT    CHECK (hospital_expire_flag IN (0, 1)),

    -- From mimiciv_hosp.patients
    gender               CHAR(1),
    anchor_age           SMALLINT,
    anchor_year          SMALLINT,
    anchor_year_group    VARCHAR(20),
    dod                  DATE,

    source_fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_apadm_subject_id ON ap_admissions (subject_id);

-- ---------------------------------------------------------------------------
-- 2.2  DIAGNOSES
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ap_diagnoses (
    id                BIGSERIAL   PRIMARY KEY,
    hadm_id           INTEGER     NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    subject_id        INTEGER     NOT NULL,
    seq_num           SMALLINT    NOT NULL,
    icd_code          VARCHAR(10) NOT NULL,
    icd_version       SMALLINT    NOT NULL CHECK (icd_version IN (9, 10)),
    long_title        TEXT,
    -- Computed: seq_num = 1 → primary diagnosis
    is_primary        BOOLEAN     GENERATED ALWAYS AS (seq_num = 1) STORED,
    source_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_diagnoses UNIQUE (hadm_id, seq_num, icd_code, icd_version)
);

CREATE INDEX IF NOT EXISTS idx_diag_hadm_id  ON ap_diagnoses (hadm_id);
CREATE INDEX IF NOT EXISTS idx_diag_icd      ON ap_diagnoses (icd_code, icd_version);
-- Fast path: primary diagnosis lookup
CREATE INDEX IF NOT EXISTS idx_diag_primary  ON ap_diagnoses (hadm_id)
    WHERE seq_num = 1;

-- ---------------------------------------------------------------------------
-- 2.3  PROCEDURES
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ap_procedures (
    id                BIGSERIAL   PRIMARY KEY,
    hadm_id           INTEGER     NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    subject_id        INTEGER     NOT NULL,
    seq_num           SMALLINT    NOT NULL,
    chartdate         DATE,
    icd_code          VARCHAR(10) NOT NULL,
    icd_version       SMALLINT    NOT NULL CHECK (icd_version IN (9, 10)),
    long_title        TEXT,
    source_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_procedures UNIQUE (hadm_id, seq_num, icd_code, icd_version)
);

CREATE INDEX IF NOT EXISTS idx_proc_hadm_id  ON ap_procedures (hadm_id);
CREATE INDEX IF NOT EXISTS idx_proc_icd      ON ap_procedures (icd_code, icd_version);
CREATE INDEX IF NOT EXISTS idx_proc_date     ON ap_procedures (hadm_id, chartdate);

-- ---------------------------------------------------------------------------
-- 2.4  DRG CODES
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ap_drgcodes (
    id                BIGSERIAL   PRIMARY KEY,
    hadm_id           INTEGER     NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    subject_id        INTEGER     NOT NULL,
    drg_type          VARCHAR(10),
    drg_code          VARCHAR(10) NOT NULL,
    description       TEXT,
    drg_severity      SMALLINT,
    drg_mortality     SMALLINT,
    source_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_drg UNIQUE (hadm_id, drg_type, drg_code)
);

CREATE INDEX IF NOT EXISTS idx_drg_hadm_id ON ap_drgcodes (hadm_id);

-- ---------------------------------------------------------------------------
-- 2.5  LAB EVENTS  (high-volume: ~500–5000 rows per admission)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ap_labevents (
    labevent_id       BIGINT      PRIMARY KEY,   -- MIMIC source PK
    hadm_id           INTEGER     NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    subject_id        INTEGER     NOT NULL,
    specimen_id       BIGINT,
    itemid            INTEGER     NOT NULL,
    -- Joined from d_labitems at fetch time
    label             VARCHAR(100),
    fluid             VARCHAR(50),
    category          VARCHAR(50),
    loinc_code        VARCHAR(20),
    -- Values
    charttime         TIMESTAMPTZ,
    storetime         TIMESTAMPTZ,
    value             VARCHAR(200),
    valuenum          NUMERIC(14,4),
    valueuom          VARCHAR(20),
    ref_range_lower   NUMERIC(14,4),
    ref_range_upper   NUMERIC(14,4),
    flag              VARCHAR(20),               -- 'abnormal' or NULL
    priority          VARCHAR(20),
    comments          TEXT,
    source_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lab_hadm_id   ON ap_labevents (hadm_id);
-- Descending time index — most tab queries fetch latest results first
CREATE INDEX IF NOT EXISTS idx_lab_time      ON ap_labevents (hadm_id, charttime DESC);
CREATE INDEX IF NOT EXISTS idx_lab_itemid    ON ap_labevents (itemid);
-- Partial: abnormal results only (used in investigations section)
CREATE INDEX IF NOT EXISTS idx_lab_abnormal  ON ap_labevents (hadm_id, charttime DESC)
    WHERE flag IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 2.6  MICROBIOLOGY EVENTS
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ap_microbiologyevents (
    microevent_id       BIGINT      PRIMARY KEY,  -- MIMIC source PK
    hadm_id             INTEGER     NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    subject_id          INTEGER     NOT NULL,
    micro_specimen_id   BIGINT,
    chartdate           DATE,
    charttime           TIMESTAMPTZ,
    spec_type_desc      VARCHAR(100),
    test_seq            SMALLINT,
    storedate           DATE,
    storetime           TIMESTAMPTZ,
    org_name            VARCHAR(100),
    isolate_num         SMALLINT,
    quantity            VARCHAR(50),
    ab_name             VARCHAR(100),
    dilution_text       VARCHAR(20),
    dilution_comparison VARCHAR(5),
    dilution_value      NUMERIC(8,2),
    interpretation      VARCHAR(5),              -- S / R / I
    comments            TEXT,
    source_fetched_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_micro_hadm_id ON ap_microbiologyevents (hadm_id);
CREATE INDEX IF NOT EXISTS idx_micro_time    ON ap_microbiologyevents (hadm_id, charttime DESC);
CREATE INDEX IF NOT EXISTS idx_micro_org     ON ap_microbiologyevents (org_name);

-- ---------------------------------------------------------------------------
-- 2.7  PRESCRIPTIONS
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ap_prescriptions (
    id                BIGSERIAL    PRIMARY KEY,
    hadm_id           INTEGER      NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    subject_id        INTEGER      NOT NULL,
    pharmacy_id       BIGINT,
    poe_id            VARCHAR(30),
    starttime         TIMESTAMPTZ,
    stoptime          TIMESTAMPTZ,
    drug_type         VARCHAR(20),
    drug              VARCHAR(200),
    formulary_drug_cd VARCHAR(20),
    gsn               VARCHAR(200),
    ndc               VARCHAR(25),
    prod_strength     TEXT,
    form_rx           VARCHAR(25),
    dose_val_rx       VARCHAR(50),
    dose_unit_rx      VARCHAR(50),
    form_val_disp     VARCHAR(50),
    form_unit_disp    VARCHAR(50),
    doses_per_24_hrs  NUMERIC(6,2),
    route             VARCHAR(50),
    source_fetched_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rx_hadm_id  ON ap_prescriptions (hadm_id);
CREATE INDEX IF NOT EXISTS idx_rx_start    ON ap_prescriptions (hadm_id, starttime);
CREATE INDEX IF NOT EXISTS idx_rx_drug     ON ap_prescriptions (drug);
-- Partial: discharge medications (MAIN type, active at discharge)
CREATE INDEX IF NOT EXISTS idx_rx_discharge ON ap_prescriptions (hadm_id, stoptime DESC)
    WHERE drug_type = 'MAIN';

-- ---------------------------------------------------------------------------
-- 2.8  ICU STAYS  (parent of all ICU sub-tables)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ap_icustays (
    stay_id           INTEGER     PRIMARY KEY,   -- MIMIC source PK
    hadm_id           INTEGER     NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    subject_id        INTEGER     NOT NULL,
    first_careunit    VARCHAR(100),
    last_careunit     VARCHAR(100),
    intime            TIMESTAMPTZ,
    outtime           TIMESTAMPTZ,
    los               NUMERIC(8,4),              -- days
    source_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_icu_hadm_id ON ap_icustays (hadm_id);
CREATE INDEX IF NOT EXISTS idx_icu_intime  ON ap_icustays (hadm_id, intime);

-- ---------------------------------------------------------------------------
-- 2.9  CHART EVENTS  (vitals + ICU monitoring — largest table per patient)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ap_chartevents (
    id                BIGSERIAL    PRIMARY KEY,
    hadm_id           INTEGER      NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    subject_id        INTEGER      NOT NULL,
    stay_id           INTEGER      REFERENCES ap_icustays (stay_id) ON DELETE SET NULL,
    itemid            INTEGER      NOT NULL,
    -- Joined from d_items at fetch time
    label             VARCHAR(100),
    category          VARCHAR(50),
    -- Values
    charttime         TIMESTAMPTZ  NOT NULL,
    storetime         TIMESTAMPTZ,
    value             VARCHAR(200),
    valuenum          NUMERIC(14,4),
    valueuom          VARCHAR(20),
    warning           SMALLINT     CHECK (warning IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_chart_hadm_id  ON ap_chartevents (hadm_id);
CREATE INDEX IF NOT EXISTS idx_chart_time     ON ap_chartevents (hadm_id, charttime DESC);
CREATE INDEX IF NOT EXISTS idx_chart_stay_id  ON ap_chartevents (stay_id);
CREATE INDEX IF NOT EXISTS idx_chart_itemid   ON ap_chartevents (itemid);
-- Partial: vital-sign category rows only (used for S5/S10 in summary)
CREATE INDEX IF NOT EXISTS idx_chart_vitals   ON ap_chartevents (hadm_id, charttime DESC)
    WHERE category IN ('Routine Vital Signs', 'Vital Signs');

-- ---------------------------------------------------------------------------
-- 2.10  TRANSFERS
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ap_transfers (
    transfer_id       INTEGER     PRIMARY KEY,   -- MIMIC source PK
    hadm_id           INTEGER     NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    subject_id        INTEGER     NOT NULL,
    eventtype         VARCHAR(20),
    careunit          VARCHAR(100),
    intime            TIMESTAMPTZ,
    outtime           TIMESTAMPTZ,
    source_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_xfr_hadm_id ON ap_transfers (hadm_id);
CREATE INDEX IF NOT EXISTS idx_xfr_intime  ON ap_transfers (hadm_id, intime);

-- ---------------------------------------------------------------------------
-- 2.11  SERVICES
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ap_services (
    id                BIGSERIAL   PRIMARY KEY,
    hadm_id           INTEGER     NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    subject_id        INTEGER     NOT NULL,
    transfertime      TIMESTAMPTZ,
    prev_service      VARCHAR(20),
    curr_service      VARCHAR(20) NOT NULL,
    source_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_services UNIQUE (hadm_id, transfertime, curr_service)
);

CREATE INDEX IF NOT EXISTS idx_svc_hadm_id ON ap_services (hadm_id);
CREATE INDEX IF NOT EXISTS idx_svc_curr    ON ap_services (curr_service);

-- ---------------------------------------------------------------------------
-- 2.12  PHARMACY  (dispensing records — frequency field for discharge meds)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ap_pharmacy (
    pharmacy_id       BIGINT      PRIMARY KEY,   -- MIMIC source PK
    hadm_id           INTEGER     NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    subject_id        INTEGER     NOT NULL,
    poe_id            VARCHAR(30),
    starttime         TIMESTAMPTZ,
    stoptime          TIMESTAMPTZ,
    medication        VARCHAR(200),
    proc_type         VARCHAR(30),
    status            VARCHAR(20),
    route             VARCHAR(50),
    frequency         VARCHAR(30),               -- "BID", "TID", "Q8H" — key field
    disp_sched        TEXT,
    infusion_type     VARCHAR(20),
    doses_per_24_hrs  NUMERIC(6,2),
    duration          NUMERIC(10,4),
    duration_interval VARCHAR(20),
    fill_quantity     VARCHAR(30),
    source_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pharm_hadm_id ON ap_pharmacy (hadm_id);
CREATE INDEX IF NOT EXISTS idx_pharm_start   ON ap_pharmacy (hadm_id, starttime);

-- ---------------------------------------------------------------------------
-- 2.13  PHYSICIAN ORDERS (POE)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ap_poe (
    poe_id                  VARCHAR(30)  PRIMARY KEY,  -- MIMIC format: subjectid-seq
    hadm_id                 INTEGER      NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    subject_id              INTEGER      NOT NULL,
    poe_seq                 INTEGER,
    ordertime               TIMESTAMPTZ,
    order_type              VARCHAR(30),
    order_subtype           VARCHAR(50),
    transaction_type        VARCHAR(20),
    discontinue_of_poe_id   VARCHAR(30)  REFERENCES ap_poe (poe_id) ON DELETE SET NULL,
    order_status            VARCHAR(20),
    order_provider_id       VARCHAR(20),
    source_fetched_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_poe_hadm_id    ON ap_poe (hadm_id);
CREATE INDEX IF NOT EXISTS idx_poe_ordertime  ON ap_poe (hadm_id, ordertime DESC);
CREATE INDEX IF NOT EXISTS idx_poe_type       ON ap_poe (order_type);

-- ---------------------------------------------------------------------------
-- 2.14  OUTPATIENT MEASUREMENTS (OMR — by subject_id; joined via active_patients)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ap_omr (
    id                BIGSERIAL    PRIMARY KEY,
    hadm_id           INTEGER      NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    subject_id        INTEGER      NOT NULL,
    chartdate         DATE,
    seq_num           SMALLINT,
    result_name       VARCHAR(50),
    result_value      VARCHAR(100),
    source_fetched_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_omr UNIQUE (hadm_id, chartdate, seq_num, result_name)
);

CREATE INDEX IF NOT EXISTS idx_omr_hadm_id   ON ap_omr (hadm_id);
CREATE INDEX IF NOT EXISTS idx_omr_chartdate ON ap_omr (hadm_id, chartdate DESC);


-- =============================================================================
-- SECTION 3: CONDITIONAL ICU TABLES
-- Fetched ONLY when ap_icustays has ≥ 1 row for this hadm_id.
-- All FK to both active_patients(hadm_id) and ap_icustays(stay_id).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 3.1  PROCEDURE EVENTS  (ventilation, CRRT, central lines)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ap_procedureevents (
    id                  BIGSERIAL    PRIMARY KEY,
    hadm_id             INTEGER      NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    subject_id          INTEGER      NOT NULL,
    stay_id             INTEGER      NOT NULL
        REFERENCES ap_icustays (stay_id) ON DELETE CASCADE,
    itemid              INTEGER      NOT NULL,
    label               VARCHAR(100),
    starttime           TIMESTAMPTZ,
    endtime             TIMESTAMPTZ,
    storetime           TIMESTAMPTZ,
    value               NUMERIC(14,4),
    valueuom            VARCHAR(30),
    location            VARCHAR(30),
    locationcategory    VARCHAR(30),
    ordercategoryname   VARCHAR(50),
    statusdescription   VARCHAR(30),
    source_fetched_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pe_hadm_id ON ap_procedureevents (hadm_id);
CREATE INDEX IF NOT EXISTS idx_pe_stay_id ON ap_procedureevents (stay_id);
CREATE INDEX IF NOT EXISTS idx_pe_item    ON ap_procedureevents (itemid);

-- ---------------------------------------------------------------------------
-- 3.2  DATETIME EVENTS  (intubation, extubation timestamps)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ap_datetimeevents (
    id                BIGSERIAL    PRIMARY KEY,
    hadm_id           INTEGER      NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    subject_id        INTEGER      NOT NULL,
    stay_id           INTEGER      NOT NULL
        REFERENCES ap_icustays (stay_id) ON DELETE CASCADE,
    itemid            INTEGER      NOT NULL,
    label             VARCHAR(100),
    category          VARCHAR(50),
    charttime         TIMESTAMPTZ  NOT NULL,
    storetime         TIMESTAMPTZ,
    value             TIMESTAMPTZ,
    warning           SMALLINT     CHECK (warning IN (0, 1)),
    source_fetched_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dte_hadm_id  ON ap_datetimeevents (hadm_id);
CREATE INDEX IF NOT EXISTS idx_dte_stay_id  ON ap_datetimeevents (stay_id);
CREATE INDEX IF NOT EXISTS idx_dte_time     ON ap_datetimeevents (hadm_id, charttime);

-- ---------------------------------------------------------------------------
-- 3.3  INPUT EVENTS  (IV fluids, infusions)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ap_inputevents (
    id                    BIGSERIAL    PRIMARY KEY,
    hadm_id               INTEGER      NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    subject_id            INTEGER      NOT NULL,
    stay_id               INTEGER      NOT NULL
        REFERENCES ap_icustays (stay_id) ON DELETE CASCADE,
    itemid                INTEGER      NOT NULL,
    label                 VARCHAR(100),
    starttime             TIMESTAMPTZ,
    endtime               TIMESTAMPTZ,
    storetime             TIMESTAMPTZ,
    amount                NUMERIC(14,4),
    amountuom             VARCHAR(20),
    rate                  NUMERIC(14,4),
    rateuom               VARCHAR(30),
    orderid               BIGINT,
    ordercategoryname     VARCHAR(50),
    statusdescription     VARCHAR(30),
    patientweight         NUMERIC(7,2),
    totalamount           NUMERIC(14,4),
    totalamountuom        VARCHAR(20),
    source_fetched_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ie_hadm_id ON ap_inputevents (hadm_id);
CREATE INDEX IF NOT EXISTS idx_ie_stay_id ON ap_inputevents (stay_id);
CREATE INDEX IF NOT EXISTS idx_ie_start   ON ap_inputevents (hadm_id, starttime);

-- ---------------------------------------------------------------------------
-- 3.4  OUTPUT EVENTS  (urine, drains)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ap_outputevents (
    id                BIGSERIAL    PRIMARY KEY,
    hadm_id           INTEGER      NOT NULL
        REFERENCES active_patients (hadm_id) ON DELETE CASCADE,
    subject_id        INTEGER      NOT NULL,
    stay_id           INTEGER      NOT NULL
        REFERENCES ap_icustays (stay_id) ON DELETE CASCADE,
    itemid            INTEGER      NOT NULL,
    label             VARCHAR(100),
    charttime         TIMESTAMPTZ  NOT NULL,
    storetime         TIMESTAMPTZ,
    value             NUMERIC(14,4),
    valueuom          VARCHAR(20),
    source_fetched_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oe_hadm_id  ON ap_outputevents (hadm_id);
CREATE INDEX IF NOT EXISTS idx_oe_stay_id  ON ap_outputevents (stay_id);
CREATE INDEX IF NOT EXISTS idx_oe_time     ON ap_outputevents (hadm_id, charttime);


-- =============================================================================
-- SECTION 4: CONCURRENCY & APPLICATION CONVENTIONS
-- =============================================================================
--
-- ── STATUS TRANSITIONS ───────────────────────────────────────────────────────
-- Any code that advances active_patients.status or app_encounters.status MUST
-- lock the row first to prevent two workers racing on the same patient:
--
--   BEGIN;
--   SELECT id FROM active_patients
--     WHERE hadm_id = $1
--     FOR UPDATE;                  -- row-level exclusive lock
--   UPDATE active_patients
--     SET status = $2, updated_at = NOW()
--     WHERE hadm_id = $1;
--   COMMIT;
--
-- ── BIGQUERY FETCH GUARD ──────────────────────────────────────────────────────
-- Before starting the BigQuery ETL job for a patient, acquire a session-level
-- advisory lock so a second worker cannot double-fetch:
--
--   BEGIN;
--   SELECT pg_advisory_xact_lock($hadm_id);  -- released automatically on COMMIT
--   SELECT data_fetch_status FROM active_patients WHERE hadm_id = $hadm_id;
--   -- Proceed only if status = 'pending' or 'failed'
--   UPDATE active_patients SET data_fetch_status = 'fetching' WHERE hadm_id = $hadm_id;
--   COMMIT;
--   -- … do BigQuery fetch …
--   BEGIN;
--   UPDATE active_patients SET data_fetch_status = 'fetched', data_fetched_at = NOW()
--     WHERE hadm_id = $hadm_id;
--   COMMIT;
--
-- ── BULK CLINICAL INSERTS ─────────────────────────────────────────────────────
-- All ap_* inserts use INSERT … ON CONFLICT DO NOTHING (idempotent re-fetch).
-- Wrap each table's batch in ONE transaction — not per-row commits.
-- Required insert order (respect FK dependencies):
--   1. ap_admissions
--   2. ap_icustays          (before chartevents / procedureevents)
--   3. ap_poe               (self-referencing FK discontinue_of_poe_id — insert nulls first)
--   4. All remaining ap_* tables in any order
--
-- ── QUEUE ASSIGNMENT (billing staff / doctors) ────────────────────────────────
-- To prevent two billing staff from claiming the same unassigned patient:
--
--   BEGIN;
--   SELECT id FROM active_patients
--     WHERE status = 'data_ready' AND assigned_doctor_id IS NULL
--     ORDER BY created_at
--     LIMIT 1
--     FOR UPDATE SKIP LOCKED;   -- skip rows another session has locked
--   UPDATE active_patients SET assigned_doctor_id = $uid WHERE id = $claimed_id;
--   COMMIT;
--
-- ── LARGE TABLE READS ─────────────────────────────────────────────────────────
-- ap_labevents and ap_chartevents can have 5000+ rows per patient.
-- Always use cursor pagination — never SELECT * without LIMIT:
--
--   SELECT * FROM ap_labevents
--     WHERE hadm_id = $1 AND charttime > $cursor
--     ORDER BY charttime DESC
--     LIMIT 500;
--
-- ── ISOLATION LEVEL ───────────────────────────────────────────────────────────
-- Default: READ COMMITTED (sufficient for queue + status workflows).
-- Use REPEATABLE READ for the summary generation transaction (reads multiple
-- clinical tables; must see a consistent snapshot across all of them):
--
--   BEGIN ISOLATION LEVEL REPEATABLE READ;
--   SELECT … FROM ap_diagnoses WHERE hadm_id = $1;
--   SELECT … FROM ap_labevents  WHERE hadm_id = $1;
--   … etc …
--   COMMIT;
--
-- =============================================================================

-- ---------------------------------------------------------------------------
-- ERROR LOG  (3-Tier Accuracy Framework — Nitin Sahni / Ashmit)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS error_log (
    id                  SERIAL          PRIMARY KEY,
    hadm_id             VARCHAR(20),
    summary_version     VARCHAR(10),
    nabh_section        VARCHAR(10),    -- 's1' … 's15'
    error_tier          SMALLINT        NOT NULL CHECK (error_tier IN (1, 2, 3)),
    ai_output           TEXT,
    correct_value       TEXT,
    error_category      VARCHAR(50),    -- 'medication_dose' | 'diagnosis' | 'hallucination' | 'formatting' | 'other'
    source_present      BOOLEAN,
    attending_id        VARCHAR(40),
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_error_log_tier      ON error_log (error_tier);
CREATE INDEX IF NOT EXISTS idx_error_log_hadm      ON error_log (hadm_id);
CREATE INDEX IF NOT EXISTS idx_error_log_created   ON error_log (created_at DESC);

-- Rolling 7-day Tier 3 rate — used for Launch Gate monitoring
CREATE OR REPLACE VIEW tier3_rolling_7d AS
SELECT
    COUNT(*) FILTER (WHERE error_tier = 3)                              AS tier3_count,
    COUNT(*)                                                            AS total_errors,
    ROUND(
        COUNT(*) FILTER (WHERE error_tier = 3)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    )                                                                   AS tier3_rate_pct
FROM error_log
WHERE created_at >= NOW() - INTERVAL '7 days';

COMMIT;
