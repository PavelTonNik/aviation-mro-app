import requests
import json

print("\n=== Testing /api/engines/parameters endpoint ===\n")

# Тестовые данные для сохранения параметров двигателя TEST005 (ER-BAT Position 1)
test_data = {
    "engine_id": 5,  # TEST005
    "n1_takeoff": 98.2,
    "n2_takeoff": 105.2,
    "egt_takeoff": 650.0,
    "n1_cruise": 95.0,
    "n2_cruise": 102.0,
    "egt_cruise": 620.0
}

print("Sending parameters for engine TEST005 (ER-BAT Pos-1):")
print(json.dumps(test_data, indent=2))
print()

try:
    response = requests.post(
        'http://localhost:8000/api/engines/parameters',
        json=test_data,
        headers={'Content-Type': 'application/json'}
    )
    
    if response.status_code == 200:
        result = response.json()
        print("✅ SUCCESS!")
        print(json.dumps(result, indent=2))
    else:
        print(f"❌ API Error: {response.status_code}")
        print(response.text)
        
except Exception as e:
    print(f"❌ Connection Error: {e}")
    print("\nMake sure server is running")
