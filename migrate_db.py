"""
Скрипт для миграции базы данных - добавление новых полей в таблицу engines
Запустите этот файл ОДИН РАЗ для обновления структуры БД
"""
from backend.database import engine
from sqlalchemy import text

def migrate():
    conn = engine.connect()
    trans = conn.begin()
    try:
        # Добавляем новые поля в таблицу engines (если их еще нет)
        print("Добавление новых полей в таблицу engines...")
        
        # Проверяем, существует ли поле 'model'
        result = conn.execute(text("PRAGMA table_info(engines)"))
        columns = [row[1] for row in result]
        
        if 'model' not in columns:
            conn.execute(text("ALTER TABLE engines ADD COLUMN model VARCHAR"))
            print("✓ Добавлено поле 'model'")
        
        if 'photo_url' not in columns:
            conn.execute(text("ALTER TABLE engines ADD COLUMN photo_url VARCHAR"))
            print("✓ Добавлено поле 'photo_url'")
        
        if 'n1_takeoff' not in columns:
            conn.execute(text("ALTER TABLE engines ADD COLUMN n1_takeoff FLOAT"))
            print("✓ Добавлено поле 'n1_takeoff'")
            
        if 'n1_cruise' not in columns:
            conn.execute(text("ALTER TABLE engines ADD COLUMN n1_cruise FLOAT"))
            print("✓ Добавлено поле 'n1_cruise'")
        
        if 'n2_takeoff' not in columns:
            conn.execute(text("ALTER TABLE engines ADD COLUMN n2_takeoff FLOAT"))
            print("✓ Добавлено поле 'n2_takeoff'")
        
        if 'n2_cruise' not in columns:
            conn.execute(text("ALTER TABLE engines ADD COLUMN n2_cruise FLOAT"))
            print("✓ Добавлено поле 'n2_cruise'")
        
        if 'tsn_at_install' not in columns:
            conn.execute(text("ALTER TABLE engines ADD COLUMN tsn_at_install FLOAT"))
            print("✓ Добавлено поле 'tsn_at_install'")
        
        if 'csn_at_install' not in columns:
            conn.execute(text("ALTER TABLE engines ADD COLUMN csn_at_install INTEGER"))
            print("✓ Добавлено поле 'csn_at_install'")
        
        if 'install_date' not in columns:
            conn.execute(text("ALTER TABLE engines ADD COLUMN install_date DATETIME"))
            print("✓ Добавлено поле 'install_date'")
        
        if 'egt_takeoff' not in columns:
            conn.execute(text("ALTER TABLE engines ADD COLUMN egt_takeoff FLOAT"))
            print("✓ Добавлено поле 'egt_takeoff'")
        
        if 'egt_cruise' not in columns:
            conn.execute(text("ALTER TABLE engines ADD COLUMN egt_cruise FLOAT"))
            print("✓ Добавлено поле 'egt_cruise'")
        
        if 'last_param_update' not in columns:
            conn.execute(text("ALTER TABLE engines ADD COLUMN last_param_update DATETIME"))
            print("✓ Добавлено поле 'last_param_update'")
        
        # Проверяем таблицу action_logs
        result = conn.execute(text("PRAGMA table_info(action_logs)"))
        log_columns = [row[1] for row in result]
        
        if 'to_aircraft' not in log_columns:
            conn.execute(text("ALTER TABLE action_logs ADD COLUMN to_aircraft VARCHAR"))
            print("✓ Добавлено поле 'to_aircraft' в action_logs")
        
        if 'position' not in log_columns:
            conn.execute(text("ALTER TABLE action_logs ADD COLUMN position INTEGER"))
            print("✓ Добавлено поле 'position' в action_logs")
        
        # Проверяем таблицу aircrafts
        result = conn.execute(text("PRAGMA table_info(aircrafts)"))
        ac_columns = [row[1] for row in result]
        
        if 'total_time' not in ac_columns:
            conn.execute(text("ALTER TABLE aircrafts ADD COLUMN total_time FLOAT DEFAULT 0.0"))
            print("✓ Добавлено поле 'total_time' в aircrafts")
        
        if 'total_cycles' not in ac_columns:
            conn.execute(text("ALTER TABLE aircrafts ADD COLUMN total_cycles INTEGER DEFAULT 0"))
            print("✓ Добавлено поле 'total_cycles' в aircrafts")
        
        trans.commit()
        print("\n✅ Миграция завершена успешно!")
        
    except Exception as e:
        print(f"❌ Ошибка при миграции: {e}")
        trans.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
