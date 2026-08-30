import psycopg2

def main():
    conn = psycopg2.connect("postgresql://postgres@localhost/postgres")
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
