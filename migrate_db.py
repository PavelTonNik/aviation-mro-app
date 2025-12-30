#!/usr/bin/env python3
"""
Direct database migration script for Render deployment.
Applies schema changes directly via SQLAlchemy without Alembic.
"""
import os
import sys
from sqlalchemy import create_engine, text, inspect

# Get DATABASE_URL from environment
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL environment variable not set")
    sys.exit(1)

print(f"Connecting to database...")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

def column_exists(inspector, table_name, column_name):
    """Check if column exists in table"""
    try:
        columns = [col['name'] for col in inspector.get_columns(table_name)]
        return column_name in columns
    except Exception:
        return False

def table_exists(inspector, table_name):
    """Check if table exists"""
    return table_name in inspector.get_table_names()

def run_migrations():
    inspector = inspect(engine)
    
    with engine.connect() as conn:
        # Add price column to engines if missing
        if table_exists(inspector, 'engines'):
            if not column_exists(inspector, 'engines', 'price'):
                print("Adding 'price' column to engines table...")
                conn.execute(text("ALTER TABLE engines ADD COLUMN price double precision DEFAULT 0"))
                conn.commit()
                print("✓ Added price column")
            else:
                print("✓ Price column already exists")
        
        # Create custom_columns table
        if not table_exists(inspector, 'custom_columns'):
            print("Creating custom_columns table...")
            conn.execute(text("""
                CREATE TABLE custom_columns (
                    id serial PRIMARY KEY,
                    table_name varchar NOT NULL,
                    column_key varchar NOT NULL,
                    column_label varchar NOT NULL,
                    column_order integer DEFAULT 0,
                    created_at timestamptz DEFAULT now(),
                    updated_at timestamptz
                )
            """))
            conn.commit()
            print("✓ Created custom_columns table")
        else:
            print("✓ custom_columns table already exists")
        
        # Create purchase_order_custom_data table
        if not table_exists(inspector, 'purchase_order_custom_data'):
            print("Creating purchase_order_custom_data table...")
            conn.execute(text("""
                CREATE TABLE purchase_order_custom_data (
                    id serial PRIMARY KEY,
                    purchase_order_id integer NOT NULL,
                    column_key varchar NOT NULL,
                    value text,
                    created_at timestamptz DEFAULT now(),
                    updated_at timestamptz
                )
            """))
            conn.commit()
            print("✓ Created purchase_order_custom_data table")
        else:
            print("✓ purchase_order_custom_data table already exists")
        
        # Create fake_installed table
        if not table_exists(inspector, 'fake_installed'):
            print("Creating fake_installed table...")
            conn.execute(text("""
                CREATE TABLE fake_installed (
                    id serial PRIMARY KEY,
                    engine_id integer,
                    engine_original_sn varchar,
                    engine_current_sn varchar,
                    aircraft_id integer,
                    aircraft_tail varchar,
                    position integer,
                    documented_date varchar,
                    documented_reason varchar,
                    old_engine_sn varchar,
                    new_engine_sn varchar,
                    is_fake boolean DEFAULT true,
                    actual_notes text,
                    created_by varchar,
                    created_at timestamptz DEFAULT now()
                )
            """))
            conn.commit()
            print("✓ Created fake_installed table")
        else:
            print("✓ fake_installed table already exists")
        
        # Create fake_installed_settings table
        if not table_exists(inspector, 'fake_installed_settings'):
            print("Creating fake_installed_settings table...")
            conn.execute(text("""
                CREATE TABLE fake_installed_settings (
                    id serial PRIMARY KEY,
                    headers_json text,
                    created_at timestamptz DEFAULT now(),
                    updated_at timestamptz
                )
            """))
            conn.commit()
            print("✓ Created fake_installed_settings table")
        else:
            print("✓ fake_installed_settings table already exists")
        
        # Create nameplate_tracker table
        if not table_exists(inspector, 'nameplate_tracker'):
            print("Creating nameplate_tracker table...")
            conn.execute(text("""
                CREATE TABLE nameplate_tracker (
                    id serial PRIMARY KEY,
                    nameplate_sn varchar NOT NULL,
                    engine_model varchar,
                    gss_id varchar,
                    engine_orig_sn varchar,
                    aircraft_tail varchar,
                    position varchar,
                    installed_date varchar,
                    removed_date varchar,
                    location_type varchar,
                    action_note varchar,
                    performed_by varchar,
                    notes text,
                    created_at timestamptz DEFAULT now()
                )
            """))
            conn.commit()
            print("✓ Created nameplate_tracker table")
        else:
            print("✓ nameplate_tracker table already exists")
    
    print("\n✅ All migrations completed successfully!")

if __name__ == "__main__":
    try:
        run_migrations()
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
