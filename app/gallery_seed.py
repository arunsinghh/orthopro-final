"""Auto-seed the public Gallery from bundled photo/video assets.

Runs once at app start (idempotent): any asset not yet registered in `media`
with category='gallery' is copied into UPLOAD_DIR under a random name and
registered. A fresh local clone therefore always shows a full gallery without
extra commands — and it never touches or deletes existing rows.
"""
import os
import secrets
import shutil

ITEMS = [
    ("app/static/img/gallery/ak-prosthesis.jpg", "image"),
    ("app/static/img/gallery/bionic-hand.jpg", "image"),
    ("app/static/img/gallery/microprocessor-knee.jpg", "image"),
    ("app/static/img/gallery/carbon-feet.jpg", "image"),
    ("app/static/img/gallery/silicone-hand.jpg", "image"),
    ("app/static/img/gallery/afo-brace.jpg", "image"),
    ("app/static/img/gallery/kafo-brace.jpg", "image"),
    ("app/static/img/gallery/diabetic-footwear.jpg", "image"),
    ("app/static/img/gallery/wheelchair.jpg", "image"),
    ("app/static/img/gallery/mobility-aids.jpg", "image"),
    ("app/static/img/gallery/liners-socks.jpg", "image"),
    ("app/static/img/services/lower-limb-prosthetics.jpg", "image"),
    ("app/static/img/services/upper-limb-prosthetics.jpg", "image"),
    ("app/static/img/services/orthotics-braces.jpg", "image"),
    ("app/static/img/services/diabetic-foot-care.jpg", "image"),
    ("app/static/img/services/pediatric-care.jpg", "image"),
    ("app/static/img/services/rehabilitation-gait-training.jpg", "image"),
    ("app/static/img/services/repair-maintenance.jpg", "image"),
    ("app/static/img/services/home-visit-service.jpg", "image"),
    ("app/static/vid/products-showcase.mp4", "video"),
    ("app/static/vid/patient-care.mp4", "video"),
    ("app/static/vid/braces-supports.mp4", "video"),
]


def sync_gallery(upload_dir):
    from . import db
    from .helpers import now

    os.makedirs(upload_dir, exist_ok=True)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    added = 0
    for rel, kind in ITEMS:
        src = os.path.join(here, rel)
        name = os.path.basename(src)
        if not os.path.exists(src):
            continue
        if db.q("SELECT id FROM media WHERE orig_name=? AND category='gallery'",
                (name,), one=True):
            # refresh content if the bundled asset changed (same safe filename)
            row = db.q("SELECT filename FROM media WHERE orig_name=? AND category='gallery'",
                       (name,), one=True)
            dst = os.path.join(upload_dir, row["filename"])
            if os.path.exists(dst) and os.path.getsize(dst) != os.path.getsize(src):
                shutil.copyfile(src, dst)
            continue
        ext = name.rsplit(".", 1)[1]
        fname = f"{secrets.token_hex(16)}.{ext}"
        shutil.copyfile(src, os.path.join(upload_dir, fname))
        db.q("""INSERT INTO media (filename, orig_name, kind, uploaded_at, is_private,
            scope, category) VALUES (?,?,?, ?, 0, 'public', 'gallery')""",
            (fname, name, kind, now()))
        added += 1
    return added
