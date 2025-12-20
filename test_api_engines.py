import requests
import json

print("\n=== Testing /api/engines endpoint ===\n")

try:
    response = requests.get('http://localhost:8000/api/engines')
    
    if response.status_code == 200:
        engines = response.json()
        print(f"✅ API returned {len(engines)} engines\n")
        
        for eng in engines:
            print(f"ID: {eng['id']}")
            print(f"  S/N: {eng['current_sn']}")
            print(f"  Aircraft: {eng.get('aircraft', 'NULL')}")
            print(f"  Position: {eng.get('position', 'NULL')}")
            print(f"  Status: {eng['status']}")
            print(f"  Aircraft ID: {eng.get('aircraft_id', 'NULL')}")
            print()
    else:
        print(f"❌ API Error: {response.status_code}")
        print(response.text)
        
except Exception as e:
    print(f"❌ Connection Error: {e}")
    print("\nMake sure server is running: START.bat")
