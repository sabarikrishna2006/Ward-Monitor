-- Migration 016: active_patients production schema completeness
-- Safe to re-run: uses IF NOT EXISTS throughout.
--
-- WHY THIS MATTERS:
--   updated_at            — every discharge handoff UPDATE writes `updated_at = NOW()`.
--                           Without this column the UPDATE fails silently; patients
--                           never surface in Ashmit's doctor queue.
--   primary_diagnosis_title — list_encounters() and billing_dashboard() both JOIN this
--                           column via `ap.primary_diagnosis_title`. PostgreSQL raises
--                           "column does not exist" without it.
--   discharge_type        — workflow state (Standard / LAMA / DAMA / Death / Referral).
--   discharge_time        — billing_dashboard JOIN: `ap.discharge_time`.
--   los_days              — billing_dashboard JOIN: `ap.los_days`.

ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS updated_at               TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS primary_diagnosis_title  VARCHAR(255);
ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS discharge_type           VARCHAR(20);
ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS discharge_time           TIMESTAMPTZ;
ALTER TABLE active_patients ADD COLUMN IF NOT EXISTS los_days                 NUMERIC(6,2);

-- Backfill updated_at so it is never NULL on existing rows
UPDATE active_patients SET updated_at = NOW() WHERE updated_at IS NULL;

-- Indexes to speed up common query patterns
CREATE INDEX IF NOT EXISTS idx_ap_status      ON active_patients (status)        WHERE status IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ap_discharge   ON active_patients (discharge_type) WHERE discharge_type IS NOT NULL;
