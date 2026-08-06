-- Migration 012: Rejection log table + ensure revision columns + fix constraint
-- Run this once against the Cloud SQL instance.

-- 1. Ensure app_encounters status constraint includes all needed values
ALTER TABLE app_encounters DROP CONSTRAINT IF EXISTS app_encounters_status_check;
ALTER TABLE app_encounters ADD CONSTRAINT app_encounters_status_check
    CHECK (status IN (
        'Pending Ingestion', 'Processing', 'Data Incomplete',
        'Ready for Review', 'Awaiting Review', 'Awaiting Confirmation',
        'Verifying Claims', 'Signed Off', 'Revision Requested'
    ));

-- 2. Ensure revision columns exist (migration 002 may not have run)
ALTER TABLE app_encounters ADD COLUMN IF NOT EXISTS discharge_type    VARCHAR(20);
ALTER TABLE app_encounters ADD COLUMN IF NOT EXISTS revision_reason   TEXT;
ALTER TABLE app_encounters ADD COLUMN IF NOT EXISTS revision_at       TIMESTAMPTZ;
ALTER TABLE app_encounters ADD COLUMN IF NOT EXISTS rejection_count   INTEGER NOT NULL DEFAULT 0;

-- 3. Rejection audit log table
CREATE TABLE IF NOT EXISTS rejection_log (
    id                         SERIAL          PRIMARY KEY,
    encounter_id               UUID            NOT NULL
        REFERENCES app_encounters(id) ON DELETE CASCADE,
    hadm_id                    INTEGER         NOT NULL,
    rejected_by                UUID            REFERENCES app_users(id) ON DELETE SET NULL,
    rejection_reason           TEXT            NOT NULL,
    rejected_at                TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    regeneration_triggered_at  TIMESTAMPTZ,
    regenerated_at             TIMESTAMPTZ,
    notification_sent_at       TIMESTAMPTZ,
    re_reviewed_at             TIMESTAMPTZ,
    signed_at                  TIMESTAMPTZ,
    prev_t1_count              INTEGER         NOT NULL DEFAULT 0,
    new_t1_count               INTEGER         NOT NULL DEFAULT 0,
    auto_resolved_sections     TEXT[]          DEFAULT '{}',
    rejection_version          INTEGER         NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_rejection_log_encounter ON rejection_log(encounter_id);
CREATE INDEX IF NOT EXISTS idx_rejection_log_hadm      ON rejection_log(hadm_id);
