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
