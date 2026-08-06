-- Migration 003: Widen care-unit VARCHAR columns
-- ICU unit names in MIMIC-IV exceed 30 chars (e.g. "Cardiac Vascular Intensive Care Unit (CVICU)" = 43)
ALTER TABLE ap_icustays  ALTER COLUMN first_careunit TYPE VARCHAR(100);
ALTER TABLE ap_icustays  ALTER COLUMN last_careunit  TYPE VARCHAR(100);
ALTER TABLE ap_transfers ALTER COLUMN careunit       TYPE VARCHAR(100);
