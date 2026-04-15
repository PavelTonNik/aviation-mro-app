#!/usr/bin/env python3
"""
Direct database migration script for Render deployment.
Applies schema changes directly via SQLAlchemy without Alembic.
"""
import os
import sys

print("=" * 80)
print("DATABASE MIGRATION SCRIPT")
print("=" * 80)

# Get DATABASE_URL from environment
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL environment variable not set")
    sys.exit(1)

# Render may provide postgres:// while SQLAlchemy expects postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Ensure SSL for managed Postgres unless explicitly provided
if DATABASE_URL.startswith("postgresql://") and "sslmode" not in DATABASE_URL:
    sep = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL = f"{DATABASE_URL}{sep}sslmode=require"

print(f"✓ DATABASE_URL found: {DATABASE_URL[:30]}...")

try:
    from sqlalchemy import create_engine, text
    print("✓ SQLAlchemy imported successfully")
except ImportError as e:
    print(f"❌ ERROR: Cannot import SQLAlchemy: {e}")
    sys.exit(1)

print(f"Connecting to database...")
try:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    print("✓ Database engine created")
    
    # Detect database type
    is_postgres = DATABASE_URL.startswith('postgresql://') or DATABASE_URL.startswith('postgres://')
    is_sqlite = DATABASE_URL.startswith('sqlite')
    
    if is_postgres:
        print("✓ Detected PostgreSQL database")
    elif is_sqlite:
        print("✓ Detected SQLite database (migration skipped - handled by startup_event)")
        print("=" * 80)
        print("⚠️  This script is for PostgreSQL on Render only.")
        print("⚠️  Local SQLite migrations are handled automatically by backend/main.py")
        print("=" * 80)
        sys.exit(0)
    else:
        print(f"⚠️  Unknown database type: {DATABASE_URL[:20]}...")
        
except Exception as e:
    print(f"❌ ERROR: Cannot create database engine: {e}")
    sys.exit(1)


def run_migrations():
    print("\n" + "=" * 80)
    print("STARTING MIGRATIONS")
    print("=" * 80 + "\n")
    
    try:
        with engine.begin() as conn:
            print("✓ Connection established")
            
            # Add price column to engines if missing
            print("\n[1/6] Checking engines.price column...")
            try:
                result = conn.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='engines' AND column_name='price'"
                ))
                if result.fetchone() is None:
                    print("  → Adding 'price' column to engines table...")
                    conn.execute(text("ALTER TABLE engines ADD COLUMN price double precision DEFAULT 0"))
                    print("  ✓ Added price column")
                else:
                    print("  ✓ Price column already exists")
            except Exception as e:
                print(f"  ⚠ Warning: Could not check/add price column: {e}")
                import traceback
                traceback.print_exc()
            
            # Create custom_columns table
            print("\n[2/6] Checking custom_columns table...")
            try:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS custom_columns (
                        id serial PRIMARY KEY,
                        table_name varchar NOT NULL,
                        column_key varchar NOT NULL,
                        column_label varchar NOT NULL,
                        column_order integer DEFAULT 0,
                        created_at timestamptz DEFAULT now(),
                        updated_at timestamptz
                    )
                """))
                print("  ✓ custom_columns table ready")
            except Exception as e:
                print(f"  ⚠ Warning: custom_columns issue: {e}")
            
            # Create purchase_order_custom_data table
            print("\n[3/6] Checking purchase_order_custom_data table...")
            try:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS purchase_order_custom_data (
                        id serial PRIMARY KEY,
                        purchase_order_id integer NOT NULL,
                        column_key varchar NOT NULL,
                        value text,
                        created_at timestamptz DEFAULT now(),
                        updated_at timestamptz
                    )
                """))
                print("  ✓ purchase_order_custom_data table ready")
            except Exception as e:
                print(f"  ⚠ Warning: purchase_order_custom_data issue: {e}")
            
            # Create fake_installed table
            print("\n[4/6] Checking fake_installed table...")
            try:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS fake_installed (
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
                print("  ✓ fake_installed table ready")
            except Exception as e:
                print(f"  ⚠ Warning: fake_installed issue: {e}")
            
            # Create fake_installed_settings table
            print("\n[5/6] Checking fake_installed_settings table...")
            try:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS fake_installed_settings (
                        id serial PRIMARY KEY,
                        headers_json text,
                        created_at timestamptz DEFAULT now(),
                        updated_at timestamptz
                    )
                """))
                print("  ✓ fake_installed_settings table ready")
            except Exception as e:
                print(f"  ⚠ Warning: fake_installed_settings issue: {e}")
            
            # Create nameplate_tracker table
            print("\n[6/7] Checking nameplate_tracker table...")
            try:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS nameplate_tracker (
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
                print("  ✓ nameplate_tracker table ready")
            except Exception as e:
                print(f"  ⚠ Warning: nameplate_tracker issue: {e}")

            # Add new store_items columns
            print("\n[7/8] Adding new store_items columns (removed_from, location_from, price, invoice_no)...")
            try:
                conn.execute(text("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='store_items' AND column_name='removed_from') THEN
                            ALTER TABLE store_items ADD COLUMN removed_from varchar;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='store_items' AND column_name='location_from') THEN
                            ALTER TABLE store_items ADD COLUMN location_from varchar;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='store_items' AND column_name='price') THEN
                            ALTER TABLE store_items ADD COLUMN price double precision;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='store_items' AND column_name='invoice_no') THEN
                            ALTER TABLE store_items ADD COLUMN invoice_no varchar;
                        END IF;
                    END$$;
                """))
                print("  ✓ store_items new columns ready")
            except Exception as e:
                print(f"  ⚠ Warning: store_items columns issue: {e}")

            # Add cost_per_hour and cost_per_cycle to engines
            print("\n[8/9] Adding engines.cost_per_hour and cost_per_cycle columns...")
            try:
                conn.execute(text("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='engines' AND column_name='cost_per_hour') THEN
                            ALTER TABLE engines ADD COLUMN cost_per_hour double precision;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='engines' AND column_name='cost_per_cycle') THEN
                            ALTER TABLE engines ADD COLUMN cost_per_cycle double precision;
                        END IF;
                    END$$;
                """))
                print("  ✓ engines cost columns ready")
            except Exception as e:
                print(f"  ⚠ Warning: engines cost columns issue: {e}")

            # Add permissions column to users
            print("\n[9/9] Adding users.permissions column...")
            try:
                conn.execute(text("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='permissions') THEN
                            ALTER TABLE users ADD COLUMN permissions text;
                        END IF;
                    END$$;
                """))
                print("  ✓ users.permissions column ready")
            except Exception as e:
                print(f"  ⚠ Warning: users.permissions column issue: {e}")

            # Add password_plain column to users
            print("\n[10/10] Adding users.password_plain column...")
            try:
                conn.execute(text("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='password_plain') THEN
                            ALTER TABLE users ADD COLUMN password_plain varchar;
                        END IF;
                    END$$;
                """))
                print("  ✓ users.password_plain column ready")
            except Exception as e:
                print(f"  ⚠ Warning: users.password_plain column issue: {e}")
        
        print("\n" + "=" * 80)
        print("✅ ALL MIGRATIONS COMPLETED SUCCESSFULLY!")
        print("=" * 80)
        
    except Exception as e:
        print("\n" + "=" * 80)
        print(f"❌ MIGRATION FAILED: {e}")
        print("=" * 80)
        import traceback
        traceback.print_exc()
        raise

if __name__ == "__main__":
    try:
        run_migrations()
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
