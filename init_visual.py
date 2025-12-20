"""
Создание базовой структуры базы данных с самолетами (без данных)
Используйте этот скрипт чтобы увидеть визуальную часть дашборда
"""
import sqlite3

db_path = "aviation_mro.db"

print("=" * 60)
print("Creating basic database structure...")
print("=" * 60)

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Проверяем есть ли уже самолеты
    cursor.execute("SELECT COUNT(*) FROM aircrafts")
    count = cursor.fetchone()[0]
    
    if count > 0:
        print(f"\n✅ Found {count} aircraft(s) in database")
        print("   Database already initialized!")
    else:
        print("\n📝 Creating aircraft entries...")
        
        # Создаем 3 самолета с нулевыми данными
        aircrafts = [
            ("ER-BAT", "Boeing 747-200", "22545", "SHJ", 0.0, 0),
            ("ER-BAR", "Boeing 747-200", "23813", "SHJ", 0.0, 0),
            ("ER-BAQ", "Boeing 747-200", "239139", "SHJ", 0.0, 0)
        ]
        
        cursor.executemany("""
            INSERT INTO aircrafts (tail_number, model, msn, current_sn, total_time, total_cycles)
            VALUES (?, ?, ?, ?, ?, ?)
        """, aircrafts)
        
        conn.commit()
        print("   ✅ Created 3 aircraft entries:")
        print("      - ER-BAT (Boeing 747-200)")
        print("      - ER-BAR (Boeing 747-200)")
        print("      - ER-BAQ (Boeing 747-200)")
    
    # Проверяем локации
    cursor.execute("SELECT COUNT(*) FROM locations")
    loc_count = cursor.fetchone()[0]
    
    if loc_count == 0:
        print("\n📝 Creating location entries...")
        locations = [
            ("SHJ", "Sharjah"),
            ("FRU", "Bishkek"),
            ("DXB", "Dubai"),
            ("MIAMI", "Miami"),
            ("Rome (Italy)", "Rome (Italy)")
        ]
        
        cursor.executemany("""
            INSERT INTO locations (name, city)
            VALUES (?, ?)
        """, locations)
        
        conn.commit()
        print("   ✅ Created 4 locations")
    else:
        print(f"\n✅ Found {loc_count} location(s) in database")
    
    conn.close()
    
    print("\n" + "=" * 60)
    print("✅ Basic structure created successfully!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Start server: START.bat")
    print("2. Open browser: http://localhost:8000")
    print("3. You will see 3 aircraft cards with 0 hours")
    print("4. All 4 engine positions will show 'No Engine Installed'")
    print("\n💡 This allows you to see the visual design")
    print("   before entering data from your Excel files")
    print("=" * 60)
    
except sqlite3.IntegrityError as e:
    print(f"\n⚠️  Data already exists: {e}")
    print("   This is OK - database is already initialized")
except Exception as e:
    print(f"\n❌ ERROR: {e}")
