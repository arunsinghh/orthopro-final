import json
import psycopg2

with open('backups/orthopro_20261023_220816_backup.json') as f:
    backup = json.load(f)

conn = psycopg2.connect(dbname='orthopro', user='orthopro_app', password='orthopro_app', host='127.0.0.1', port=5432)
cur = conn.cursor()

print('=== Comparison of orthopro tables before vs after ===')
all_ok = True
for t, tdata in backup['tables'].items():
    cur.execute(f'SELECT COUNT(*) FROM "{t}";')
    current_cnt = cur.fetchone()[0]
    orig_cnt = tdata['row_count']
    status = 'MATCH' if current_cnt == orig_cnt else ('INCREASED' if current_cnt > orig_cnt else 'DECREASED (WARNING)')
    print(f'  {t:25s}: before={orig_cnt:3d}, after={current_cnt:3d} [{status}]')
    if current_cnt < orig_cnt:
        all_ok = False

# Verify patient #1 still intact
cur.execute('SELECT id, name, serial_no, phone FROM patients WHERE id=1;')
p1 = cur.fetchone()
print(f'Patient 1 verification: {p1}')
assert p1 is not None and p1[0] == 1

# Verify all 13 original lead IDs exist
cur.execute('SELECT id, status, patient_id FROM leads ORDER BY id;')
leads = cur.fetchall()
print(f'Total leads in orthopro: {len(leads)}')
orig_lead_ids = set(r[0] for r in backup['tables']['leads']['rows'])
current_lead_ids = set(r[0] for r in leads)
assert orig_lead_ids.issubset(current_lead_ids), 'Some original lead IDs are missing!'
print('All original 13 lead IDs confirmed intact and present.')

conn.close()
print('Verification status:', 'PASSED' if all_ok else 'FAILED')

