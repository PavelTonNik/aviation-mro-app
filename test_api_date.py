import requests
import json

r = requests.get('http://localhost:8000/api/dashboard/aircraft-details')
data = r.json()

# Ищем ER-BAT (последний в списке, index 2)
for ac in data:
    if ac['tail_number'] == 'ER-BAT':
        pos1 = ac['positions'][0]
        if pos1:
            print(f"\nAircraft: {ac['tail_number']}")
            print(f"Position 1: {pos1['current_sn']}")
            print(f"Param Date: {pos1['param_date']}")
        break
