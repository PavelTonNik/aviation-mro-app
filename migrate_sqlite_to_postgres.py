"""
Migrate data from local SQLite DB to PostgreSQL without changing application code.

Usage (Windows PowerShell):

$env:POSTGRES_URL = "postgresql+psycopg2://user:pass@localhost:5432/engapp"
python migrate_sqlite_to_postgres.py

Optional envs:
- SQLITE_PATH: path to existing SQLite file (defaults to backend/aviation_mro.db)

This script:
1. Connects to SQLite and PostgreSQL.
2. Creates PostgreSQL tables from SQLAlchemy models.
3. Copies rows table-by-table preserving IDs.
4. Resets PostgreSQL sequences to max(id) for each table.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import os
import sys

# Import models using module path
try:
    from backend import models
except Exception as e:
    print("Failed to import backend.models:", e)
    sys.exit(1)

SQLITE_PATH = os.environ.get("SQLITE_PATH") or os.path.join(os.path.dirname(__file__), "backend", "aviation_mro.db")
SQLITE_URL = f"sqlite:///{SQLITE_PATH}"
POSTGRES_URL = os.environ.get("POSTGRES_URL")
if not POSTGRES_URL:
    print("POSTGRES_URL env var is required, e.g. postgresql+psycopg2://user:pass@host:5432/dbname")
    sys.exit(1)

print(f"SQLite: {SQLITE_URL}")
print(f"Postgres: {POSTGRES_URL}")

src_engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
# pre-ping recommended for PG
dst_engine = create_engine(POSTGRES_URL, pool_pre_ping=True)

SrcSession = sessionmaker(bind=src_engine)
DstSession = sessionmaker(bind=dst_engine)

# Create tables on Postgres
print("Creating tables on PostgreSQL from models...")
models.Base.metadata.create_all(bind=dst_engine)

# Define copy order to satisfy FKs
COPY_ORDER = [
    models.Location,
    models.Aircraft,
    models.Engine,
    models.Part,
    models.StoreItem,
    models.ActionLog,
    models.EngineParameterHistory,
    models.UtilizationParameter,
    models.BoroscopeInspection,
    models.PurchaseOrder,
    models.User,
    models.Notification,
]

def copy_table(cls, ssession, dsession):
    name = cls.__tablename__
    print(f"Copying {name}...")
    rows = ssession.query(cls).all()
    if not rows:
        print(f"  No rows")
        return 0
    # Build dicts of column values
    cols = [c.name for c in cls.__table__.columns]
    count = 0
    for row in rows:
        data = {c: getattr(row, c) for c in cols}
        inst = cls(**data)
        dsession.add(inst)
        count += 1
    dsession.commit()
    print(f"  Inserted {count}")
    return count

# Reset sequence for serial PKs so next insert won't collide
RESET_SEQUENCE_SQL = "SELECT setval(pg_get_serial_sequence(:table_name, :id_col), COALESCE((SELECT MAX(id) FROM \"" + "{table}" + "\"), 1))"

def reset_sequence(table_name, conn):
    try:
        # dynamic format table into string literal-safe query
        sql = f"SELECT setval(pg_get_serial_sequence('\"{table_name}\"','id'), COALESCE((SELECT MAX(id) FROM \"{table_name}\"), 1))"
        conn.execute(text(sql))
        print(f"  Sequence reset for {table_name}")
    except Exception as e:
        print(f"  Sequence reset skipped for {table_name}: {e}")

with SrcSession() as ssession, DstSession() as dsession:
    for cls in COPY_ORDER:
        copy_table(cls, ssession, dsession)

    # Reset sequences
    with dst_engine.connect() as conn:
        for cls in COPY_ORDER:
            reset_sequence(cls.__tablename__, conn)

print("\n✅ Migration completed.")
