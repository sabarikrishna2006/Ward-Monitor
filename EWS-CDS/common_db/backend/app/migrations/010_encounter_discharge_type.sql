-- Migration 010: Add discharge_type column to encounters table
-- Required for storing resident-selected discharge type (Standard/LAMA/DAMA/Death/Referral)
-- Also bumps prompt version log to v1.1 for schema expansion

ALTER TABLE app_encounters
    ADD COLUMN IF NOT EXISTS discharge_type TEXT DEFAULT 'Standard';

UPDATE app_encounters
    SET discharge_type = 'Standard'
    WHERE discharge_type IS NULL;

-- Backfill v1.1 marker for any summaries generated with new schema
-- (pass1_version/pass2_version columns already exist from migration 008)
