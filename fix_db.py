import psycopg2

conn = psycopg2.connect('postgresql://postgres:postgres@localhost/sos_algerie')
conn.autocommit = True
cur = conn.cursor()

try:
    cur.execute("ALTER TYPE emergencystatus ADD VALUE 'cancelled_by_worker'")
    print('Added cancelled_by_worker')
except Exception as e:
    print('cancelled_by_worker already exists or error:', e)

try:
    cur.execute("CREATE TYPE respondertype AS ENUM ('police', 'samu', 'fire', 'other')")
    print('Created respondertype')
except Exception as e:
    print('respondertype already exists or error:', e)

try:
    cur.execute("ALTER TABLE emergencies ADD COLUMN responder_type respondertype")
    print('Added responder_type column')
except Exception as e:
    print('responder_type column exists or error:', e)

try:
    cur.execute("ALTER TABLE emergencies ADD COLUMN eta_minutes integer")
    print('Added eta_minutes column')
except Exception as e:
    print('eta_minutes column exists or error:', e)

try:
    cur.execute("UPDATE alembic_version SET version_num='c7782175642d'")
    print('Stamped alembic version')
except Exception as e:
    print('Alembic stamp error:', e)
