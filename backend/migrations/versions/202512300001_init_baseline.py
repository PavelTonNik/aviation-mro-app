"""Baseline migration for Render

- add price column to engines if missing
- create tables used by code but absent on Render
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "202512300001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure price column on engines
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='engines' AND column_name='price'
            ) THEN
                ALTER TABLE engines ADD COLUMN price double precision DEFAULT 0;
            END IF;
        END$$;
        """
    )

    # Custom columns (per-table column configs)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS custom_columns (
            id serial PRIMARY KEY,
            table_name varchar NOT NULL,
            column_key varchar NOT NULL,
            column_label varchar NOT NULL,
            column_order integer DEFAULT 0,
            created_at timestamptz DEFAULT now(),
            updated_at timestamptz
        );
        """
    )

    # Purchase order custom data values
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS purchase_order_custom_data (
            id serial PRIMARY KEY,
            purchase_order_id integer NOT NULL,
            column_key varchar NOT NULL,
            value text,
            created_at timestamptz DEFAULT now(),
            updated_at timestamptz
        );
        """
    )

    # Fake installed records
    op.execute(
        """
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
        );
        """
    )

    # Fake installed headers/settings
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fake_installed_settings (
            id serial PRIMARY KEY,
            headers_json text,
            created_at timestamptz DEFAULT now(),
            updated_at timestamptz
        );
        """
    )

    # Nameplate tracker
    op.execute(
        """
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
        );
        """
    )


def downgrade() -> None:
    # Safe downgrades: drop created tables, leave price column intact
    op.execute("DROP TABLE IF EXISTS nameplate_tracker;")
    op.execute("DROP TABLE IF EXISTS fake_installed_settings;")
    op.execute("DROP TABLE IF EXISTS fake_installed;")
    op.execute("DROP TABLE IF EXISTS purchase_order_custom_data;")
    op.execute("DROP TABLE IF EXISTS custom_columns;")
