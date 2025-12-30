-- Run this on Render Postgres to align schema with current models
-- Safe to re-run: uses IF NOT EXISTS and column-exists checks

-- Add price column to engines
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'engines' AND column_name = 'price'
    ) THEN
        ALTER TABLE engines ADD COLUMN price double precision;
    END IF;
END$$;

-- Fake Installed main table
CREATE TABLE IF NOT EXISTS fake_installed (
    id SERIAL PRIMARY KEY,
    engine_id INTEGER REFERENCES engines(id),
    engine_original_sn VARCHAR NOT NULL,
    engine_current_sn VARCHAR NOT NULL,
    aircraft_id INTEGER REFERENCES aircrafts(id),
    aircraft_tail VARCHAR,
    position INTEGER,
    documented_date VARCHAR NOT NULL,
    documented_reason VARCHAR,
    old_engine_sn VARCHAR,
    new_engine_sn VARCHAR,
    is_fake BOOLEAN DEFAULT TRUE,
    actual_notes TEXT,
    created_by VARCHAR,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Fake Installed settings
CREATE TABLE IF NOT EXISTS fake_installed_settings (
    id SERIAL PRIMARY KEY,
    headers_json TEXT
);

-- Nameplate Tracker
CREATE TABLE IF NOT EXISTS nameplate_tracker (
    id SERIAL PRIMARY KEY,
    nameplate_sn VARCHAR NOT NULL,
    engine_model VARCHAR,
    gss_id VARCHAR,
    engine_orig_sn VARCHAR,
    aircraft_tail VARCHAR,
    position INTEGER,
    installed_date VARCHAR NOT NULL,
    removed_date VARCHAR,
    location_type VARCHAR,
    action_note VARCHAR,
    performed_by VARCHAR,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Custom columns (ensure exists)
CREATE TABLE IF NOT EXISTS custom_columns (
    id SERIAL PRIMARY KEY,
    table_name VARCHAR NOT NULL,
    column_key VARCHAR NOT NULL,
    column_label VARCHAR NOT NULL,
    column_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS purchase_order_custom_data (
    id SERIAL PRIMARY KEY,
    purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id),
    column_key VARCHAR NOT NULL,
    value TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indices for faster lookup
CREATE INDEX IF NOT EXISTS idx_fake_installed_engine_sn ON fake_installed(engine_original_sn, engine_current_sn);
CREATE INDEX IF NOT EXISTS idx_nameplate_sn ON nameplate_tracker(nameplate_sn);
CREATE INDEX IF NOT EXISTS idx_nameplate_gss ON nameplate_tracker(gss_id);
