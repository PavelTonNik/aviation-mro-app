import sqlite3

conn = sqlite3.connect('aviation_mro.db')
cur = conn.cursor()

cur.execute('''
    SELECT e.current_sn, a.tail_number, e.position, e.status 
    FROM engines e 
    LEFT JOIN aircrafts a ON e.aircraft_id = a.id
''')

engines = cur.fetchall()

print(f'\n=== Total engines in database: {len(engines)} ===\n')

if engines:
    for e in engines:
        sn = e[0]
        ac = e[1] or 'NO AIRCRAFT'
        pos = e[2] if e[2] is not None else 'N/A'
        status = e[3]
        print(f'  • {sn} on {ac} Pos-{pos} [{status}]')
else:
    print('  ❌ NO ENGINES IN DATABASE!')
    print('\n  You need to add engines first through:')
    print('  1. Logistics → Engine Receipt (for new engines)')
    print('  2. Logistics → Installation (to install on aircraft)')

conn.close()
