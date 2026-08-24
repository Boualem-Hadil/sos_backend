import requests
import time

BASE_URL = "http://192.168.1.64:8000"  # match your api_service.dart baseUrl

# Fill in with real test worker accounts already registered in your system
FAKE_WORKERS = [
    {"employee_id": "TEST-0001", "password": "test123", "company_code": "SONATRACH-2024", "lat": 36.1901, "lng": 5.4132},
    {"employee_id": "TEST-0002", "password": "test123", "company_code": "SONATRACH-2024", "lat": 36.1915, "lng": 5.4148},
    {"employee_id": "TEST-0003", "password": "test123", "company_code": "SONATRACH-2024", "lat": 36.1888, "lng": 5.4110},
]

def login(worker):
    r = requests.post(f"{BASE_URL}/auth/login", json={
        "employee_id": worker["employee_id"],
        "password": worker["password"],
        "company_code": worker["company_code"],
    })
    r.raise_for_status()
    return r.json()["data"]["access_token"]

def send_heartbeat(token, lat, lng):
    r = requests.put(
        f"{BASE_URL}/workers/heartbeat",  # ADJUST to your real endpoint path
        json={"latitude": lat, "longitude": lng},
        headers={"Authorization": f"Bearer {token}"},
    )
    print(f"  -> {r.status_code}: {r.text[:100]}")

for worker in FAKE_WORKERS:
    print(f"Seeding {worker['employee_id']}...")
    token = login(worker)
    send_heartbeat(token, worker["lat"], worker["lng"])

print("Done. Re-run this script periodically if the backend expects fresh heartbeats.")