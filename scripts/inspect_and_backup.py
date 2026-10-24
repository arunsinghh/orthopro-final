import datetime
import json
import os
import subprocess
import psycopg2

BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

def backup_db(dbname):
    conn = psycopg2.connect(dbname=dbname, user="orthopro_app", password="orthopro_app", host="127.0.0.1", port=5432)
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        ORDER BY table_name;
    """)
    tables = [row[0] for row in cur.fetchall()]
    print(f"=== Database '{dbname}' Tables ({len(tables)}) ===")
    counts = {}
    dump_data = {}
    for t in tables:
        cur.execute(f'SELECT COUNT(*) FROM "{t}";')
        cnt = cur.fetchone()[0]
        counts[t] = cnt
        print(f"  {t}: {cnt} rows")
        
        # Dump schema and rows to JSON for safe, readable, verified backup
        cur.execute(f"""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = '{t}'
            ORDER BY ordinal_position;
        """)
        cols = cur.fetchall()
        cur.execute(f'SELECT * FROM "{t}";')
        col_names = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        # Convert non-serializable to string
        serialized_rows = []
        for r in rows:
            serialized_rows.append([str(v) if v is not None and not isinstance(v, (int, float, bool, str)) else v for v in r])
        dump_data[t] = {
            "columns": [{"name": c[0], "type": c[1], "nullable": c[2]} for c in cols],
            "row_count": cnt,
            "col_names": col_names,
            "rows": serialized_rows
        }
    
    backup_file = os.path.join(BACKUP_DIR, f"{dbname}_{timestamp}_backup.json")
    with open(backup_file, "w", encoding="utf-8") as f:
        json.dump({"dbname": dbname, "timestamp": timestamp, "tables": dump_data}, f, indent=2)
    
    print(f"Successfully saved JSON backup to {backup_file} (Size: {os.path.getsize(backup_file)} bytes)")
    
    # Verify backup is readable
    with open(backup_file, "r", encoding="utf-8") as f:
        verified = json.load(f)
    print(f"Verified backup: {len(verified['tables'])} tables verified in backup file.")
    conn.close()

if __name__ == "__main__":
    backup_db("orthopro")
    backup_db("orthopro_test")

