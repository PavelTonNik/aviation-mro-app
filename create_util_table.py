# Создание таблицы utilization_parameters
from backend import models, database

def create_utilization_params_table():
    print("Создание таблицы utilization_parameters...")
    try:
        # Создаем все таблицы из models (включая новую utilization_parameters)
        models.Base.metadata.create_all(bind=database.engine)
        print("✅ Таблица utilization_parameters успешно создана!")
        
        # Проверяем
        import sqlite3
        conn = sqlite3.connect('aviation_mro.db')
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='utilization_parameters'")
        if cursor.fetchone():
            print("✅ Проверка: таблица существует в базе данных!")
            
            # Показываем структуру
            cursor.execute("PRAGMA table_info(utilization_parameters)")
            columns = cursor.fetchall()
            print("\n📋 Структура таблицы:")
            for col in columns:
                print(f"  - {col[1]} ({col[2]})")
        else:
            print("❌ Ошибка: таблица не найдена после создания")
        conn.close()
        
    except Exception as e:
        print(f"❌ Ошибка при создании таблицы: {e}")

if __name__ == "__main__":
    create_utilization_params_table()
