-- Migration 013: Add files_ready_at column to rejection_log
-- and add "Files Ready" status to app_encounters

-- Step 1: Add files_ready_at to rejection_log (resident uploads corrected files)
ALTER TABLE rejection_log
    ADD COLUMN IF NOT EXISTS files_ready_at TIMESTAMPTZ;

-- Step 2: Drop old status constraint and recreate with "Files Ready" added
ALTER TABLE app_encounters
    DROP CONSTRAINT IF EXISTS app_encounters_status_check;

ALTER TABLE app_encounters
    ADD CONSTRAINT app_encounters_status_check CHECK (
        status IN (
            'Pending Ingestion',
            'Processing',
            'Data Incomplete',
            'Ready for Review',
            'Awaiting Confirmation',
            'Verifying Claims',
            'Awaiting Review',
            'Signed Off',
            'Revision Requested',
            'Files Ready'
        )
    );
