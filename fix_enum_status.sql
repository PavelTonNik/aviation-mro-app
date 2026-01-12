-- FORCE UPDATE enginestatus ENUM to include '-' value
-- Run this on your Render PostgreSQL database

BEGIN;

-- Drop old enum constraint and rename column temporarily
ALTER TABLE engines DROP CONSTRAINT IF EXISTS engines_status_check;

-- Rename the old type
ALTER TYPE enginestatus RENAME TO enginestatus_old;

-- Create new enum with all values including '-'
CREATE TYPE enginestatus AS ENUM ('SV', 'US', 'INSTALLED', 'REMOVED', '-');

-- Convert column to new type
ALTER TABLE engines 
    ALTER COLUMN status TYPE enginestatus USING 
        CASE 
            WHEN status::text IN ('SV', 'US', 'INSTALLED', 'REMOVED', '-') THEN status::text::enginestatus
            ELSE 'SV'::enginestatus
        END;

-- Drop old enum
DROP TYPE enginestatus_old;

-- Update default value for new engines
ALTER TABLE engines ALTER COLUMN status SET DEFAULT 'SV';

-- Also update action_logs if it has status field
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'action_logs' AND column_name = 'status'
    ) THEN
        BEGIN
            ALTER TYPE actionstatus RENAME TO actionstatus_old;
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END IF;
END$$;

COMMIT;

-- Verify the change
SELECT column_name, data_type FROM information_schema.columns 
WHERE table_name = 'engines' AND column_name = 'status';
