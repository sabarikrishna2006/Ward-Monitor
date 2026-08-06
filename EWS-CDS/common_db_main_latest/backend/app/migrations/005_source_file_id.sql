-- Migration 005: Add source_file_id to ap_* tables so uploaded rows can be tracked and deleted
-- Applied: 2026-06-06

ALTER TABLE ap_prescriptions      ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40);
ALTER TABLE ap_labevents           ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40);
ALTER TABLE ap_microbiologyevents  ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40);
ALTER TABLE ap_chartevents         ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40);
ALTER TABLE ap_icustays            ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40);
ALTER TABLE ap_transfers           ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40);
ALTER TABLE ap_services            ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40);
ALTER TABLE ap_pharmacy            ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40);
ALTER TABLE ap_poe                 ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40);
ALTER TABLE ap_drgcodes            ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40);
ALTER TABLE ap_diagnoses           ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40);
ALTER TABLE ap_procedures          ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40);
ALTER TABLE ap_emar                ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40);
ALTER TABLE ap_emar_detail         ADD COLUMN IF NOT EXISTS source_file_id VARCHAR(40);

-- Indexes for fast delete by file_id
CREATE INDEX IF NOT EXISTS idx_rx_file_id     ON ap_prescriptions     (source_file_id) WHERE source_file_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lab_file_id    ON ap_labevents          (source_file_id) WHERE source_file_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_micro_file_id  ON ap_microbiologyevents (source_file_id) WHERE source_file_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_chart_file_id  ON ap_chartevents        (source_file_id) WHERE source_file_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_emar_file_id   ON ap_emar               (source_file_id) WHERE source_file_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_emard_file_id  ON ap_emar_detail        (source_file_id) WHERE source_file_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_poe_file_id    ON ap_poe                (source_file_id) WHERE source_file_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_pharm_file_id  ON ap_pharmacy           (source_file_id) WHERE source_file_id IS NOT NULL;
