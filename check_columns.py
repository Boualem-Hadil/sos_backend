import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set. Add it to .env")
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()
cur.execute("""
    SELECT column_name FROM information_schema.columns
    WHERE table_name = 'users'
    ORDER BY column_name;
""")
for row in cur.fetchall():
    print(row[0])
cur.close()
conn.close()