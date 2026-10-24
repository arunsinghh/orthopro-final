#!/usr/bin/env python3
"""Populate full reference content from data_seed_reference.json into PostgreSQL.

Ensures the local website matches the published orthoproindia.com website with all
8 services, 21 products, 12 settings, 3 journeys, 6 testimonials, and 3 blog posts,
while keeping all existing leads, patients, and users 100% intact.
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db as dblib
from app.config import get_config
from app.gallery_seed import sync_gallery
from sqlalchemy import text

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF_FILE = os.path.join(HERE, "data_seed_reference.json")


def init():
    cfg = get_config()
    class _App:
        config = {
            "DATABASE_URL": cfg.DATABASE_URL,
            "DB_POOL_SIZE": 2,
            "DB_MAX_OVERFLOW": 2,
            "UPLOAD_DIR": os.path.join(HERE, "uploads")
        }
        extensions = {}
    dblib.init_app(_App())


def populate():
    with open(REF_FILE, encoding="utf-8") as f:
        data = json.load(f)

    # 1. Services (8 total)
    print("--- Populating Services ---")
    for s in data.get("services", []):
        exists = dblib.q("SELECT id FROM services WHERE slug=?", (s["slug"],), one=True)
        if exists:
            dblib.q("""UPDATE services SET 
                name=?, short=?, category=?, icon=?, meta_desc=?, keywords=?,
                description=?, who_for=?, process=?, sort=?, subcategories=COALESCE(subcategories, '[]')
                WHERE slug=?""",
                (s["name"], s["short"], s.get("category", ""), s.get("icon", ""),
                 s.get("meta_desc", ""), s.get("keywords", ""), s.get("description", ""),
                 s.get("who_for", ""), s.get("process", ""), s.get("sort", 1), s["slug"]))
            print(f"  [updated service] {s['slug']}")
        else:
            dblib.q("""INSERT INTO services (slug, name, short, category, icon, meta_desc, keywords, description, who_for, process, sort, subcategories)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]')""",
                (s["slug"], s["name"], s["short"], s.get("category", ""), s.get("icon", ""),
                 s.get("meta_desc", ""), s.get("keywords", ""), s.get("description", ""),
                 s.get("who_for", ""), s.get("process", ""), s.get("sort", 1)))
            print(f"  [inserted service] {s['slug']}")

    # 2. Products (21 total)
    print("--- Populating Products ---")
    for p in data.get("products", []):
        exists = dblib.q("SELECT id FROM products WHERE name=?", (p["name"],), one=True)
        if not exists:
            dblib.q("""INSERT INTO products (name, category, brand, description, price_min, price_max, image, featured, service, sort)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (p["name"], p["category"], p.get("brand", ""), p.get("description", ""),
                 p.get("price_min", 0), p.get("price_max", 0), p.get("image", "") or "",
                 p.get("featured", 0), p.get("service", ""), p.get("sort", 1)))
            print(f"  [inserted product] {p['name']}")
        else:
            print(f"  [exists product] {p['name']}")

    # 3. Settings (12 total: phone, whatsapp, email, address, etc.)
    print("--- Populating Settings ---")
    for stg in data.get("settings", []):
        k, v = stg["key"], stg["value"]
        if k == "address":
            v = "OrthoPro Artificial Limbs Center, Khirki Extension, Malviya Nagar, New Delhi – 110017"
        exists = dblib.q("SELECT key FROM settings WHERE key=?", (k,), one=True)
        if exists:
            dblib.q("UPDATE settings SET value=? WHERE key=?", (v, k))
            print(f"  [updated setting] {k} = {v}")
        else:
            dblib.q("INSERT INTO settings (key, value) VALUES (?, ?)", (k, v))
            print(f"  [inserted setting] {k} = {v}")

    # Ensure google_reviews_url is set
    dblib.q("""INSERT INTO settings (key, value) VALUES ('google_reviews_url', 'https://g.page/r/CbP1aE0n9t9QEAI/review')
        ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value""")

    # 4. Journeys (Patient success stories)
    print("--- Populating Journeys ---")
    for j in data.get("journeys", []):
        exists = dblib.q("SELECT id FROM journeys WHERE title=?", (j["title"],), one=True)
        if not exists:
            dblib.q("""INSERT INTO journeys (title, patient_name, area, service, story, before_image, after_image, video, featured, created_at, consent_public)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (j["title"], j.get("patient_name", ""), j.get("area", ""), j.get("service", ""),
                 j.get("story", ""), j.get("before_image", ""), j.get("after_image", ""),
                 j.get("video", ""), j.get("featured", 1), j.get("created_at", str(dt.datetime.now()))))
            print(f"  [inserted journey] {j['title']}")
        else:
            print(f"  [exists journey] {j['title']}")

    # 5. Testimonials / Reviews (6 total)
    print("--- Populating Testimonials ---")
    for t in data.get("testimonials", []):
        exists = dblib.q("SELECT id FROM testimonials WHERE name=? AND text=?", (t["name"], t["text"]), one=True)
        if not exists:
            dblib.q("""INSERT INTO testimonials (name, rating, text, approved, source)
                VALUES (?, ?, ?, ?, 'google')""",
                (t["name"], t["rating"], t["text"], t.get("approved", 1)))
            print(f"  [inserted testimonial] {t['name']}")
        else:
            print(f"  [exists testimonial] {t['name']}")

    # 6. Blog Posts (3 total)
    print("--- Populating Posts ---")
    for post in data.get("posts", []):
        exists = dblib.q("SELECT id FROM posts WHERE slug=?", (post["slug"],), one=True)
        if not exists:
            dblib.q("""INSERT INTO posts (title, slug, excerpt, body, image, keywords, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (post["title"], post["slug"], post.get("excerpt", ""), post.get("body", ""),
                 post.get("image", ""), post.get("keywords", ""), post.get("status", "published"),
                 post.get("created_at", str(dt.datetime.now()))))
            print(f"  [inserted post] {post['slug']}")
        else:
            print(f"  [exists post] {post['slug']}")

    # 7. Sync gallery images
    print("--- Syncing Gallery ---")
    try:
        added = sync_gallery(os.path.join(HERE, "uploads"))
        print(f"  [gallery] added {added} gallery items")
    except Exception as e:
        print(f"  [gallery warning] {e}")

    # Summary
    print("\n=== Current Database Counts ===")
    for tbl in ["services", "products", "settings", "journeys", "testimonials", "posts", "media", "leads", "patients", "users"]:
        cnt = dblib.q(f"SELECT COUNT(*) c FROM {tbl}", one=True)["c"]
        print(f"  {tbl}: {cnt}")


if __name__ == "__main__":
    init()
    populate()

