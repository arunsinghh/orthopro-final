#!/usr/bin/env python3
"""Securely create (or reset) the admin account.

Prompts for username and password, enforces a strength policy, hashes with
Argon2id, and stores ONLY the hash. The password is never printed or stored
in plaintext anywhere.

Usage:
    python scripts/create_admin.py            # create or reset interactively
    python scripts/create_admin.py --username ops --reset   # reset existing
"""
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db as dblib                        # noqa: E402
from app.config import get_config                  # noqa: E402
from app.security import hash_password, password_strength_ok  # noqa: E402


def _init():
    cfg = get_config()

    class _App:
        config = {"DATABASE_URL": cfg.DATABASE_URL, "DB_POOL_SIZE": 2, "DB_MAX_OVERFLOW": 2}
        extensions = {}

    dblib.init_app(_App())


def main():
    _init()

    username = input("Admin username: ").strip()
    if not username or len(username) < 3:
        sys.exit("Username must be at least 3 characters.")

    while True:
        pw = getpass.getpass("Password: ")
        pw2 = getpass.getpass("Confirm password: ")
        if pw != pw2:
            print("Passwords do not match. Try again.\n")
            continue
        ok, msg = password_strength_ok(pw)
        if not ok:
            print(msg + " Try again.\n")
            continue
        break

    pw_hash = hash_password(pw)

    existing = dblib.q("SELECT id FROM users WHERE username=?", (username,), one=True)
    if existing:
        dblib.q("UPDATE users SET password_hash=? WHERE username=?", (pw_hash, username))
        print(f"[ok] Password reset for existing admin '{username}'. (Hash stored, plaintext discarded.)")
    else:
        dblib.q("INSERT INTO users (username, password_hash) VALUES (?,?)", (username, pw_hash))
        print(f"[ok] Admin '{username}' created. (Hash stored, plaintext discarded.)")


if __name__ == "__main__":
    main()
