"""
Script to populate database with test data for dashboard demonstration
"""
import sqlite3
from datetime import datetime

db_path = "aviation_mro.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("Adding test data for dashboard demonstration...")

try:
    # Check if we have aircraft
    cursor.execute("SELECT id, tail_number FROM aircrafts")
    aircrafts = cursor.fetchall()
    print(f"\nFound {len(aircrafts)} aircraft:")
    for ac in aircrafts:
        print(f"  - {ac[1]} (ID: {ac[0]})")
    
    # Update aircraft total hours and cycles
    print("\nUpdating aircraft hours...")
    cursor.execute("UPDATE aircrafts SET total_time = 45623.5, total_cycles = 28450 WHERE tail_number = 'ER-BAT'")
    cursor.execute("UPDATE aircrafts SET total_time = 38912.2, total_cycles = 24100 WHERE tail_number = 'ER-BAR'")
    cursor.execute("UPDATE aircrafts SET total_time = 52341.8, total_cycles = 31220 WHERE tail_number = 'ER-BAQ'")
    
    # Check if we have engines
    cursor.execute("SELECT id, current_sn, aircraft_id, position FROM engines WHERE status = 'INSTALLED'")
    engines = cursor.fetchall()
    print(f"\nFound {len(engines)} installed engines:")
    for eng in engines:
        print(f"  - {eng[1]} on aircraft_id {eng[2]} position {eng[3]}")
    
    if engines:
        # Update engine parameters with realistic data
        for eng in engines:
            eng_id, sn, ac_id, pos = eng
            
            # Generate realistic N1/N2 values
            n1_cruise = 85.0 + (pos * 0.5)
            n1_takeoff = 95.0 + (pos * 0.3)
            n2_cruise = 92.0 + (pos * 0.4)
            n2_takeoff = 98.0 + (pos * 0.2)
            
            # Set installation data
            tsn_at_install = 15000.0 + (pos * 500)
            csn_at_install = 9000 + (pos * 200)
            total_time = 23450.0 + (pos * 800)
            total_cycles = 14200 + (pos * 350)
            
            cursor.execute("""
                UPDATE engines 
                SET n1_cruise = ?, n1_takeoff = ?, n2_cruise = ?, n2_takeoff = ?,
                    tsn_at_install = ?, csn_at_install = ?,
                    total_time = ?, total_cycles = ?,
                    install_date = ?
                WHERE id = ?
            """, (n1_cruise, n1_takeoff, n2_cruise, n2_takeoff,
                  tsn_at_install, csn_at_install,
                  total_time, total_cycles,
                  '2024-01-15 10:30:00',
                  eng_id))
            
            print(f"  ✓ Updated engine {sn}: TSN={total_time}, CSN={total_cycles}")
    
    conn.commit()
    print("\n✅ Test data added successfully!")
    
    # Show summary
    print("\n=== SUMMARY ===")
    cursor.execute("""
        SELECT a.tail_number, a.total_time, a.total_cycles,
               COUNT(e.id) as engine_count
        FROM aircrafts a
        LEFT JOIN engines e ON e.aircraft_id = a.id AND e.status = 'INSTALLED'
        GROUP BY a.id
    """)
    
    for row in cursor.fetchall():
        print(f"{row[0]}: {row[1]} hrs, {row[2]} cyc, {row[3]} engines")
    
except Exception as e:
    print(f"✗ Error: {e}")
    conn.rollback()
finally:
    conn.close()
