-- ============================================
-- GSS Assignments Table
-- ============================================
-- Таблица для отслеживания присвоения внутрикомпанейских номеров (GSS ID)
-- к двигателям. Позволяет отслеживать смену шильдиков (nameplate).
--
-- Логика:
-- - Если запись есть → GSS ID занят
-- - Если записи нет → GSS ID свободен
-- - При DELETE → GSS ID автоматически освобождается
-- ============================================

CREATE TABLE IF NOT EXISTS gss_assignments (
    id SERIAL PRIMARY KEY,
    gss_id INTEGER NOT NULL UNIQUE,  -- GSS ID должен быть уникальным
    
    -- Связь с двигателем
    engine_id INTEGER NOT NULL REFERENCES engines(id) ON DELETE CASCADE,
    original_sn VARCHAR NOT NULL,    -- Snapshot Original SN на момент присвоения
    current_sn VARCHAR,               -- Snapshot Current SN (если отличается)
    
    -- Медиа и примечания
    photo_url VARCHAR,                -- URL фото (если вставлена ссылка)
    photo_filename VARCHAR,           -- Имя файла (если загружен файл)
    remarks TEXT,                     -- Примечания
    
    -- Метаданные
    assigned_by INTEGER NOT NULL REFERENCES users(id),
    assigned_date TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Индексы для быстрого поиска
CREATE INDEX IF NOT EXISTS idx_gss_assignments_gss_id ON gss_assignments(gss_id);
CREATE INDEX IF NOT EXISTS idx_gss_assignments_engine_id ON gss_assignments(engine_id);
CREATE INDEX IF NOT EXISTS idx_gss_assignments_assigned_date ON gss_assignments(assigned_date DESC);

-- Комментарии
COMMENT ON TABLE gss_assignments IS 'GSS ID assignments to engines with nameplate tracking';
COMMENT ON COLUMN gss_assignments.gss_id IS 'Internal company ID number (unique)';
COMMENT ON COLUMN gss_assignments.original_sn IS 'Original serial number at time of assignment';
COMMENT ON COLUMN gss_assignments.current_sn IS 'Current serial number (if nameplate was changed)';
COMMENT ON COLUMN gss_assignments.photo_url IS 'URL to photo (if pasted)';
COMMENT ON COLUMN gss_assignments.photo_filename IS 'Uploaded photo filename';
COMMENT ON COLUMN gss_assignments.remarks IS 'Additional notes';
