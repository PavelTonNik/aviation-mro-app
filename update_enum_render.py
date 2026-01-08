#!/usr/bin/env python3
"""
Быстрый скрипт для обновления enum enginestatus на Render
Удаляет AS и оставляет только SV, US, INSTALLED, REMOVED
"""
import os
from sqlalchemy import text
from backend.database import engine

def update_enum():
    sql = """
    DO $$
    BEGIN
        -- Check if enginestatus enum exists
        IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'enginestatus') THEN
            -- Rename old enum
            ALTER TYPE enginestatus RENAME TO enginestatus_old;
            
            -- Create new enum with correct values (no AS, only SV, US, INSTALLED, REMOVED)
            CREATE TYPE enginestatus AS ENUM ('SV', 'US', 'INSTALLED', 'REMOVED');
            
            -- Update the column to use new enum type
            ALTER TABLE engines 
                ALTER COLUMN status TYPE enginestatus USING status::text::enginestatus;
            
            -- Drop old enum
            DROP TYPE enginestatus_old;
            
            RAISE NOTICE 'Engine status enum updated successfully!';
        ELSE
            RAISE NOTICE 'enginestatus enum does not exist, skipping...';
        END IF;
    END$$;
    """
    
    try:
        with engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
        print("✅ Enum enginestatus updated successfully on Render!")
    except Exception as e:
        print(f"❌ Error updating enum: {e}")
        raise

if __name__ == "__main__":
    print("🚀 Starting enum update on Render...")
    update_enum()
