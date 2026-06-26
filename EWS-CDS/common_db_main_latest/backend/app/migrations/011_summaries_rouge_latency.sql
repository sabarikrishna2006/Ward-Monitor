-- Migration 011: Add ROUGE scores, latency, and summary version to app_summaries
-- These columns are written by generate_summary on every call and were missing
-- from the base schema (added after initial deploy).

ALTER TABLE app_summaries
    ADD COLUMN IF NOT EXISTS pass1_latency_s  NUMERIC(8,3),
    ADD COLUMN IF NOT EXISTS pass2_latency_s  NUMERIC(8,3),
    ADD COLUMN IF NOT EXISTS total_latency_s  NUMERIC(8,3),
    ADD COLUMN IF NOT EXISTS rouge1           NUMERIC(6,4),
    ADD COLUMN IF NOT EXISTS rouge2           NUMERIC(6,4),
    ADD COLUMN IF NOT EXISTS "rougeL"         NUMERIC(6,4),
    ADD COLUMN IF NOT EXISTS summary_version  INTEGER DEFAULT 1;

-- Backfill summary_version for any existing rows
UPDATE app_summaries SET summary_version = 1 WHERE summary_version IS NULL;
