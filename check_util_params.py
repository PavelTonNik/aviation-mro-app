# Проверка таблицы Utilization Parameters
import sqlite3

def check_utilization_params():
    conn = sqlite3.connect('aviation_mro.db')
    cursor = conn.cursor()
    
    # Проверяем существует ли таблица
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='utilization_parameters'")
    table_exists = cursor.fetchone()
    
    if table_exists:
        print("✅ Таблица utilization_parameters существует!")
        
        # Получаем структуру таблицы
        cursor.execute("PRAGMA table_info(utilization_parameters)")
        columns = cursor.fetchall()
        print("\n📋 Структура таблицы:")
        for col in columns:
            print(f"  - {col[1]} ({col[2]})")
        
        # Получаем количество записей
        cursor.execute("SELECT COUNT(*) FROM utilization_parameters")
        count = cursor.fetchone()[0]
        print(f"\n📊 Количество записей в таблице: {count}")
        
        if count > 0:
            cursor.execute("SELECT * FROM utilization_parameters ORDER BY date DESC LIMIT 5")
            records = cursor.fetchall()
            print("\n🔍 Последние 5 записей:")
            for rec in records:
                print(f"  ID: {rec[0]}, Дата: {rec[1]}, Самолет: {rec[2]}, TTSN: {rec[3]}, TCSN: {rec[4]}")
    else:
        print("❌ Таблица utilization_parameters НЕ существует!")
        print("Запустите миграцию: python migrate_db.py")
    
    conn.close()

if __name__ == "__main__":
    check_utilization_params()
