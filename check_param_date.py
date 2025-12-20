import sqlite3

conn = sqlite3.connect('aviation_mro.db')
cur = conn.cursor()

cur.execute('SELECT current_sn, last_param_update FROM engines WHERE current_sn = "TEST005"')
r = cur.fetchone()

print(f'\nEngine: {r[0]}')
print(f'last_param_update: {r[1]}')

# Проверим также историю параметров
cur.execute('SELECT date, n1_takeoff, egt_takeoff FROM engine_parameter_history WHERE engine_id = 5')
history = cur.fetchall()

print(f'\nHistory records: {len(history)}')
for h in history:
    print(f'  Date: {h[0]}, N1: {h[1]}, EGT: {h[2]}')

conn.close()
