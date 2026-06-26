-- Migration 008: Add prompt version columns to app_summaries
-- Tracks which Pass 1 / Pass 2 prompt version generated each summary
-- so Tier 3 error rates can be correlated against specific prompt versions.

ALTER TABLE app_summaries
    ADD COLUMN IF NOT EXISTS pass1_version TEXT DEFAULT '1.0',
    ADD COLUMN IF NOT EXISTS pass2_version TEXT DEFAULT '1.0';

-- Backfill existing rows with v1.0
UPDATE app_summaries
SET pass1_version = '1.0', pass2_version = '1.0'
WHERE pass1_version IS NULL OR pass2_version IS NULL;
