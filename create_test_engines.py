"""
Создание тестовых двигателей для проверки функционала
"""
import sqlite3
from datetime import datetime

conn = sqlite3.connect('aviation_mro.db')
cur = conn.cursor()

# Получаем ID самолетов
cur.execute("SELECT id, tail_number FROM aircrafts")
aircrafts = cur.fetchall()

if not aircrafts:
    print("❌ ERROR: No aircrafts in database!")
    print("   Run: python init_visual.py first")
    conn.close()
    exit(1)

# Получаем ID локации
cur.execute("SELECT id FROM locations WHERE name='SHJ' LIMIT 1")
location = cur.fetchone()
location_id = location[0] if location else 1

print("\n=== Creating test engines ===\n")

# Создаем по 2 двигателя на каждый самолет (позиции 1 и 2)
test_engines = []

for idx, (aircraft_id, tail) in enumerate(aircrafts):
    # Двигатель на позиции 1
    eng1_sn = f"TEST{(idx*2)+1:03d}"
    test_engines.append({
        'original_sn': eng1_sn,
        'gss_sn': eng1_sn,
        'current_sn': eng1_sn,
        'model': 'CF6-50E2',
        'status': 'INSTALLED',
        'total_time': 15000.0 + (idx * 1000),
        'total_cycles': 8000 + (idx * 500),
        'aircraft_id': aircraft_id,
        'position': 1,
        'tsn_at_install': 14000.0 + (idx * 1000),
        'csn_at_install': 7500 + (idx * 500),
        'install_date': '2024-01-15'
    })
    
    # Двигатель на позиции 2
    eng2_sn = f"TEST{(idx*2)+2:03d}"
    test_engines.append({
        'original_sn': eng2_sn,
        'gss_sn': eng2_sn,
        'current_sn': eng2_sn,
        'model': 'CF6-50E2',
        'status': 'INSTALLED',
        'total_time': 16000.0 + (idx * 1000),
        'total_cycles': 8500 + (idx * 500),
        'aircraft_id': aircraft_id,
        'position': 2,
        'tsn_at_install': 15000.0 + (idx * 1000),
        'csn_at_install': 8000 + (idx * 500),
        'install_date': '2024-02-20'
    })
    
    print(f"✅ {tail}:")
    print(f"   Position 1: {eng1_sn} (TSN: 15000h, CSN: 8000)")
    print(f"   Position 2: {eng2_sn} (TSN: 16000h, CSN: 8500)")

# Вставляем в базу
for eng in test_engines:
    cur.execute("""
        INSERT INTO engines (
            original_sn, gss_sn, current_sn, model, status,
            total_time, total_cycles, aircraft_id, position,
            tsn_at_install, csn_at_install, install_date, location_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        eng['original_sn'], eng['gss_sn'], eng['current_sn'], 
        eng['model'], eng['status'], eng['total_time'], eng['total_cycles'],
        eng['aircraft_id'], eng['position'], eng['tsn_at_install'],
        eng['csn_at_install'], eng['install_date'], location_id
    ))

conn.commit()
conn.close()

print(f"\n{'='*60}")
print(f"✅ Created {len(test_engines)} test engines successfully!")
print(f"{'='*60}")
print("\nNow you can:")
print("1. Open ENG Parameters")
print("2. Select aircraft and position")
print("3. Enter N1/N2/EGT values")
print("4. Click Save Parameters")
print(f"{'='*60}\n")
