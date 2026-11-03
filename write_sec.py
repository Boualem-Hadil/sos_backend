import pathlib

code = r'''import os, pytest, httpx
from datetime import datetime, timedelta, timezone
from jose import jwt

BASE = os.getenv("TEST_BASE_URL", "http://127.0.0.1:8000")
client = httpx.Client(base_url=BASE, timeout=30)
_state = {}


@pytest.fixture(scope="module", autouse=True)
def acquire_tokens():
    logins = [
        ("SON-002",    "worker123",    "SONATRACH-2024", "worker_token"),
        ("SON-001",    "worker123",    "SONATRACH-2024", "officer_token"),
        ("COS-001",    "worker123",    "COSIDER-2024",   "company_admin_token"),
        ("superAdmin", "turbocooling", "SUPER-ADMIN",    "super_admin_token"),
    ]
    for emp, pwd, code, key in logins:
        r = client.post("/auth/login", json={"employee_id": emp, "password": pwd, "company_code": code})
        assert r.status_code == 200, f"{key} login failed: {r.text}"
        _state[key] = r.json()["data"]["access_token"]

    r = client.post("/emergencies",
        headers={"Authorization": "Bearer " + _state["worker_token"]},
        json={"type": "Trauma", "severity": "Moderate", "latitude": 36.7, "longitude": 3.08})
    if r.status_code == 201:
        _state["son_emergency_id"] = r.json()["data"]["id"]
    yield


def test_no_token_protected_route():
    r = client.get("/users")
    assert r.status_code in (401, 403)


def test_invalid_token_rejected():
    r = client.get("/auth/me", headers={"Authorization": "Bearer bad.token.here"})
    assert r.status_code == 401


def test_expired_token_rejected():
    secret = os.getenv("SECRET_KEY", "sos-algerie-super-secret-key-change-in-production-2024")
    alg    = os.getenv("ALGORITHM", "HS256")
    tok = jwt.encode({"sub": "00000000-0000-0000-0000-000000000001",
                      "company_id": "00000000-0000-0000-0000-000000000002",
                      "role": "worker",
                      "exp": datetime.now(timezone.utc) - timedelta(days=1)}, secret, algorithm=alg)
    r = client.get("/auth/me", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 401


def test_worker_cannot_call_officer_route():
    r = client.get("/users", headers={"Authorization": "Bearer " + _state["worker_token"]})
    assert r.status_code == 403


def test_worker_cannot_access_admin_stats():
    r = client.get("/admin/stats", headers={"Authorization": "Bearer " + _state["worker_token"]})
    assert r.status_code == 403


def test_cross_company_emergency_not_accessible():
    eid = _state.get("son_emergency_id")
    if not eid:
        pytest.skip("No cross-company emergency id")
    r = client.get("/emergencies/" + eid, headers={"Authorization": "Bearer " + _state["company_admin_token"]})
    assert r.status_code in (403, 404)


def test_cross_company_user_list_isolation():
    r = client.get("/users", headers={"Authorization": "Bearer " + _state["company_admin_token"]})
    assert r.status_code == 200
    for u in r.json()["data"]:
        assert not u["employee_id"].startswith("SON-"), "Cross-company data leak: " + u["employee_id"]


def test_company_admin_blocked_from_super_admin_stats():
    r = client.get("/admin/stats", headers={"Authorization": "Bearer " + _state["company_admin_token"]})
    assert r.status_code == 403


def test_company_admin_blocked_from_list_companies():
    r = client.get("/admin/companies", headers={"Authorization": "Bearer " + _state["company_admin_token"]})
    assert r.status_code == 403


def test_deactivated_user_login_refused():
    admin_tok   = _state["super_admin_token"]
    officer_tok = _state["officer_token"]

    r = client.get("/users", headers={"Authorization": "Bearer " + officer_tok})
    assert r.status_code == 200
    target = next((u for u in r.json()["data"] if u["employee_id"] == "SON-005"), None)
    if not target:
        pytest.skip("SON-005 not found")

    uid = target["id"]
    r = client.delete("/users/" + uid, headers={"Authorization": "Bearer " + admin_tok})
    assert r.status_code == 200, "Deactivation failed: " + r.text

    r = client.post("/auth/login", json={"employee_id": "SON-005", "password": "worker123",
                                          "company_code": "SONATRACH-2024"})
    assert r.status_code in (401, 403)

    client.patch("/users/" + uid + "/reactivate", headers={"Authorization": "Bearer " + admin_tok})


def test_rate_limit_triggers_429():
    got_429 = False
    for _ in range(15):
        r = client.get("/auth/company/SONATRACH-2024/departments")
        if r.status_code == 429:
            got_429 = True
            break
    assert got_429, "Expected 429 after 15 rapid requests"


def test_password_stored_as_bcrypt_hash():
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app.database import SessionLocal
    from app import models as m
    db = SessionLocal()
    try:
        users = db.query(m.User).all()
        assert len(users) > 0
        for u in users:
            assert u.password_hash.startswith("$"), u.employee_id + " has bad hash"
    finally:
        db.close()


def test_worker_must_change_password_flag():
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app.database import SessionLocal
    from app import models as m
    db = SessionLocal()
    try:
        user = db.query(m.User).filter(m.User.employee_id == "SON-003").first()
        if not user:
            pytest.skip("SON-003 not found")
        user.must_change_password = True
        db.commit()

        r = client.post("/auth/login", json={"employee_id": "SON-003", "password": "worker123",
                                              "company_code": "SONATRACH-2024"})
        assert r.status_code == 200
        assert r.json()["data"]["user"].get("must_change_password") is True
    finally:
        user = db.query(m.User).filter(m.User.employee_id == "SON-003").first()
        if user:
            user.must_change_password = False
            db.commit()
        db.close()
'''

import pathlib
pathlib.Path('test_security.py').write_text(code, encoding='utf-8')
print(f'Written {len(code.splitlines())} lines')
