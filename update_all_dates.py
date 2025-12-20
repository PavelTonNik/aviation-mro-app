"""
Добавляем тестовые даты для всех двигателей
"""
import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect('aviation_mro.db')
cur = conn.cursor()

# Получаем все двигатели
cur.execute('SELECT id, current_sn FROM engines')
engines = cur.fetchall()

print("\n=== Updating param dates for all engines ===\n")

for idx, (engine_id, sn) in enumerate(engines):
    # Разные даты для разных двигателей (в ноябре)
    days_ago = idx * 3
    date = datetime(2025, 11, 30) - timedelta(days=days_ago)
    date_str = date.strftime('%Y-%m-%d')
    
    cur.execute("""
        UPDATE engines 
        SET last_param_update = ? 
        WHERE id = ?
    """, (date_str, engine_id))
    
    print(f"✅ {sn}: {date.strftime('%d.%m.%Y')}")

conn.commit()
conn.close()

print("\n✅ All engines updated with param dates!")
print("\nНажмите F5 в браузере чтобы увидеть даты на всех карточках")
