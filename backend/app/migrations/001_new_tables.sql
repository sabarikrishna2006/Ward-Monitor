-- =============================================================================
-- Migration 001 — New tables required by cloud_sql_app_db.py
-- Apply ONCE after setup_cloud_sql.py has been run.
--
-- Usage:
--   python backend/apply_migration.py 001
-- =============================================================================

BEGIN;

-- Reset tokens for password-reset email flow
CREATE TABLE IF NOT EXISTS app_reset_tokens (
    token      TEXT        PRIMARY KEY,
    user_id    UUID        NOT NULL
        REFERENCES app_users (id) ON DELETE CASCADE,
    expiry     BIGINT      NOT NULL,   -- Unix timestamp seconds
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reset_user ON app_reset_tokens (user_id);

-- Clinical rows uploaded by doctors (CSV data stored per file as JSONB array)
CREATE TABLE IF NOT EXISTS app_clinical_rows (
    id         BIGSERIAL    PRIMARY KEY,
    hadm_id    INTEGER      NOT NULL,
    file_type  VARCHAR(30)  NOT NULL,
    file_id    UUID         NOT NULL,
    rows       JSONB        NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_clinical_rows UNIQUE (hadm_id, file_type, file_id)
);

CREATE INDEX IF NOT EXISTS idx_clinical_hadm ON app_clinical_rows (hadm_id, file_type);

COMMIT;
