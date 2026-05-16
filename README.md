# SOS Algérie Backend — README

## Quick Start

### 1. Create virtualenv & install dependencies
```bash
cd sos_backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt
```

### 2. Configure environment
Edit `.env` — set your PostgreSQL credentials:
```
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost/sos_algerie
SECRET_KEY=your-strong-random-secret
```

### 3. Create the database
```bash
# In psql or pgAdmin:
CREATE DATABASE sos_algerie;
```

### 4. Run migrations (or let auto-create on startup)
```bash
alembic revision --autogenerate -m "initial"
alembic upgrade head
```

### 5. Seed test data
```bash
python seed.py
```
Credentials after seeding:
| Role         | employee_id | password   | company_code        |
|-------------|-------------|------------|---------------------|
| super_admin  | admin       | admin123   | SYSADMIN-INTERNAL   |
| safety_officer | SON-001  | worker123  | SONATRACH-2024      |
| worker       | SON-002     | worker123  | SONATRACH-2024      |
| company_admin | COS-001   | worker123  | COSIDER-2024        |

### 6. Run the server
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

API docs: http://localhost:8000/docs

### 7. Run tests
```bash
pytest test_api.py -v
```

---

## API Overview

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /auth/register | — | Register worker |
| POST | /auth/login | — | Login |
| GET | /auth/me | ✓ | Current user |
| GET | /users | Officer+ | List company workers |
| GET | /users/{id} | ✓ | User profile |
| PUT | /users/medical-profile | ✓ | Upsert medical profile |
| PUT | /users/last-seen | ✓ | Heartbeat |
| POST | /emergencies | ✓ | Report SOS |
| PUT | /emergencies/{id}/resolve | ✓ | Resolve SOS |
| GET | /emergencies | ✓ | List (paginated + filtered) |
| GET | /emergencies/{id} | ✓ | Emergency detail |
| GET | /companies/{id} | ✓ | Company info + stats |
| GET | /medical/me | ✓ | Own medical profile |
| GET | /medical/{user_id} | Officer+ | Any user medical profile |
| GET | /events/stream | ✓ (query) | SSE live stream |
| POST | /admin/companies | SuperAdmin | Create company |
| GET | /admin/companies | SuperAdmin | List all companies |
| PUT | /admin/companies/{id} | SuperAdmin | Update company |
| GET | /admin/stats | SuperAdmin | Platform stats |

## SSE Connection (Flutter / Next.js)

```
GET /events/stream?company_id=<uuid>&token=<jwt>
Accept: text/event-stream
```

Events emitted:
- `CONNECTED` — on connect
- `EMERGENCY_STARTED` — new SOS with full user + medical data
- `EMERGENCY_RESOLVED` — status update
- `: heartbeat` — every 30s keep-alive comment
