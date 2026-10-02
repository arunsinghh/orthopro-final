#!/usr/bin/env python3
"""Apply the PostgreSQL schema (idempotent — never drops existing data).

Usage:
    python scripts/init_db.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db as dblib           # noqa: E402
from app.config import get_config     # noqa: E402

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "migrations")


def main():
    cfg = get_config()
    print(f"[init_db] DATABASE_URL = {cfg.DATABASE_URL.split('@')[-1]}")

    class _App:  # minimal object so db.init_app works outside Flask
        config = {"DATABASE_URL": cfg.DATABASE_URL, "DB_POOL_SIZE": 5, "DB_MAX_OVERFLOW": 10}
        extensions = {}

    dblib.init_app(_App())
    for fname in sorted(f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql")):
        with open(os.path.join(MIGRATIONS_DIR, fname)) as f:
            dblib.apply_schema(f.read())
        print(f"[init_db] applied {fname}")
    print("[init_db] Schema applied (idempotent). Existing rows untouched.")


if __name__ == "__main__":
    main()
