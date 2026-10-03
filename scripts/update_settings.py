#!/usr/bin/env python3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import db
from app.config import get_config

def main():
    cfg = get_config()
    class App:
        config = {"DATABASE_URL": cfg.DATABASE_URL, "DB_POOL_SIZE": 1, "DB_MAX_OVERFLOW": 1}
        extensions = {}
    db.init_app(App())
    url = "https://share.google/43Xf7XcTXUTvqFXV2"
    db.q("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", ("gmb_url", url))
    db.q("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", ("google_reviews_url", url))
    print("Settings updated successfully with Google reviews URL!")

if __name__ == "__main__":
    main()
