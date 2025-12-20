"""
Quick database check script
"""
import sqlite3

db_path = "aviation_mro.db"

print("=" * 60)
print("Database Status Check")
print("=" * 60)

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check aircrafts table
    print("\n1. AIRCRAFTS:")
    cursor.execute("SELECT tail_number, total_time, total_cycles FROM aircrafts")
    aircrafts = cursor.fetchall()
    if aircrafts:
        for ac in aircrafts:
            print(f"   {ac[0]}: {ac[1] or 0} hrs, {ac[2] or 0} cyc")
    else:
        print("   ⚠️  No aircraft found!")
    
    # Check engines table
    print("\n2. ENGINES (INSTALLED):")
    cursor.execute("""
        SELECT e.current_sn, e.position, a.tail_number, e.total_time, e.total_cycles,
               e.tsn_at_install, e.csn_at_install, e.install_date
        FROM engines e
        LEFT JOIN aircrafts a ON e.aircraft_id = a.id
        WHERE e.status = 'INSTALLED'
    """)
    engines = cursor.fetchall()
    if engines:
        for eng in engines:
            print(f"   {eng[0]} @ {eng[2]} Pos-{eng[1]}: TSN={eng[3] or 0}, TSN@Install={eng[5] or 'NULL'}")
    else:
        print("   ⚠️  No installed engines found!")
    
    # Check if new fields exist
    print("\n3. SCHEMA CHECK:")
    cursor.execute("PRAGMA table_info(engines)")
    columns = [row[1] for row in cursor.fetchall()]
    
    required_fields = ['tsn_at_install', 'csn_at_install', 'install_date']
    for field in required_fields:
        if field in columns:
            print(f"   ✅ {field}")
        else:
            print(f"   ❌ {field} - MISSING! Run migrate_db.py")
    
    # Check aircrafts fields
    cursor.execute("PRAGMA table_info(aircrafts)")
    ac_columns = [row[1] for row in cursor.fetchall()]
    
    ac_required = ['total_time', 'total_cycles']
    for field in ac_required:
        if field in ac_columns:
            print(f"   ✅ aircrafts.{field}")
        else:
            print(f"   ❌ aircrafts.{field} - MISSING! Run migrate_db.py")
    
    # Check action_logs
    cursor.execute("PRAGMA table_info(action_logs)")
    log_columns = [row[1] for row in cursor.fetchall()]
    
    log_required = ['to_aircraft', 'position']
    for field in log_required:
        if field in log_columns:
            print(f"   ✅ action_logs.{field}")
        else:
            print(f"   ❌ action_logs.{field} - MISSING! Run migrate_db.py")
    
    # Check FLIGHT logs
    print("\n4. FLIGHT LOGS:")
    cursor.execute("SELECT COUNT(*) FROM action_logs WHERE action_type = 'FLIGHT'")
    flight_count = cursor.fetchone()[0]
    print(f"   Total FLIGHT entries: {flight_count}")
    
    conn.close()
    
    print("\n" + "=" * 60)
    print("RECOMMENDATIONS:")
    print("=" * 60)
    
    if not aircrafts:
        print("⚠️  No aircraft in database. Run seed_data.py")
    
    if not engines:
        print("⚠️  No installed engines. Install engines via Installation form")
    
    if 'tsn_at_install' not in columns:
        print("❌ Missing new fields. Run: python migrate_db.py")
    
    if aircrafts and engines and 'tsn_at_install' in columns:
        print("✅ Database structure looks good!")
        print("💡 If dashboard is empty, check browser console (F12) for errors")
    
except Exception as e:
    print(f"\n❌ ERROR: {e}")

print("\n" + "=" * 60)
