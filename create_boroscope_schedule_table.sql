-- Create boroscope_schedule table
CREATE TABLE IF NOT EXISTS boroscope_schedule (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    aircraft_tail_number VARCHAR(20) NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 1 AND position <= 4),
    inspector VARCHAR(255) NOT NULL,
    remarks TEXT,
    location VARCHAR(255),
    status VARCHAR(50) DEFAULT 'Scheduled' CHECK (status IN ('Scheduled', 'Completed', 'Cancelled')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    FOREIGN KEY (aircraft_tail_number) REFERENCES aircrafts(tail_number) ON DELETE CASCADE,
    UNIQUE(aircraft_tail_number, position, date)
);

-- Create indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_boroscope_date ON boroscope_schedule(date);
CREATE INDEX IF NOT EXISTS idx_boroscope_aircraft ON boroscope_schedule(aircraft_tail_number);
CREATE INDEX IF NOT EXISTS idx_boroscope_status ON boroscope_schedule(status);

-- Alter table if it already exists (safe operation)
ALTER TABLE boroscope_schedule ADD COLUMN IF NOT EXISTS id SERIAL PRIMARY KEY;
ALTER TABLE boroscope_schedule ADD COLUMN IF NOT EXISTS date DATE NOT NULL;
ALTER TABLE boroscope_schedule ADD COLUMN IF NOT EXISTS aircraft_tail_number VARCHAR(20) NOT NULL;
ALTER TABLE boroscope_schedule ADD COLUMN IF NOT EXISTS position INTEGER NOT NULL;
ALTER TABLE boroscope_schedule ADD COLUMN IF NOT EXISTS inspector VARCHAR(255) NOT NULL;
ALTER TABLE boroscope_schedule ADD COLUMN IF NOT EXISTS remarks TEXT;
ALTER TABLE boroscope_schedule ADD COLUMN IF NOT EXISTS location VARCHAR(255);
ALTER TABLE boroscope_schedule ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'Scheduled';
ALTER TABLE boroscope_schedule ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE boroscope_schedule ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP;
