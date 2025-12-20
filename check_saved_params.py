import sqlite3

conn = sqlite3.connect('aviation_mro.db')
cur = conn.cursor()

cur.execute('''
    SELECT current_sn, n1_takeoff, n2_takeoff, egt_takeoff, 
           n1_cruise, n2_cruise, egt_cruise 
    FROM engines 
    WHERE current_sn = 'TEST005'
''')

r = cur.fetchone()

print('\n=== TEST005 Saved Parameters ===\n')
print(f'Takeoff:')
print(f'  N1:  {r[1]}')
print(f'  N2:  {r[2]}')
print(f'  EGT: {r[3]}')
print(f'\nCruise:')
print(f'  N1:  {r[4]}')
print(f'  N2:  {r[5]}')
print(f'  EGT: {r[6]}')
print()

conn.close()
