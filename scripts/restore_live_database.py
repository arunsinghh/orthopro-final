import os
import sys
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db as dblib
from app.config import get_config
from sqlalchemy import text

def restore():
    cfg = get_config()
    class _App:
        config = {"DATABASE_URL": cfg.DATABASE_URL, "DB_POOL_SIZE": 2, "DB_MAX_OVERFLOW": 2}
        extensions = {}
    dblib.init_app(_App())

    print("Step 1: Dropping old local tables...")
    tables = [r["table_name"] for r in dblib.q(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'"
    )]
    with dblib.transaction() as conn:
        for t in tables:
            conn.execute(text(f'DROP TABLE IF EXISTS "{t}" CASCADE;'))
    print(f"  [ok] Dropped {len(tables)} tables.")

    print("Step 2: Importing live database dump from backups/orthopro_live.sql...")
    sql_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backups", "orthopro_live.sql")
    env = os.environ.copy()
    env["PGPASSWORD"] = "orthopro_app"
    psql_bin = r"C:\Program Files\PostgreSQL\18\bin\psql.exe"
    if not os.path.exists(psql_bin):
        psql_bin = r"C:\Program Files\PostgreSQL\14\bin\psql.exe"

    cmd = [psql_bin, "-U", "orthopro_app", "-h", "127.0.0.1", "-p", "5432", "-d", "orthopro", "-q", "-f", sql_path]
    subprocess.run(cmd, env=env, check=True)
    print("  [ok] Live database imported successfully.")

    print("Step 3: Applying migration 009 (editable leads & whatsapp timeline)...")
    mig_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations", "009_leads_editable_chat.sql")
    if os.path.exists(mig_path):
        with open(mig_path, "r", encoding="utf-8") as f:
            dblib.apply_schema(f.read())
        print("  [ok] Migration 009 applied cleanly.")

    print("\n=== Live Database Synchronized Locally ===")
    for tbl in ["patients", "leads", "lead_history", "followups", "users", "appointments", "services", "products"]:
        cnt = dblib.q(f"SELECT COUNT(*) c FROM {tbl}", one=True)["c"]
        print(f"  {tbl}: {cnt} rows")

if __name__ == "__main__":
    restore()

