#!/usr/bin/env python3
"""Convenience script to set or reset a local user's password.

Usage:
    python scripts/set_password.py <username> <new_password>
Example:
    python scripts/set_password.py admin Admin@12345
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db as dblib
from app.config import get_config
from app.security import hash_password


def set_user_password(username, new_password):
    cfg = get_config()
    class _App:
        config = {"DATABASE_URL": cfg.DATABASE_URL, "DB_POOL_SIZE": 2, "DB_MAX_OVERFLOW": 2}
        extensions = {}
    dblib.init_app(_App())

    u = username.strip()
    pw = new_password.strip()
    if not u or not pw:
        print("Usage: python scripts/set_password.py <username> <new_password>")
        sys.exit(1)

    existing = dblib.q("SELECT id, username, role FROM users WHERE username=?", (u,), one=True)
    pw_hash = hash_password(pw)
    if existing:
        dblib.q("UPDATE users SET password_hash=?, is_active=1 WHERE username=?", (pw_hash, u))
        print(f"SUCCESS: Password updated for user '{u}' (ID: {existing['id']}, Role: {existing['role']}).")
    else:
        dblib.q("""INSERT INTO users (username, password_hash, role, is_active, created_at)
            VALUES (?, ?, 'super_admin', 1, NOW())""", (u, pw_hash))
        print(f"SUCCESS: New super_admin user '{u}' created.")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/set_password.py <username> <new_password>")
        sys.exit(1)
    set_user_password(sys.argv[1], sys.argv[2])

