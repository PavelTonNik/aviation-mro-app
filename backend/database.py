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
        test_engine = create_engine(DATABASE_URL, **engine_kwargs)
        with test_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine = test_engine
        print(f"✅ Connected to PostgreSQL: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else DATABASE_URL}")
    except Exception as e:
        print(f"⚠️  PostgreSQL unavailable ({type(e).__name__}), falling back to local SQLite")
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

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()