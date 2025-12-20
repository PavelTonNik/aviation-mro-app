"""
Миграция: Создание таблицы истории параметров двигателя
"""
import sqlite3

db_path = "aviation_mro.db"

print("=" * 60)
print("Creating engine_parameter_history table...")
print("=" * 60)

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Проверяем существует ли таблица
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='engine_parameter_history'
    """)
    
    if cursor.fetchone():
        print("\n✅ Table 'engine_parameter_history' already exists")
    else:
        print("\n📝 Creating table 'engine_parameter_history'...")
        
        cursor.execute("""
            CREATE TABLE engine_parameter_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                engine_id INTEGER NOT NULL,
                date DATETIME NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                n1_takeoff FLOAT,
                n2_takeoff FLOAT,
                egt_takeoff FLOAT,
                n1_cruise FLOAT,
                n2_cruise FLOAT,
                egt_cruise FLOAT,
                FOREIGN KEY (engine_id) REFERENCES engines(id)
            )
        """)
        
        conn.commit()
        print("   ✅ Table created successfully!")
        
        # Создаем индексы для быстрого поиска
        cursor.execute("""
            CREATE INDEX idx_param_history_engine 
            ON engine_parameter_history(engine_id)
        """)
        
        cursor.execute("""
            CREATE INDEX idx_param_history_date 
            ON engine_parameter_history(date DESC)
        """)
        
        conn.commit()
        print("   ✅ Indexes created successfully!")
    
    conn.close()
    
    print("\n" + "=" * 60)
    print("✅ Migration completed successfully!")
    print("=" * 60)
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    print("\nPlease check your database file.")
