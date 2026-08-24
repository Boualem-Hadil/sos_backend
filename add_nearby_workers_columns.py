"""
add_nearby_workers_columns.py
─────────────────────────────
Run once to add the 5 new columns to the `emergencies` table that the
nearby-workers / ping feature needs.  Safe to run on an existing database —
ALTER TABLE ADD COLUMN is idempotent (duplicate-column exceptions are caught).

Usage (from sos_backend/):
    python add_nearby_workers_columns.py
"""

import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://sos_user:sos_password@localhost:5432/sos_db",
)

COLUMNS = [
    ("last_seen_active", "TIMESTAMP WITH TIME ZONE"),
    ("ping_sent_at",     "TIMESTAMP WITH TIME ZONE"),
    ("ping_acked_at",    "TIMESTAMP WITH TIME ZONE"),
    ("heartbeat_lat",    "DOUBLE PRECISION"),
    ("heartbeat_lng",    "DOUBLE PRECISION"),
]

def main():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()

    for col_name, col_type in COLUMNS:
        try:
            cur.execute(
                f"ALTER TABLE emergencies ADD COLUMN {col_name} {col_type};"
            )
            print(f"[OK] Added column: {col_name} {col_type}")
        except psycopg2.errors.DuplicateColumn:
            print(f"[SKIP] Column already exists: {col_name}")
        except Exception as e:
            print(f"[ERROR] Adding {col_name}: {e}")
            raise

    cur.close()
    conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    main()
