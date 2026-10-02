#!/usr/bin/env python3
"""Seed/refresh the public Gallery (wrapper around app.gallery_seed)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db                       # noqa: E402
from app.config import get_config        # noqa: E402
from app.gallery_seed import sync_gallery  # noqa: E402


def main():
    cfg = get_config()

    class _App:
        config = {"DATABASE_URL": cfg.DATABASE_URL, "DB_POOL_SIZE": 2,
                  "DB_MAX_OVERFLOW": 2,
                  "UPLOAD_DIR": os.path.join(os.path.dirname(
                      os.path.dirname(os.path.abspath(__file__))), "uploads")}
        extensions = {}

    db.init_app(_App())
    added = sync_gallery(_App.config["UPLOAD_DIR"])
    n = db.q("SELECT COUNT(*) c FROM media WHERE category='gallery'", one=True)["c"]
    print(f"[seed_gallery] added {added}; gallery items total: {n}")


if __name__ == "__main__":
    main()
