-- Migration 007: Usability ratings table + latency/ROUGE columns on app_summaries

CREATE TABLE IF NOT EXISTS usability_ratings (
    id              SERIAL          PRIMARY KEY,
    encounter_id    UUID            REFERENCES app_encounters(id) ON DELETE SET NULL,
    hadm_id         INTEGER,
    attending_id    VARCHAR(40),
    rating          SMALLINT        NOT NULL CHECK (rating BETWEEN 1 AND 5),
    feedback        TEXT,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usability_enc  ON usability_ratings (encounter_id);
CREATE INDEX IF NOT EXISTS idx_usability_att  ON usability_ratings (attending_id);

ALTER TABLE app_summaries
    ADD COLUMN IF NOT EXISTS pass1_latency_s  REAL,
    ADD COLUMN IF NOT EXISTS pass2_latency_s  REAL,
    ADD COLUMN IF NOT EXISTS total_latency_s  REAL,
    ADD COLUMN IF NOT EXISTS rouge1           REAL,
    ADD COLUMN IF NOT EXISTS rouge2           REAL,
    ADD COLUMN IF NOT EXISTS rougeL           REAL,
    ADD COLUMN IF NOT EXISTS summary_version  INTEGER;
