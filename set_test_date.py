"""
Добавляем тестовую дату last_param_update для двигателей
"""
import sqlite3
from datetime import datetime

conn = sqlite3.connect('aviation_mro.db')
cur = conn.cursor()

# Обновляем TEST005 с датой
test_date = '2025-11-30'

cur.execute("""
    UPDATE engines 
    SET last_param_update = ? 
    WHERE current_sn = 'TEST005'
""", (test_date,))

conn.commit()

print(f"\n✅ Updated TEST005 with param date: {test_date}")

# Проверяем
cur.execute('SELECT current_sn, last_param_update FROM engines WHERE current_sn = "TEST005"')
r = cur.fetchone()
print(f"Verification: {r[0]} - {r[1]}")

conn.close()
