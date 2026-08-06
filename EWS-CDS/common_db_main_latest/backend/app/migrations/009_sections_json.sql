-- Migration 009: Store per-section JSON from Pass 2 output
-- PM spec v1.0 requires Pass 2 to return {"s1":"...","s15":"..."} JSON.
-- sections_json stores that raw dict; content stores the assembled narrative for frontend.

ALTER TABLE app_summaries
    ADD COLUMN IF NOT EXISTS sections_json JSONB;
