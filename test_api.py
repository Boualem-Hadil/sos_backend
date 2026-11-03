"""
test_api.py — Basic integration tests for EchoAlert API.
Run:  pytest test_api.py -v
(requires the server to be running AND the database to be seeded)

Set TEST_BASE_URL env var to override the default http://127.0.0.1:8000
"""
import os
import pytest
import httpx

BASE = os.getenv("TEST_BASE_URL", "http://127.0.0.1:8000")
client = httpx.Client(base_url=BASE, timeout=30)

# -- shared state ----
_state: dict = {}


# ----
# Health
# ----

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ----
# Registration flow
# ----

def test_register_invalid_company_code():
    r = client.post("/auth/register", json={
        "full_name":   "Test User",
        "employee_id": "T-999",
        "password":    "pass123",
        "phone":       "+213500000001",
        "company_code": "INVALID-CODE",
    })
    assert r.status_code == 404
    body = r.json()
    assert "Company code invalid" in body["detail"]


def test_register_success():
    import uuid
    unique_id = f"TEST-{uuid.uuid4().hex[:6].upper()}"
    r = client.post("/auth/register", json={
        "full_name":    "Nouveau Employé",
        "employee_id":  unique_id,
        "password":     "testpass123",
        "phone":        "+213550999888",
        "company_code": "SONATRACH-2024",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["success"] is True
    assert "access_token" in body["data"]
    _state["worker_token"] = body["data"]["access_token"]
    _state["worker_employee_id"] = unique_id


def test_register_duplicate_employee():
    """Registering the same employee_id twice should return 409."""
    r = client.post("/auth/register", json={
        "full_name":    "Duplicate",
        "employee_id":  _state.get("worker_employee_id", "SON-001"),
        "password":     "testpass123",
        "phone":        "+213550999777",
        "company_code": "SONATRACH-2024",
    })
    assert r.status_code == 409


# ----
# Login flow
# ----

def test_login_wrong_password():
    r = client.post("/auth/login", json={
        "employee_id":  "SON-001",
        "password":     "wrongpassword",
        "company_code": "SONATRACH-2024",
    })
    assert r.status_code == 401


def test_login_success():
    r = client.post("/auth/login", json={
        "employee_id":  "SON-001",
        "password":     "worker123",
        "company_code": "SONATRACH-2024",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert "access_token" in body["data"]
    assert body["data"]["user"]["employee_id"] == "SON-001"
    _state["officer_token"] = body["data"]["access_token"]


def test_login_admin():
    r = client.post("/auth/login", json={
        "employee_id":  "superAdmin",
        "password":     "turbocooling",
        "company_code": "SUPER-ADMIN",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["user"]["role"] == "super_admin"
    _state["admin_token"] = body["data"]["access_token"]


def test_me_endpoint():
    token = _state.get("officer_token")
    assert token, "Run test_login_success first"
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["employee_id"] == "SON-001"
    assert body["data"]["company"] is not None


# ----
# Users management (CRUD and company user limits)
# ----

def test_users_crud_and_limit():
    import uuid
    officer_tok = _state.get("officer_token")
    emp_code = f"SON-W-{uuid.uuid4().hex[:5].upper()}"

    # 1. Creating user
    r = client.post("/users", headers={"Authorization": f"Bearer {officer_tok}"}, json={
        "full_name": "Test Worker LifeCycle",
        "employee_id": emp_code,
        "password": "workerPassword123",
        "phone": "+213550111222",
        "role": "worker"
    })
    assert r.status_code == 201, r.text
    u_id = r.json()["data"]["id"]

    # 2. Updating user
    r = client.put(f"/users/{u_id}", headers={"Authorization": f"Bearer {officer_tok}"}, json={
        "full_name": "Test Worker LifeCycle Updated"
    })
    assert r.status_code == 200
    assert r.json()["data"]["full_name"] == "Test Worker LifeCycle Updated"

    # 3. Deactivating user (requires admin role)
    admin_tok = _state.get("admin_token")
    r = client.delete(f"/users/{u_id}", headers={"Authorization": f"Bearer {admin_tok}"})
    assert r.status_code == 200

    # Reactivate user
    r = client.patch(f"/users/{u_id}/reactivate", headers={"Authorization": f"Bearer {admin_tok}"})
    assert r.status_code == 200

    # 4. Limit check: when current_users >= max_users, registration/creation is rejected
    from app.database import SessionLocal
    from app import models
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.id == u_id).first()
        company = db.query(models.Company).filter(models.Company.id == user.company_id).first()
        old_max = company.max_users
        old_curr = company.current_users
        company.max_users = old_curr  # saturation
        db.commit()

        # Attempt to create should be rejected by limit
        r_limit = client.post("/users", headers={"Authorization": f"Bearer {officer_tok}"}, json={
            "full_name": "Limit Exceeded Worker",
            "employee_id": f"LIMIT-{uuid.uuid4().hex[:4].upper()}",
            "password": "workerPassword123",
            "phone": "+213550111333",
            "role": "worker"
        })
        assert r_limit.status_code == 403
        assert "limit" in r_limit.text.lower()
    finally:
        company.max_users = old_max
        db.commit()
        db.close()


# ----
# Emergency reporting
# ----

def test_report_emergency():
    token = _state.get("worker_token")
    assert token, "Run test_register_success first"
    r = client.post("/emergencies", headers={"Authorization": f"Bearer {token}"}, json={
        "type":                 "Cardiac",
        "severity":             "Critical",
        "latitude":             36.7372,
        "longitude":            3.0867,
        "location_description": "Unité de pompage P-05",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["success"] is True
    assert body["data"]["status"] == "active"
    _state["emergency_id"] = body["data"]["id"]


def test_report_emergency_invalid_type():
    token = _state.get("worker_token")
    r = client.post("/emergencies", headers={"Authorization": f"Bearer {token}"}, json={
        "type":     "Alien Invasion",
        "severity": "Critical",
    })
    assert r.status_code == 422


def test_list_emergencies():
    token = _state.get("officer_token")
    r = client.get("/emergencies", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["data"]["items"], list)
    assert "total" in body["data"]


def test_list_emergencies_filtered():
    token = _state.get("officer_token")
    r = client.get("/emergencies?status=active&page=1&limit=5",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_get_emergency_detail():
    eid = _state.get("emergency_id")
    token = _state.get("worker_token")
    if not eid:
        pytest.skip("No emergency_id in state")
    r = client.get(f"/emergencies/{eid}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["id"] == eid


def test_emergency_gps_heartbeat():
    eid = _state.get("emergency_id")
    token = _state.get("worker_token")
    if not eid:
        pytest.skip("No emergency_id in state")
    r = client.post(
        f"/emergencies/{eid}/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={"latitude": 36.7380, "longitude": 3.0870},
    )
    assert r.status_code == 200
    assert r.json()["data"]["heartbeat_lat"] == 36.7380


def test_emergency_ping_and_ack():
    eid = _state.get("emergency_id")
    officer_tok = _state.get("officer_token")
    worker_tok  = _state.get("worker_token")
    if not eid:
        pytest.skip("No emergency_id in state")
    # Officer pings the emergency
    r = client.post(f"/emergencies/{eid}/ping", headers={"Authorization": f"Bearer {officer_tok}"})
    assert r.status_code == 200
    assert r.json()["data"]["ping_sent_at"] is not None

    # Worker acknowledges the ping
    r = client.post(f"/emergencies/{eid}/ping-ack", headers={"Authorization": f"Bearer {worker_tok}"})
    assert r.status_code == 200
    assert r.json()["data"]["ping_acked_at"] is not None


def test_emergency_messages():
    eid = _state.get("emergency_id")
    worker_tok  = _state.get("worker_token")
    officer_tok = _state.get("officer_token")
    if not eid:
        pytest.skip("No emergency_id in state")
    # Worker posts a message
    r = client.post(
        f"/emergencies/{eid}/messages/text",
        headers={"Authorization": f"Bearer {worker_tok}"},
        json={"content": "Need immediate medical team at sector 4."},
    )
    assert r.status_code == 200
    assert r.json()["data"]["content"] == "Need immediate medical team at sector 4."

    # Officer reads messages
    r = client.get(
        f"/emergencies/{eid}/messages",
        headers={"Authorization": f"Bearer {officer_tok}"},
    )
    assert r.status_code == 200
    msgs = r.json()["data"]
    assert any("Need immediate medical team" in m["content"] for m in msgs)


def test_resolve_emergency():
    eid = _state.get("emergency_id")
    token = _state.get("officer_token")
    if not eid:
        pytest.skip("No emergency_id in state")
    r = client.put(
        f"/emergencies/{eid}/resolve",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "resolved", "notes": "Patient stabilisé."},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["status"] == "resolved"


# ----
# Medical profile
# ----

def test_upsert_medical_profile():
    token = _state.get("worker_token")
    r = client.put("/users/medical-profile", headers={"Authorization": f"Bearer {token}"}, json={
        "blood_type":           "A+",
        "is_universal_donor":   False,
        "chronic_diseases":     ["Diabète de type 2"],
        "allergies":            ["Pénicilline"],
        "emergency_notes":      "Prendre insuline toutes les 8h.",
        "ice_contact_name":     "Karima Benali",
        "ice_contact_relation": "Épouse",
        "ice_contact_phone":    "+213550777888",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["blood_type"] == "A+"


def test_last_seen_update():
    token = _state.get("worker_token")
    r = client.put("/users/last-seen", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert "last_seen" in r.json()["data"]


# ----
# Admin routes
# ----

def test_admin_stats():
    token = _state.get("admin_token")
    assert token, "Run test_login_admin first"
    r = client.get("/admin/stats", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    data = body["data"]
    assert "total_companies" in data
    assert "total_users" in data


def test_admin_list_companies():
    token = _state.get("admin_token")
    r = client.get("/admin/companies", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["data"], list)
    assert len(body["data"]) >= 2


def test_admin_create_company():
    from app.database import SessionLocal
    from app import models
    db = SessionLocal()
    try:
        existing = db.query(models.Company).filter(models.Company.company_code == "TEST-MINING-001").first()
        if existing:
            db.query(models.User).filter(models.User.company_id == existing.id).delete()
            db.delete(existing)
            db.commit()
    finally:
        db.close()

    token = _state.get("admin_token")
    r = client.post("/admin/companies", headers={"Authorization": f"Bearer {token}"}, json={
        "name":             "Test Mining Corp",
        "industry":         "mining",
        "company_code":     "TEST-MINING-001",
        "max_users":        25,
        "subscription_end": "2027-12-31",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["data"]["company_code"] == "TEST-MINING-001"
    _state["new_company_id"] = body["data"]["id"]


def test_admin_create_company_duplicate_code():
    token = _state.get("admin_token")
    r = client.post("/admin/companies", headers={"Authorization": f"Bearer {token}"}, json={
        "name":         "Duplicate",
        "industry":     "mining",
        "company_code": "TEST-MINING-001",
        "max_users":    10,
    })
    assert r.status_code == 409


def test_admin_update_company():
    cid   = _state.get("new_company_id")
    token = _state.get("admin_token")
    if not cid:
        pytest.skip("No new_company_id in state")
    r = client.put(f"/admin/companies/{cid}",
                   headers={"Authorization": f"Bearer {token}"},
                   json={"max_users": 50, "is_active": True})
    assert r.status_code == 200
    assert r.json()["data"]["max_users"] == 50


# ----
# Access control guards
# ----

def test_worker_cannot_access_admin():
    token = _state.get("worker_token")
    r = client.get("/admin/stats", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_unauthenticated_request():
    r = client.get("/users")
    assert r.status_code in (401, 403)   # HTTPBearer returns 401/403 when no credentials


# ----
# SSE endpoint (basic connectivity — not full stream test)
# ----

def test_sse_invalid_token():
    r = client.get("/events/stream?company_id=00000000-0000-0000-0000-000000000000&token=badtoken",
                   headers={"Accept": "text/event-stream"}, timeout=3)
    assert r.status_code == 401
