import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def main():
    # Use DATABASE_URL from env — point this at the postgres maintenance db
    # e.g. postgresql://postgres:pass@host/postgres
    db_url = os.getenv("DATABASE_ADMIN_URL", os.getenv("DATABASE_URL", ""))
    if not db_url:
        raise RuntimeError("Set DATABASE_ADMIN_URL (or DATABASE_URL) in .env")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname='sos_algerie'")
    exists = cur.fetchone()
    if not exists:
        cur.execute("CREATE DATABASE sos_algerie")
        print("Database 'sos_algerie' created successfully!")
    else:
        print("Database 'sos_algerie' already exists.")
    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
