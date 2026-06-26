-- Remove clinical tables that provide no value for NABH discharge summaries:
-- eMAR / eMAR Detail (duplicates Medications at administration granularity)
-- Datetime Events (ICU timestamps already covered by ICU Events)
-- DRG Codes (billing classification, not clinical data)
-- Services (hospital routing, already captured by Transfers)
DROP TABLE IF EXISTS ap_emar_detail CASCADE;
DROP TABLE IF EXISTS ap_emar CASCADE;
DROP TABLE IF EXISTS ap_datetimeevents CASCADE;
DROP TABLE IF EXISTS ap_drgcodes CASCADE;
DROP TABLE IF EXISTS ap_services CASCADE;
