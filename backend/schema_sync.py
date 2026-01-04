import os
import pathlib
import sys

import psycopg2


SQL_FILE = pathlib.Path(__file__).resolve().parent.parent / "schema_sync_postgres.sql"


def main() -> int:
    if not SQL_FILE.exists():
        print(f"Schema file not found: {SQL_FILE}", file=sys.stderr)
        return 1

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1

    # Render uses postgres:// but psycopg2 and SQLAlchemy need postgresql://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
        print("🔧 Fixed DATABASE_URL: postgres:// -> postgresql://")

    sql = SQL_FILE.read_text(encoding="utf-8")
    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
        print("✅ schema synced successfully")
        return 0
    except Exception as e:
        print(f"❌ Schema sync failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
