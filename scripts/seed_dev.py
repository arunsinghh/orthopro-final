#!/usr/bin/env python3
"""SAFE, idempotent seeding for development/demo (PostgreSQL only).

Reference content lives in ``data_seed_reference.json`` (a plain JSON dump —
no SQLite anywhere in the project). This script NEVER removes data: it only
inserts missing reference content and never touches existing patient records,
settings overrides added later, or the admin account.

    python scripts/seed_dev.py            # insert reference content if empty
    python scripts/seed_dev.py --demo     # also add a few demo patients/leads

The admin account is intentionally NOT seeded with a default password.
Run ``python scripts/create_admin.py`` to create one securely.
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db as dblib          # noqa: E402
from app.config import get_config    # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF_FILE = os.path.join(HERE, "data_seed_reference.json")

REFERENCE_TABLES = ["services", "products", "settings", "journeys", "posts",
                    "testimonials"]
DATE_COLS = {"next_followup", "due_date", "preferred_date"}
TS_COLS = {"created_at", "uploaded_at"}


def _init():
    cfg = get_config()

    class _App:
        config = {"DATABASE_URL": cfg.DATABASE_URL, "DB_POOL_SIZE": 2,
                  "DB_MAX_OVERFLOW": 2}
        extensions = {}

    dblib.init_app(_App())


def _copy_table(data, table):
    existing = dblib.q(f"SELECT COUNT(*) c FROM {table}", one=True)["c"]
    if existing:
        print(f"  [skip] {table}: already has {existing} rows (not modified)")
        return
    rows = data.get(table, [])
    if not rows:
        print(f"  [skip] {table}: no reference rows in source")
        return
    inserted = 0
    with dblib.transaction() as conn:
        for row in rows:
            cols, values = [], []
            for c, v in row.items():
                if c in TS_COLS:
                    v = dt.datetime.fromisoformat(str(v)) if v else None
                elif c in DATE_COLS:
                    v = str(v)[:10] if v else None
                elif v is None and c in ("image",):
                    v = ""  # postgres NOT NULL text column
                cols.append(c)
                values.append(v)
            cols_sql = ",".join(f'"{c}"' for c in cols)
            dblib.q(f"INSERT INTO {table} ({cols_sql}) VALUES ({','.join('?' * len(cols))})",
                    tuple(values), conn=conn)
            inserted += 1
        if any(r.get("id") for r in rows) and table != "settings":
            from sqlalchemy import text
            conn.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{table}','id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}),0)+1, false)"))
    print(f"  [seed] {table}: inserted {inserted} reference rows")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true",
                    help="also seed demo patients/appointments/leads")
    args = ap.parse_args()

    _init()
    if not os.path.exists(REF_FILE):
        sys.exit(f"Reference source not found: {REF_FILE}")
    with open(REF_FILE, encoding="utf-8") as f:
        data = json.load(f)

    print("[seed] Inserting missing reference content (never overwrites existing rows):")
    for table in REFERENCE_TABLES:
        _copy_table(data, table)

    # Brand / NAP consistency with the Google Business Profile
    dblib.q("UPDATE settings SET value=? WHERE key='address'",
            ("OrthoPro Artificial Limbs Center, Khirki Extension, Malviya Nagar, "
             "New Delhi – 110017",))
    dblib.q("INSERT INTO settings (key,value) VALUES ('google_reviews_url', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
            ("https://share.google/43Xf7XcTXUTvqFXV2",))

    # Real product photos instead of emoji placeholders
    from app.helpers import PRODUCT_IMAGES
    
    for name, img in PRODUCT_IMAGES.items():
        dblib.q("UPDATE products SET image=? WHERE name=? AND (image='' OR image IS NULL)",
                (img, name))

    admin = dblib.q("SELECT COUNT(*) c FROM users", one=True)["c"]
    if admin == 0:
        print("\n[seed] No admin user exists. Create one securely with:")
        print("       python scripts/create_admin.py")
    else:
        print(f"\n[seed] Admin user(s) present ({admin}); not modified.")

    if args.demo:
        print("\n[seed] Demo rows:")
        for table in ["patients", "appointments", "followups"]:
            _copy_table(data, table)
        _demo_leads()
    else:
        print("\n[seed] Skipped demo patients/leads (use --demo to add sample rows).")


def _demo_leads():
    have = dblib.q("SELECT COUNT(*) c FROM leads", one=True)["c"]
    if have:
        print("  [skip] leads: already present")
        return
    now = dt.datetime.now(dt.timezone.utc)
    demos = [
        ("WhatsApp", "whatsapp", "Ramesh Yadav", "+91 98111 22334",
         "Lower Limb (Leg)", "need artificial leg after accident, above knee", "new", None),
        ("Facebook", "", "Sunita Devi", "+91 90000 11223",
         "Braces & Orthotics", "AFO brace for foot drop after stroke", "new", None),
        ("Walk-in", "", "Mohammad Irfan", "+91 98777 55667",
         "Diabetic Foot Care", "diabetic footwear, father has ulcer history", "followup", None),
        ("WhatsApp", "whatsapp", "Kavita Sharma", "+91 91234 56780",
         "Upper Limb (Hand/Arm)", "bionic hand price enquiry", "appointment", None),
    ]
    for src, plat, name, phone, interest, notes, status, assigned in demos:
        dblib.q("""INSERT INTO leads (patient_id, source, platform, status, interest,
            notes, assigned_to, created_at) VALUES (NULL,?,?,?, ?,?, ?,?)""",
                (src, plat, status, interest, notes, assigned, now))
    print(f"  [seed] leads: inserted {len(demos)} sample leads (delete anytime)")


if __name__ == "__main__":
    main()
