"""
Test script to check API endpoints
"""
import requests
import json

BASE_URL = "http://localhost:8000"

print("=" * 60)
print("Testing Aviation MRO API Endpoints")
print("=" * 60)

# Test 1: Dashboard aircraft details
print("\n1. Testing /api/dashboard/aircraft-details")
try:
    response = requests.get(f"{BASE_URL}/api/dashboard/aircraft-details")
    print(f"   Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"   Aircraft count: {len(data)}")
        if data:
            print(f"   First aircraft: {data[0]['tail_number']}")
            print(f"   Total time: {data[0]['total_time']} hrs")
            print(f"   Positions: {len(data[0]['positions'])}")
        print(json.dumps(data, indent=2))
    else:
        print(f"   Error: {response.text}")
except Exception as e:
    print(f"   ERROR: {e}")

# Test 2: Fleet (old endpoint)
print("\n2. Testing /api/fleet")
try:
    response = requests.get(f"{BASE_URL}/api/fleet")
    print(f"   Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"   Aircraft count: {len(data)}")
        if data:
            print(f"   First aircraft: {data[0]['tail_number']}")
    else:
        print(f"   Error: {response.text}")
except Exception as e:
    print(f"   ERROR: {e}")

# Test 3: Dashboard stats
print("\n3. Testing /api/dashboard/stats")
try:
    response = requests.get(f"{BASE_URL}/api/dashboard/stats")
    print(f"   Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"   Stats: {data}")
    else:
        print(f"   Error: {response.text}")
except Exception as e:
    print(f"   ERROR: {e}")

print("\n" + "=" * 60)
print("Test completed!")
print("=" * 60)
