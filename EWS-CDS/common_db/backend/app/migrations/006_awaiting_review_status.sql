-- Migration 006: Add 'Awaiting Review' to app_encounters status CHECK constraint
-- Required because sendReview uses this status but it was missing from the constraint.

ALTER TABLE app_encounters DROP CONSTRAINT IF EXISTS app_encounters_status_check;

ALTER TABLE app_encounters ADD CONSTRAINT app_encounters_status_check
    CHECK (status IN (
        'Pending Ingestion', 'Processing', 'Data Incomplete',
        'Ready for Review', 'Awaiting Review', 'Awaiting Confirmation',
        'Verifying Claims', 'Signed Off', 'Revision Requested'
    ));
