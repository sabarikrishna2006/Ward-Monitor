-- Migration 027: persist doctor sign-off signature + signer name on app_summaries
-- Safe to re-run: uses IF NOT EXISTS throughout.
--
-- WHY THIS MATTERS:
--   signature_data — signoff.js sends { mci, sig_png, full_name, designation, hospital }
--                    on sign-off, but app_summaries has no column for it, so
--                    cloud_sql_app_db.update_summary() silently drops it. Reopening a
--                    signed discharge summary later (or downloading its PDF) then shows
--                    no signature image and generic/blank MCI, designation, hospital.
--   saved_by_name  — same drop: only summary_versions stored it, so the live
--                    app_summaries row (what /api/encounters/{id}/summary returns)
--                    never carries the actual signer's name.

ALTER TABLE app_summaries ADD COLUMN IF NOT EXISTS signature_data TEXT;
ALTER TABLE app_summaries ADD COLUMN IF NOT EXISTS saved_by_name  VARCHAR(255);
