"""
seed.py — Populate the database with realistic test data for SOS Algérie.

Run with:  python seed.py
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(__file__))

from app.database import SessionLocal, engine
from app import models
from app.auth import hash_password

# ── helpers ───────────────────────────────────────────────────────────────────

def now():
    return datetime.now(timezone.utc)


def days_ago(n: int):
    return now() - timedelta(days=n)


# ── seed data ─────────────────────────────────────────────────────────────────

COMPANIES = [
    {
        "name":               "Sonatrach Division Exploitation",
        "industry":           "oil",
        "company_code":       "SONATRACH-2024",
        "max_users":          100,
        "subscription_start": date(2024, 1, 1),
        "subscription_end":   date(2026, 12, 31),
    },
    {
        "name":               "COSIDER Construction Est",
        "industry":           "construction",
        "company_code":       "COSIDER-2024",
        "max_users":          50,
        "subscription_start": date(2024, 3, 1),
        "subscription_end":   date(2025, 12, 31),
    },
]

WORKERS = {
    "SONATRACH-2024": [
        {"full_name": "Karim Boualem",      "employee_id": "SON-001", "phone": "+213550123401", "role": models.UserRole.safety_officer},
        {"full_name": "Amira Benali",       "employee_id": "SON-002", "phone": "+213550123402", "role": models.UserRole.worker},
        {"full_name": "Youcef Meddah",      "employee_id": "SON-003", "phone": "+213550123403", "role": models.UserRole.worker},
        {"full_name": "Fatima Ziani",       "employee_id": "SON-004", "phone": "+213550123404", "role": models.UserRole.worker},
        {"full_name": "Hicham Kermiche",    "employee_id": "SON-005", "phone": "+213550123405", "role": models.UserRole.worker},
    ],
    "COSIDER-2024": [
        {"full_name": "Sofiane Guerroudj",  "employee_id": "COS-001", "phone": "+213770234501", "role": models.UserRole.company_admin},
        {"full_name": "Nadia Ouali",        "employee_id": "COS-002", "phone": "+213770234502", "role": models.UserRole.worker},
        {"full_name": "Mourad Slimane",     "employee_id": "COS-003", "phone": "+213770234503", "role": models.UserRole.worker},
        {"full_name": "Leila Hadjadj",      "employee_id": "COS-004", "phone": "+213770234504", "role": models.UserRole.worker},
        {"full_name": "Rachid Bensalem",    "employee_id": "COS-005", "phone": "+213770234505", "role": models.UserRole.worker},
    ],
}

MEDICAL_DATA = [
    {"blood_type": "A+",  "is_universal_donor": False, "chronic_diseases": [],            "allergies": ["Pénicilline"],        "ice_contact_name": "Saliha Boualem",    "ice_contact_relation": "Épouse",   "ice_contact_phone": "+213550100001"},
    {"blood_type": "O-",  "is_universal_donor": True,  "chronic_diseases": ["Diabète"],   "allergies": [],                     "ice_contact_name": "Omar Benali",       "ice_contact_relation": "Père",     "ice_contact_phone": "+213550100002"},
    {"blood_type": "B+",  "is_universal_donor": False, "chronic_diseases": [],            "allergies": ["Aspirine"],           "ice_contact_name": "Houria Meddah",     "ice_contact_relation": "Mère",     "ice_contact_phone": "+213550100003"},
    {"blood_type": "AB+", "is_universal_donor": False, "chronic_diseases": ["Asthme"],    "allergies": ["Ibuprofène"],         "ice_contact_name": "Tarek Ziani",       "ice_contact_relation": "Frère",    "ice_contact_phone": "+213550100004"},
    {"blood_type": "O+",  "is_universal_donor": False, "chronic_diseases": [],            "allergies": [],                     "ice_contact_name": "Zineb Kermiche",    "ice_contact_relation": "Sœur",     "ice_contact_phone": "+213550100005"},
    {"blood_type": "A-",  "is_universal_donor": False, "chronic_diseases": ["HTA"],       "allergies": ["Latex"],              "ice_contact_name": "Djamila Guerroudj", "ice_contact_relation": "Épouse",   "ice_contact_phone": "+213770100001"},
    {"blood_type": "O+",  "is_universal_donor": False, "chronic_diseases": [],            "allergies": [],                     "ice_contact_name": "Azzedine Ouali",    "ice_contact_relation": "Mari",     "ice_contact_phone": "+213770100002"},
    {"blood_type": "B-",  "is_universal_donor": False, "chronic_diseases": ["Épilepsie"], "allergies": ["Sulfamides"],         "ice_contact_name": "Rania Slimane",     "ice_contact_relation": "Épouse",   "ice_contact_phone": "+213770100003"},
    {"blood_type": "A+",  "is_universal_donor": False, "chronic_diseases": [],            "allergies": ["Arachides"],          "ice_contact_name": "Salim Hadjadj",     "ice_contact_relation": "Père",     "ice_contact_phone": "+213770100004"},
    {"blood_type": "O+",  "is_universal_donor": False, "chronic_diseases": [],            "allergies": [],                     "ice_contact_name": "Fatma Bensalem",    "ice_contact_relation": "Mère",     "ice_contact_phone": "+213770100005"},
]

SAMPLE_EMERGENCIES = [
    {"type": "Cardiac",     "severity": "Critical", "location_description": "Puits P-12, Secteur Nord", "status": models.EmergencyStatus.resolved,    "days_ago": 10},
    {"type": "Trauma",      "severity": "Moderate", "location_description": "Atelier mécanique B3",     "status": models.EmergencyStatus.resolved,    "days_ago": 7},
    {"type": "Fire",        "severity": "Critical", "location_description": "Salle compresseurs Est",   "status": models.EmergencyStatus.resolved,    "days_ago": 5},
    {"type": "Respiratory", "severity": "Low",      "location_description": "Cantine du site",           "status": models.EmergencyStatus.false_alarm, "days_ago": 3},
    {"type": "Medical",     "severity": "Moderate", "location_description": "Chantier principal A",      "status": models.EmergencyStatus.active,      "days_ago": 0},
]


# ── main ──────────────────────────────────────────────────────────────────────

def seed():
    print("🌱 Creating all tables …")
    models.Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # ── Super admin ───────────────────────────────────────────────────────
        # We need a dummy company for the super admin
        dummy_company = db.query(models.Company).filter_by(company_code="SYSADMIN-INTERNAL").first()
        if not dummy_company:
            dummy_company = models.Company(
                name               = "SOS Algérie Platform",
                industry           = "platform",
                company_code       = "SYSADMIN-INTERNAL",
                max_users          = 999,
                subscription_start = date(2024, 1, 1),
                subscription_end   = date(2099, 12, 31),
                is_active          = True,
            )
            db.add(dummy_company)
            db.flush()

        existing_admin = db.query(models.User).filter_by(employee_id="admin").first()
        if not existing_admin:
            admin = models.User(
                company_id    = dummy_company.id,
                full_name     = "Super Administrateur",
                employee_id   = "admin",
                phone         = "+213550000000",
                password_hash = hash_password("admin123"),
                role          = models.UserRole.super_admin,
            )
            db.add(admin)
            db.flush()
            db.add(models.MedicalProfile(user_id=admin.id, chronic_diseases=[], allergies=[]))
            dummy_company.current_users += 1
            print("  ✅ super_admin created  (employee_id=admin  password=admin123)")
        else:
            print("  ⏭  super_admin already exists")

        # ── Companies + workers ───────────────────────────────────────────────
        company_objects = {}
        medical_idx = 0

        for c_data in COMPANIES:
            company = db.query(models.Company).filter_by(company_code=c_data["company_code"]).first()
            if not company:
                company = models.Company(**c_data, is_active=True)
                db.add(company)
                db.flush()
                print(f"  ✅ Company: {c_data['name']}  ({c_data['company_code']})")
            else:
                print(f"  ⏭  Company already exists: {c_data['company_code']}")

            company_objects[c_data["company_code"]] = company

            for w_data in WORKERS[c_data["company_code"]]:
                existing_w = db.query(models.User).filter_by(
                    employee_id=w_data["employee_id"],
                    company_id=company.id,
                ).first()
                if not existing_w:
                    worker = models.User(
                        company_id    = company.id,
                        full_name     = w_data["full_name"],
                        employee_id   = w_data["employee_id"],
                        phone         = w_data["phone"],
                        password_hash = hash_password("worker123"),
                        role          = w_data["role"],
                        last_seen     = days_ago(1),
                    )
                    db.add(worker)
                    db.flush()

                    med = MEDICAL_DATA[medical_idx % len(MEDICAL_DATA)]
                    db.add(models.MedicalProfile(
                        user_id              = worker.id,
                        blood_type           = med["blood_type"],
                        is_universal_donor   = med["is_universal_donor"],
                        chronic_diseases     = med["chronic_diseases"],
                        allergies            = med["allergies"],
                        ice_contact_name     = med["ice_contact_name"],
                        ice_contact_relation = med["ice_contact_relation"],
                        ice_contact_phone    = med["ice_contact_phone"],
                        emergency_notes      = "Pas de notes supplémentaires.",
                    ))
                    company.current_users += 1
                    print(f"    👤 {w_data['full_name']}  [{w_data['employee_id']}]  role={w_data['role'].value}")
                else:
                    print(f"    ⏭  Worker already exists: {w_data['employee_id']}")

                medical_idx += 1

        # ── Sample emergencies (Sonatrach) ────────────────────────────────────
        sonatrach = company_objects.get("SONATRACH-2024")
        if sonatrach:
            first_worker = db.query(models.User).filter_by(
                company_id=sonatrach.id,
                employee_id="SON-002",
            ).first()

            for em_data in SAMPLE_EMERGENCIES:
                started = days_ago(em_data["days_ago"])
                resolved = None if em_data["status"] == models.EmergencyStatus.active \
                           else started + timedelta(hours=2)

                emergency = models.Emergency(
                    user_id              = first_worker.id if first_worker else None,
                    company_id           = sonatrach.id,
                    type                 = em_data["type"],
                    severity             = em_data["severity"],
                    location_description = em_data["location_description"],
                    latitude             = 36.7372 + (em_data["days_ago"] * 0.001),
                    longitude            = 3.0867  + (em_data["days_ago"] * 0.001),
                    status               = em_data["status"],
                    started_at           = started,
                    resolved_at          = resolved,
                    notes                = "Situation maîtrisée." if resolved else None,
                )
                db.add(emergency)

            print(f"  ✅ {len(SAMPLE_EMERGENCIES)} sample emergencies added for Sonatrach")

        db.commit()
        print("\n✅ Seeding complete!")
        print("─" * 50)
        print("  Login credentials:")
        print("  super_admin → employee_id: admin     | password: admin123 | company_code: SYSADMIN-INTERNAL")
        print("  workers     → employee_id: SON-001…  | password: worker123 | company_code: SONATRACH-2024")
        print("  workers     → employee_id: COS-001…  | password: worker123 | company_code: COSIDER-2024")

    except Exception as exc:
        db.rollback()
        print(f"\n❌ Seed failed: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
