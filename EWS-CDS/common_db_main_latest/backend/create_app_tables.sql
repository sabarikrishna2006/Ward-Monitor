-- ── App-level tables for discharge-summary-ai ─────────────────────────────

-- Users
CREATE TABLE IF NOT EXISTS app_users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hospital_email  TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('Doctor','Admin Staff')),
    full_name       TEXT,
    session_token   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_users_email ON app_users(hospital_email);
CREATE INDEX IF NOT EXISTS idx_users_token ON app_users(session_token);

-- Encounters
CREATE TABLE IF NOT EXISTS app_encounters (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hadm_id             BIGINT NOT NULL,
    status              TEXT DEFAULT 'Pending Ingestion',
    complexity          TEXT,
    assigned_to         UUID REFERENCES app_users(id) ON DELETE SET NULL,
    version             INTEGER DEFAULT 1,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    last_accessed_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_enc_hadm    ON app_encounters(hadm_id);
CREATE INDEX IF NOT EXISTS idx_enc_status  ON app_encounters(status);
CREATE INDEX IF NOT EXISTS idx_enc_assign  ON app_encounters(assigned_to);

-- Summaries
CREATE TABLE IF NOT EXISTS app_summaries (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    encounter_id                UUID NOT NULL REFERENCES app_encounters(id) ON DELETE CASCADE,
    content                     TEXT,
    nli_score                   DOUBLE PRECISION,
    clinical_context            TEXT,
    claim_verification_status   TEXT,
    signed_by                   TEXT,
    signed_at                   TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sum_enc ON app_summaries(encounter_id);

-- Uploaded files metadata
CREATE TABLE IF NOT EXISTS app_uploaded_files (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    encounter_id    UUID REFERENCES app_encounters(id) ON DELETE CASCADE,
    hadm_id         BIGINT,
    file_type       TEXT,
    file_name       TEXT,
    file_size       BIGINT,
    indexed_status  BOOLEAN DEFAULT FALSE,
    upload_date     DATE,
    uploaded_at     TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_files_enc  ON app_uploaded_files(encounter_id);
CREATE INDEX IF NOT EXISTS idx_files_hadm ON app_uploaded_files(hadm_id);

-- Uploaded clinical rows (CSV data from user uploads)
CREATE TABLE IF NOT EXISTS app_clinical_data (
    id          BIGSERIAL PRIMARY KEY,
    hadm_id     BIGINT NOT NULL,
    file_type   TEXT NOT NULL,
    file_id     UUID NOT NULL,
    row_data    JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clin_hadm      ON app_clinical_data(hadm_id);
CREATE INDEX IF NOT EXISTS idx_clin_file_type ON app_clinical_data(hadm_id, file_type);
CREATE INDEX IF NOT EXISTS idx_clin_file_id   ON app_clinical_data(file_id);

-- Password reset tokens
CREATE TABLE IF NOT EXISTS app_reset_tokens (
    token       TEXT PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    expiry      BIGINT NOT NULL
);

-- Audit log
CREATE TABLE IF NOT EXISTS app_audit_log (
    id          BIGSERIAL PRIMARY KEY,
    action      TEXT NOT NULL,
    hadm_id     BIGINT,
    user_id     UUID,
    details     JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_time   ON app_audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_hadm   ON app_audit_log(hadm_id);

-- Settings (singleton — always upsert row id=1)
CREATE TABLE IF NOT EXISTS app_settings (
    id                          INTEGER PRIMARY KEY DEFAULT 1,
    hospital_name               TEXT DEFAULT '',
    wing                        TEXT DEFAULT '',
    city                        TEXT DEFAULT '',
    mci_nabh_number             TEXT DEFAULT '',
    footer_disclaimer           TEXT DEFAULT '',
    nli_entailment_threshold    DOUBLE PRECISION DEFAULT 0.5,
    k_retrieved_chunks          INTEGER DEFAULT 5,
    dense_retrieval_weight      DOUBLE PRECISION DEFAULT 0.7,
    auto_notify_doctor          BOOLEAN DEFAULT FALSE,
    updated_at                  TIMESTAMPTZ DEFAULT NOW()
);
INSERT INTO app_settings (id) VALUES (1) ON CONFLICT DO NOTHING;
