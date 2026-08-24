import psycopg2
conn = psycopg2.connect("postgresql://postgres:postgres@localhost/sos_algerie")
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