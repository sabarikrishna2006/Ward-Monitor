-- Migration 002: 3-Tier Accuracy Framework error log + encounter extra columns
-- Run once: psql $DATABASE_URL -f backend/app/migrations/002_error_log.sql

-- Add columns to app_encounters that may not exist in deployed schema
ALTER TABLE app_encounters ADD COLUMN IF NOT EXISTS discharge_type    VARCHAR(20);
ALTER TABLE app_encounters ADD COLUMN IF NOT EXISTS revision_reason   TEXT;
ALTER TABLE app_encounters ADD COLUMN IF NOT EXISTS revision_at       TIMESTAMPTZ;

-- Allow the new status value
ALTER TABLE app_encounters DROP CONSTRAINT IF EXISTS app_encounters_status_check;
ALTER TABLE app_encounters ADD CONSTRAINT app_encounters_status_check
    CHECK (status IN (
        'Pending Ingestion', 'Processing', 'Data Incomplete',
        'Ready for Review', 'Awaiting Confirmation', 'Awaiting Review',
        'Verifying Claims', 'Signed Off', 'Revision Requested', 'revision_requested', 'Rejected'
    ));

CREATE TABLE IF NOT EXISTS error_log (
    id                  SERIAL          PRIMARY KEY,
    hadm_id             VARCHAR(20),
    summary_version     VARCHAR(10),
    nabh_section        VARCHAR(10),
    error_tier          SMALLINT        NOT NULL CHECK (error_tier IN (1, 2, 3)),
    ai_output           TEXT,
    correct_value       TEXT,
    error_category      VARCHAR(50),
    source_present      BOOLEAN,
    attending_id        VARCHAR(40),
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_error_log_tier    ON error_log (error_tier);
CREATE INDEX IF NOT EXISTS idx_error_log_hadm    ON error_log (hadm_id);
CREATE INDEX IF NOT EXISTS idx_error_log_created ON error_log (created_at DESC);

CREATE OR REPLACE VIEW tier3_rolling_7d AS
SELECT
    COUNT(*) FILTER (WHERE error_tier = 3)                          AS tier3_count,
    COUNT(*)                                                        AS total_errors,
    ROUND(
        COUNT(*) FILTER (WHERE error_tier = 3)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    )                                                               AS tier3_rate_pct
FROM error_log
WHERE created_at >= NOW() - INTERVAL '7 days';
