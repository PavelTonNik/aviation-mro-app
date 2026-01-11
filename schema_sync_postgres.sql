-- Run this on Render Postgres to align schema with current models
-- Safe to re-run: uses IF NOT EXISTS and column-exists checks

-- Add price and from_location columns to engines
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'engines' AND column_name = 'price'
    ) THEN
        ALTER TABLE engines ADD COLUMN price double precision;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'engines' AND column_name = 'from_location'
    ) THEN
        ALTER TABLE engines ADD COLUMN from_location varchar;
    END IF;
END$$;

-- Add is_active column to action_logs for tracking installation status
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'action_logs' AND column_name = 'is_active'
    ) THEN
        ALTER TABLE action_logs ADD COLUMN is_active boolean DEFAULT TRUE;
        
        -- Умная логика для старых записей:
        -- Если INSTALL, проверяем: есть ли REMOVE после него для того же двигателя
        UPDATE action_logs SET is_active = FALSE 
        WHERE action_type = 'INSTALL' 
        AND EXISTS (
            SELECT 1 FROM action_logs AS remove_log
            WHERE remove_log.engine_id = action_logs.engine_id
            AND remove_log.action_type = 'REMOVE'
            AND remove_log.date > action_logs.date
        );
        
        -- Все не-INSTALL записи помечаем как неактивные
        UPDATE action_logs SET is_active = FALSE WHERE action_type != 'INSTALL';
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

-- Borescope Inspections table
CREATE TABLE IF NOT EXISTS borescope_inspections (
    id SERIAL PRIMARY KEY,
    date VARCHAR NOT NULL,
    aircraft VARCHAR NOT NULL,
    serial_number VARCHAR NOT NULL,
    position VARCHAR NOT NULL,
    gss_id VARCHAR,
    inspector VARCHAR NOT NULL,
    link VARCHAR,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Purchase Orders table
CREATE TABLE IF NOT EXISTS purchase_orders (
    id SERIAL PRIMARY KEY,
    date VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    part_number VARCHAR,
    serial_number VARCHAR,
    price DOUBLE PRECISION,
    purpose VARCHAR NOT NULL,
    aircraft VARCHAR NOT NULL,
    ro_number VARCHAR NOT NULL,
    link VARCHAR,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add missing columns to purchase_orders if table already exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'purchase_orders' AND column_name = 'part_number'
    ) THEN
        ALTER TABLE purchase_orders ADD COLUMN part_number VARCHAR;
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'purchase_orders' AND column_name = 'serial_number'
    ) THEN
        ALTER TABLE purchase_orders ADD COLUMN serial_number VARCHAR;
    END IF;
END$$;

-- Scheduled Events table (Calendar)
CREATE TABLE IF NOT EXISTS scheduled_events (
    id SERIAL PRIMARY KEY,
    event_date VARCHAR NOT NULL,
    event_time VARCHAR,
    event_type VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    description TEXT,
    engine_id INTEGER REFERENCES engines(id),
    serial_number VARCHAR,
    location VARCHAR,
    from_location VARCHAR,
    to_location VARCHAR,
    status VARCHAR DEFAULT 'PLANNED',
    priority VARCHAR DEFAULT 'MEDIUM',
    color VARCHAR DEFAULT '#3788d8',
    created_by VARCHAR,
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
CREATE INDEX IF NOT EXISTS idx_borescope_serial ON borescope_inspections(serial_number);
CREATE INDEX IF NOT EXISTS idx_borescope_date ON borescope_inspections(date);
CREATE INDEX IF NOT EXISTS idx_purchase_order_date ON purchase_orders(date);
CREATE INDEX IF NOT EXISTS idx_purchase_order_serial ON purchase_orders(serial_number);
CREATE INDEX IF NOT EXISTS idx_scheduled_events_date ON scheduled_events(event_date);
CREATE INDEX IF NOT EXISTS idx_scheduled_events_type ON scheduled_events(event_type);
CREATE INDEX IF NOT EXISTS idx_scheduled_events_status ON scheduled_events(status);

-- Shipments table (Logistics & Schedules Tracking)
CREATE TABLE IF NOT EXISTS shipments (
    id SERIAL PRIMARY KEY,
    shipment_type VARCHAR(50) NOT NULL,  -- ENGINE, PARTS
    status VARCHAR(50) DEFAULT 'PLANNED',  -- PLANNED, IN_TRANSIT, DELIVERED, DELAYED, CANCELLED
    
    -- For ENGINE type
        engine_model VARCHAR(100),
        gss_id VARCHAR(100),
    engine_id INTEGER REFERENCES engines(id),
    destination_location VARCHAR(255),
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'shipments' AND column_name = 'engine_model'
        ) THEN
            ALTER TABLE shipments ADD COLUMN engine_model VARCHAR(100);
        END IF;
    
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'shipments' AND column_name = 'gss_id'
        ) THEN
            ALTER TABLE shipments ADD COLUMN gss_id VARCHAR(100);
        END IF;
    END$$;
    
    -- For PARTS type
    part_name VARCHAR(255),
    part_category VARCHAR(100),
    part_quantity INTEGER,
    reserved_quantity INTEGER DEFAULT 0,
    
    -- Shipping and delivery
    departure_date TIMESTAMPTZ,
    expected_delivery_date TIMESTAMPTZ NOT NULL,
    actual_delivery_date TIMESTAMPTZ,
    
    -- Tracking
    supplier_name VARCHAR(255),
    tracking_number VARCHAR(255),
    notes TEXT,
    
    -- User and timestamps
    created_by VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_by VARCHAR(255),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indices for shipments performance
CREATE INDEX IF NOT EXISTS idx_shipments_status ON shipments(status);
CREATE INDEX IF NOT EXISTS idx_shipments_type ON shipments(shipment_type);
CREATE INDEX IF NOT EXISTS idx_shipments_delivery_date ON shipments(expected_delivery_date);
CREATE INDEX IF NOT EXISTS idx_shipments_engine_id ON shipments(engine_id);

-- Condition Statuses (Store Balance)
CREATE TABLE IF NOT EXISTS condition_statuses (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    color VARCHAR(20) NOT NULL DEFAULT '#6c757d',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_condition_statuses_name ON condition_statuses(name);

-- Populate from_location with existing location data for backward compatibility
DO $$
BEGIN
    -- Copy current location names to from_location where from_location is NULL
    UPDATE engines
    SET from_location = l.name
    FROM locations l
    WHERE engines.location_id = l.id 
    AND engines.from_location IS NULL;
END$$;

-- Update enginestatus enum to include all required values
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'enginestatus') THEN
        ALTER TYPE enginestatus RENAME TO enginestatus_old;
        CREATE TYPE enginestatus AS ENUM ('SV', 'US', 'INSTALLED', 'REMOVED', '-');
        ALTER TABLE engines ALTER COLUMN status TYPE VARCHAR USING status::text;
        ALTER TABLE engines ALTER COLUMN status TYPE enginestatus USING 
            CASE 
                WHEN status = 'AS' THEN '-'::enginestatus
                WHEN status IN ('SV', 'US', 'INSTALLED', 'REMOVED', '-') THEN status::enginestatus
                ELSE '-'::enginestatus
            END;
        DROP TYPE enginestatus_old;
    ELSE
        CREATE TYPE enginestatus AS ENUM ('SV', 'US', 'INSTALLED', 'REMOVED', '-');
    END IF;
EXCEPTION WHEN OTHERS THEN
    NULL;
END$$;

-- Ensure condition_1 and condition_2 columns exist and are set to NOT NULL with defaults
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'engines' AND column_name = 'condition_1'
    ) THEN
        ALTER TABLE engines ADD COLUMN condition_1 VARCHAR DEFAULT 'SV' NOT NULL;
    ELSE
        -- Update nullable to NOT NULL with default
        ALTER TABLE engines ALTER COLUMN condition_1 SET DEFAULT 'SV';
        UPDATE engines SET condition_1 = 'SV' WHERE condition_1 IS NULL OR condition_1 = '';
        ALTER TABLE engines ALTER COLUMN condition_1 SET NOT NULL;
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'engines' AND column_name = 'condition_2'
    ) THEN
        ALTER TABLE engines ADD COLUMN condition_2 VARCHAR DEFAULT 'New' NOT NULL;
    ELSE
        -- Update nullable to NOT NULL with default
        ALTER TABLE engines ALTER COLUMN condition_2 SET DEFAULT 'New';
        UPDATE engines SET condition_2 = 'New' WHERE condition_2 IS NULL OR condition_2 = '';
        ALTER TABLE engines ALTER COLUMN condition_2 SET NOT NULL;
    END IF;
END$$;


