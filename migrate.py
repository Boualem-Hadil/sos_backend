"""
migrate.py — Apply schema changes that create_all misses for existing databases.

Run with:  python migrate.py
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))

from app.database import engine, Base
from app import models
from sqlalchemy import text, inspect

def migrate():
    insp = inspect(engine)

    with engine.begin() as conn:
        # 1. Add contact_email to companies if missing
        existing_cols = [c["name"] for c in insp.get_columns("companies")]
        if "contact_email" not in existing_cols:
            conn.execute(text("ALTER TABLE companies ADD COLUMN contact_email VARCHAR(255)"))
            print("[+] Added companies.contact_email")
        else:
            print("[=] companies.contact_email already exists")

        # 2. Create notification_recipients table if missing
        existing_tables = insp.get_table_names()
        if "notification_recipients" not in existing_tables:
            conn.execute(text("""
                CREATE TABLE notification_recipients (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    email VARCHAR(255) NOT NULL UNIQUE,
                    name VARCHAR(255) NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
                )
            """))
            print("[+] Created notification_recipients table")
        else:
            print("[=] notification_recipients table already exists")

        # 3. Migrate old SYSADMIN-INTERNAL company code to SUPER-ADMIN if needed
        result = conn.execute(text("SELECT id FROM companies WHERE company_code = 'SYSADMIN-INTERNAL'")).fetchone()
        if result:
            conn.execute(text("UPDATE companies SET company_code = 'SUPER-ADMIN', name = 'SOS Algerie Platform' WHERE company_code = 'SYSADMIN-INTERNAL'"))
            print("[+] Migrated company_code SYSADMIN-INTERNAL -> SUPER-ADMIN")
        else:
            print("[=] No SYSADMIN-INTERNAL company to migrate")

        # 4. Migrate old admin employee_id to superAdmin if needed
        result = conn.execute(text("SELECT id FROM users WHERE employee_id = 'admin'")).fetchone()
        if result:
            from app.auth import hash_password
            new_hash = hash_password("turbocooling")
            conn.execute(text(
                "UPDATE users SET employee_id = 'superAdmin', password_hash = :h, full_name = 'Super Administrateur' WHERE employee_id = 'admin'"
            ), {"h": new_hash})
            print("[+] Migrated super admin: admin -> superAdmin (password: turbocooling)")
        else:
            print("[=] No old 'admin' user to migrate")

    print("\n[OK] Migration complete.")

if __name__ == "__main__":
    migrate()
