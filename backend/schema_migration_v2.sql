-- =============================================================================
-- EWS Schema Migration v2 — MIMIC Data Integration
-- Run ONCE against Cloud SQL after schema_migration_v1 (ews_migration.sql)
-- Adds: BNP/Troponin/Na/Hgb to ews_lab_events
--       Weight to ews_vitals_timeseries
--       NYHA/LVEF/BNP-baseline to active_patients
-- =============================================================================

-- ews_lab_events: cardiology-critical labs from MIMIC ap_labevents
ALTER TABLE ews_lab_events
    ADD COLUMN IF NOT EXISTS bnp        NUMERIC(10,2),   -- BNP pg/mL (itemids 50963, 51921)
    ADD COLUMN IF NOT EXISTS troponin   NUMERIC(10,4),   -- Troponin T ng/mL (itemid 51003)
    ADD COLUMN IF NOT EXISTS sodium     NUMERIC(6,2),    -- Na mmol/L (itemid 50983)
    ADD COLUMN IF NOT EXISTS hemoglobin NUMERIC(6,2);    -- Hgb g/dL (itemid 51222)

-- ews_vitals_timeseries: daily weight for fluid balance tracking
ALTER TABLE ews_vitals_timeseries
    ADD COLUMN IF NOT EXISTS weight_kg  NUMERIC(6,2);    -- kg (itemids 224639, 226512)

-- active_patients: NYHA class + LVEF + BNP at admission
ALTER TABLE active_patients
    ADD COLUMN IF NOT EXISTS nyha_class   SMALLINT,      -- 1-4 (derived from BNP/EF/NEWS2)
    ADD COLUMN IF NOT EXISTS lvef_percent SMALLINT,      -- LVEF % (from echo, NULL if unavailable)
    ADD COLUMN IF NOT EXISTS bnp_baseline NUMERIC(10,2); -- BNP at admission pg/mL
