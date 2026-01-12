# backend/database.py
from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# Database URL resolution: use env var `DATABASE_URL` if provided,
# fallback to local SQLite file next to this module.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SQLITE_PATH = os.path.join(BASE_DIR, "aviation_mro.db")
DEFAULT_SQLITE_URL = f"sqlite:///{DEFAULT_SQLITE_PATH}"

DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_SQLITE_URL)

# Render.com uses postgres:// but SQLAlchemy 1.4+ requires postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    print(f"🔧 Fixed DATABASE_URL: postgres:// -> postgresql://")

# Try to detect if we're in local development mode
IS_LOCAL_DEV = os.environ.get("LOCAL_DEV", "").lower() in ("1", "true", "yes")

IS_SQLITE = DATABASE_URL.startswith("sqlite://")

engine_kwargs = {
    "pool_pre_ping": True,
}

# SQLite needs a special connect arg; Postgres/MySQL do not.
if IS_SQLITE:
    engine_kwargs["connect_args"] = {"check_same_thread": False}

# For PostgreSQL, try to connect; if it fails, fall back to SQLite
if not IS_SQLITE and not IS_LOCAL_DEV:
    try:
        # PostgreSQL doesn't accept 'timeout' in connect_args
        engine = create_engine(DATABASE_URL, **engine_kwargs)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print(f"✅ Connected to PostgreSQL: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'database'}")
    except Exception as e:
        print(f"⚠️  PostgreSQL unavailable ({type(e).__name__}: {e}), falling back to local SQLite")
        print(f"   Path: {DEFAULT_SQLITE_PATH}")
        DATABASE_URL = DEFAULT_SQLITE_URL
        IS_SQLITE = True
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        engine = create_engine(DATABASE_URL, **engine_kwargs)
else:
    if IS_LOCAL_DEV:
        print(f"🔧 LOCAL_DEV=1 detected, using local SQLite: {DEFAULT_SQLITE_PATH}")
        DATABASE_URL = DEFAULT_SQLITE_URL
        IS_SQLITE = True
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(DATABASE_URL, **engine_kwargs)

def _ensure_postgres_enums(current_engine):
    """Ensure PostgreSQL enum types contain expected values.

    Specifically validates/patches `enginestatus` to include '-' which is used
    in the UI to represent "no status/unspecified". On some Render deployments
    older migrations may have created the enum without this value, causing
    psycopg2 InvalidTextRepresentation errors when saving.
    """
    try:
        # Only relevant for Postgres
        url = str(current_engine.url)
        if not url.startswith("postgresql://"):
            return

        # Run in AUTOCOMMIT because ADD VALUE cannot run inside a transaction block
        with current_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(
                """
                DO $$
                DECLARE
                    have_type boolean := EXISTS (
                        SELECT 1 FROM pg_type WHERE typname = 'enginestatus'
                    );
                BEGIN
                    IF have_type THEN
                        -- Ensure '-' value exists
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_enum e
                            JOIN pg_type t ON t.oid = e.enumtypid
                            WHERE t.typname = 'enginestatus' AND e.enumlabel = '-'::text
                        ) THEN
                            ALTER TYPE enginestatus ADD VALUE '-';
                        END IF;
                        -- Ensure core values exist (idempotent checks)
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
                            WHERE t.typname = 'enginestatus' AND e.enumlabel = 'SV'
                        ) THEN ALTER TYPE enginestatus ADD VALUE 'SV'; END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
                            WHERE t.typname = 'enginestatus' AND e.enumlabel = 'US'
                        ) THEN ALTER TYPE enginestatus ADD VALUE 'US'; END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
                            WHERE t.typname = 'enginestatus' AND e.enumlabel = 'INSTALLED'
                        ) THEN ALTER TYPE enginestatus ADD VALUE 'INSTALLED'; END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
                            WHERE t.typname = 'enginestatus' AND e.enumlabel = 'REMOVED'
                        ) THEN ALTER TYPE enginestatus ADD VALUE 'REMOVED'; END IF;
                    END IF;
                END $$;
                """
            ))
            print("✅ Verified/updated PostgreSQL enum 'enginestatus' values")
    except Exception as e:
        # Non-fatal: app can still run; log for visibility
        print(f"⚠️  Enum check failed ({type(e).__name__}): {e}")


_ensure_postgres_enums(engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()