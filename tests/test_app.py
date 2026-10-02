"""Test suite for OrthoPro India (production-hardened build).

Uses a dedicated PostgreSQL test database (orthopro_test). Run with:
    FLASK_ENV=testing DATABASE_URL=postgresql://orthopro_app:<pw>@127.0.0.1:5432/orthopro_test \
        pytest tests/ -v
"""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, csrf              # noqa: E402
from app import db as dblib                  # noqa: E402
from app.security import hash_password       # noqa: E402

TEST_DB = os.environ.get(
    "DATABASE_URL", "postgresql://orthopro_app:test@127.0.0.1:5432/orthopro_test")
ADMIN_USER = "admin"
ADMIN_PW = "Str0ng!Passw0rd#2026"


def _bootstrap_db(app):
    mdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "migrations")
    # wipe leftover rows from a previous session BEFORE schema changes so
    # constraint re-creation can never clash with old test data
    try:
        dblib.q("TRUNCATE users, leads, patients RESTART IDENTITY CASCADE")
    except Exception:
        pass
    for fname in sorted(f for f in os.listdir(mdir) if f.endswith(".sql")):
        with open(os.path.join(mdir, fname), encoding="utf-8") as f:
            dblib.apply_schema(f.read())
    # wipe + minimal seed
    with dblib.transaction() as conn:
        from sqlalchemy import text
        conn.execute(text("TRUNCATE users, settings, services, products, journeys, "
                          "patients, appointments, followups, media, testimonials, "
                          "posts, audit_log RESTART IDENTITY CASCADE"))
    dblib.q("INSERT INTO users (username, password_hash) VALUES (?,?)",
            (ADMIN_USER, hash_password(ADMIN_PW)))
    dblib.q("INSERT INTO settings (key, value) VALUES ('domain','http://localhost') "
            "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value")
    dblib.q("INSERT INTO services (slug,name,short,category,description,who_for,process,sort) "
            "VALUES ('lower-limb-prosthetics','Lower Limb Prosthetics','Artificial legs',"
            "'Lower Limb Prosthetics','desc','who','proc',1)")
    dblib.q("INSERT INTO products (name,category,brand,description,price_min,price_max,sort) "
            "VALUES ('BK Leg','Lower Limb Prosthetics','Brand','desc',25000,50000,1)")
    dblib.q("INSERT INTO journeys (title,patient_name,service,story,featured) "
            "VALUES ('Story','P1','Lower Limb Prosthetics','story body',1)")
    from app.helpers import now as _now
    dblib.q("INSERT INTO posts (title,slug,excerpt,body,status,created_at) "
            "VALUES ('Guide','guide-1','ex','body here','published',?)", (_now(),))
    dblib.q("INSERT INTO testimonials (name,rating,text,approved) VALUES ('T',5,'great',1)")


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    os.environ["DATABASE_URL"] = TEST_DB
    os.environ["FLASK_ENV"] = "testing"
    upload_dir = tmp_path_factory.mktemp("uploads")
    application = create_app("testing")
    application.config["UPLOAD_DIR"] = str(upload_dir)
    with application.app_context():
        _bootstrap_db(application)
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin_client(app, client):
    rv = client.post("/admin/login", data={"username": ADMIN_USER, "password": ADMIN_PW},
                     follow_redirects=False)
    assert rv.status_code in (302, 303)
    return client


# ---------------------------------------------------------------- public pages
@pytest.mark.parametrize("path", [
    "/", "/services", "/services/lower-limb-prosthetics", "/products", "/prices",
    "/journeys", "/journey/1", "/about", "/faq", "/blog", "/blog/guide-1",
    "/contact", "/sitemap.xml", "/robots.txt",
])
def test_public_pages(client, path):
    rv = client.get(path)
    assert rv.status_code == 200, f"{path} -> {rv.status_code}"


def test_services_page_image_cards(client):
    rv = client.get("/services")
    assert rv.status_code == 200 and b"svc-card" in rv.data
    # the seeded test service renders its image card
    assert b"/static/img/services/lower-limb-prosthetics.jpg" in rv.data


def test_service_detail_subcategories(client):
    import json
    dblib.q("""UPDATE services SET subcategories = CAST(? AS jsonb)
        WHERE slug='lower-limb-prosthetics'""",
            (json.dumps([{"title": "Above-Knee (AK) Prosthetic Leg", "icon": "AK",
                          "desc": "Complete AK solutions.",
                          "img": "/static/img/gallery/ak-prosthesis.jpg"}]),))
    rv = client.get("/services/lower-limb-prosthetics")
    assert rv.status_code == 200
    assert b"What We Offer" in rv.data
    assert b"Above-Knee (AK) Prosthetic Leg" in rv.data
    assert b"Complete AK solutions." in rv.data


def test_service_detail_hero_image(client):
    rv = client.get("/services/lower-limb-prosthetics")
    assert rv.status_code == 200 and b"/static/img/services/lower-limb-prosthetics.jpg" in rv.data


def test_gallery_page_images_and_videos(client):
    # seed gallery items the same way the seed script does (random-safe name)
    dblib.q("""INSERT INTO media (filename, orig_name, kind, uploaded_at, is_private,
        scope, category) VALUES (?, 'gal-test.jpg', 'image', now(), 0, 'public',
        'gallery')""", ("ab" * 16 + ".jpg",))
    dblib.q("""INSERT INTO media (filename, orig_name, kind, uploaded_at, is_private,
        scope, category) VALUES (?, 'vid-test.mp4', 'video', now(), 0, 'public',
        'gallery')""", ("cd" * 16 + ".mp4",))
    rv = client.get("/gallery")
    assert rv.status_code == 200
    assert b"<video" in rv.data and b"vid-test.mp4" not in rv.data  # served via random name
    assert b"Product Photos" in rv.data
    # public nav shows the Gallery link
    rv = client.get("/")
    assert b'/gallery' in rv.data
    # sitemap includes it
    rv = client.get("/sitemap.xml")
    assert b"/gallery" in rv.data


def test_sitemap_lists_urls(client):
    rv = client.get("/sitemap.xml")
    assert b"<urlset" in rv.data and b"/services/lower-limb-prosthetics" in rv.data


def test_seo_meta_present(client):
    html = client.get("/").get_data(as_text=True)
    assert 'rel="canonical"' in html
    assert "application/ld+json" in html
    assert 'name="description"' in html


def test_security_headers(client):
    rv = client.get("/")
    assert rv.headers.get("X-Content-Type-Options") == "nosniff"
    assert rv.headers.get("Referrer-Policy")


def test_404(client):
    assert client.get("/no-such-page").status_code == 404
    assert client.get("/services/does-not-exist").status_code == 404


def test_contact_form_inserts(client):
    rv = client.post("/contact", data={"name": "X", "phone": "999"}, follow_redirects=True)
    assert rv.status_code == 200
    row = dblib.q("SELECT COUNT(*) c FROM appointments WHERE phone='999'", one=True)
    assert row["c"] == 1


def test_review_needs_csrf_in_real_mode(app):
    # Build a CSRF-enforced client to prove forms are actually protected.
    app.config["WTF_CSRF_ENABLED"] = True
    c = app.test_client()
    rv = c.post("/review", data={"name": "A", "text": "B", "rating": "5"})
    assert rv.status_code == 400  # CSRF token missing
    app.config["WTF_CSRF_ENABLED"] = False


# ---------------------------------------------------------------- admin auth
def test_admin_requires_login(client):
    for path in ["/admin", "/admin/patients", "/admin/products", "/admin/settings"]:
        rv = client.get(path)
        assert rv.status_code in (302, 303), path
        assert "/admin/login" in rv.headers["Location"]


def test_login_wrong_password(client):
    rv = client.post("/admin/login", data={"username": ADMIN_USER, "password": "wrong"},
                     follow_redirects=True)
    assert rv.status_code == 200
    assert b"Invalid username or password" in rv.data
    # must NOT be authenticated
    assert client.get("/admin/patients").status_code in (302, 303)


def test_login_success_and_logout(admin_client):
    assert admin_client.get("/admin/patients").status_code == 200
    rv = admin_client.get("/admin/logout", follow_redirects=False)
    assert rv.status_code in (302, 303)
    assert admin_client.get("/admin/patients").status_code in (302, 303)


def test_default_password_rejected(client):
    rv = client.post("/admin/login", data={"username": "admin", "password": "admin123"},
                     follow_redirects=True)
    assert b"Invalid username or password" in rv.data


# ---------------------------------------------------------------- admin CRUD
def test_patient_crud(admin_client):
    rv = admin_client.post("/admin/patients/new", data={
        "name": "Test Patient", "phone": "12345", "area": "TestArea", "status": "active",
    }, follow_redirects=True)
    assert rv.status_code == 200
    row = dblib.q("SELECT * FROM patients WHERE name='Test Patient'", one=True)
    assert row is not None and row["serial_no"]
    assert row["pipeline_stage"] == "consultation"
    pid = row["id"]
    # search finds it
    rv = admin_client.get("/admin/patients?q=Test Patient")
    assert b"Test Patient" in rv.data
    # delete (cascades followups)
    rv = admin_client.post(f"/admin/patients/{pid}/delete", follow_redirects=True)
    assert rv.status_code == 200
    assert dblib.q("SELECT COUNT(*) c FROM patients WHERE id=?", (pid,), one=True)["c"] == 0


def test_sql_injection_in_search(admin_client):
    # Parameterized queries: this must not error and must not dump all rows.
    rv = admin_client.get("/admin/patients?q=" + "%27%20OR%20%271%27%3D%271")
    assert rv.status_code == 200
    # name param with SQL metacharacters should be stored literally, not executed
    admin_client.post("/admin/patients/new", data={
        "name": "Robert'); DROP TABLE patients;--", "status": "active"})
    assert dblib.q("SELECT COUNT(*) c FROM patients", one=True) is not None
    row = dblib.q("SELECT name FROM patients WHERE name LIKE ?",
                  ("Robert%DROP TABLE%",), one=True)
    assert row is not None  # stored as literal text


def test_product_create_and_delete(admin_client):
    admin_client.post("/admin/products/new", data={
        "name": "Test Product", "category": "Orthotics & Braces", "brand": "B",
        "price_min": "100", "price_max": "200"}, follow_redirects=True)
    row = dblib.q("SELECT * FROM products WHERE name='Test Product'", one=True)
    assert row and float(row["price_min"]) == 100
    admin_client.post(f"/admin/products/{row['id']}/delete", follow_redirects=True)
    assert dblib.q("SELECT COUNT(*) c FROM products WHERE name='Test Product'", one=True)["c"] == 0


def test_followup_requires_existing_patient(admin_client):
    admin_client.post("/admin/patients/new", data={"name": "FU Patient", "status": "active"},
                      follow_redirects=True)
    pid = dblib.q("SELECT id FROM patients WHERE name='FU Patient'", one=True)["id"]
    admin_client.post("/admin/followups/new", data={"patient_id": pid, "due_date": "2030-01-01",
                                                   "note": "check"}, follow_redirects=True)
    assert dblib.q("SELECT COUNT(*) c FROM followups WHERE patient_id=?", (pid,), one=True)["c"] == 1
    # cascade delete
    admin_client.post(f"/admin/patients/{pid}/delete", follow_redirects=True)
    assert dblib.q("SELECT COUNT(*) c FROM followups WHERE patient_id=?", (pid,), one=True)["c"] == 0


# ---------------------------------------------------------------- uploads
def _png_bytes():
    import struct, zlib
    def chunk(typ, data):
        c = struct.pack(">I", len(data)) + typ + data
        return c + struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = zlib.compress(b"\x00\xff\x00\x00")
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def test_upload_valid_image(admin_client, app):
    data = {"files": (io.BytesIO(_png_bytes()), "ok.png")}
    rv = admin_client.post("/admin/media", data=data, content_type="multipart/form-data",
                           follow_redirects=True)
    assert rv.status_code == 200
    row = dblib.q("SELECT * FROM media WHERE orig_name='ok.png'", one=True)
    assert row is not None and row["kind"] == "image"
    # served with forced content type + nosniff
    rv = admin_client.get(f"/uploads/{row['filename']}")
    assert rv.status_code == 200
    assert rv.headers["Content-Type"].startswith("image/png")
    assert rv.headers.get("X-Content-Type-Options") == "nosniff"


def test_upload_disguised_file_rejected(admin_client):
    # .png extension but HTML content -> must be rejected (magic-byte sniff)
    data = {"files": (io.BytesIO(b"<html><script>alert(1)</script></html>"), "evil.png")}
    rv = admin_client.post("/admin/media", data=data, content_type="multipart/form-data",
                           follow_redirects=True)
    assert rv.status_code == 200
    assert dblib.q("SELECT COUNT(*) c FROM media WHERE orig_name='evil.png'", one=True)["c"] == 0


def test_upload_disallowed_extension_rejected(admin_client):
    data = {"files": (io.BytesIO(b"#!/usr/bin/env python\nprint('hi')"), "shell.py")}
    admin_client.post("/admin/media", data=data, content_type="multipart/form-data",
                      follow_redirects=True)
    assert dblib.q("SELECT COUNT(*) c FROM media WHERE orig_name='shell.py'", one=True)["c"] == 0


def test_upload_path_traversal_filename_safe(admin_client):
    data = {"files": (io.BytesIO(_png_bytes()), "../../../etc/passwd.png")}
    admin_client.post("/admin/media", data=data, content_type="multipart/form-data",
                      follow_redirects=True)
    row = dblib.q("SELECT * FROM media WHERE orig_name LIKE '%passwd%'", one=True)
    if row:  # if stored, the on-disk name must be randomized, not the traversal path
        assert "/" not in row["filename"] and ".." not in row["filename"]


def test_private_media_requires_auth(app, admin_client):
    fname = "a" * 32 + ".png"
    dblib.q("INSERT INTO media (filename, orig_name, kind, is_private) VALUES (?,?,?,1)",
            (fname, "priv.png", "image"))
    # write a real file so serving can succeed if authorized
    import os as _os
    with open(_os.path.join(app.config["UPLOAD_DIR"], fname), "wb") as f:
        f.write(_png_bytes())
    anon = app.test_client()
    assert anon.get(f"/uploads/private/{fname}").status_code == 403
    assert admin_client.get(f"/uploads/private/{fname}").status_code == 200


def test_upload_requires_auth(app):
    anon = app.test_client()
    rv = anon.post("/admin/media", data={"files": (io.BytesIO(_png_bytes()), "x.png")},
                   content_type="multipart/form-data")
    assert rv.status_code in (302, 303)  # redirected to login
    assert "/admin/login" in rv.headers["Location"]


def test_uploads_guess_resistance(client):
    # random nonexistent file -> 404, no directory listing
    assert client.get("/uploads/deadbeefdeadbeefdeadbeefdeadbeef.png").status_code == 404
    assert client.get("/uploads/../app/config.py").status_code == 404


# ---------------------------------------------------------------- authorization
def test_patient_delete_requires_auth(app):
    anon = app.test_client()
    rv = anon.post("/admin/patients/1/delete")
    assert rv.status_code in (302, 303)
    assert "/admin/login" in rv.headers["Location"]


def test_whatsapp_webhook_autotypes_lead(client, monkeypatch):
    import hashlib
    import hmac
    import json
    monkeypatch.setenv("META_APP_SECRET", "testsecret")
    payload = {"object": "whatsapp_business_account", "entry": [{"id": "W",
        "changes": [{"field": "messages", "value": {
            "contacts": [{"profile": {"name": "Webhook Person"}, "wa_id": "919000000009"}],
            "messages": [{"id": "wamid.TEST1", "timestamp": "1700000000", "type": "text",
                          "text": {"body": "I need an artificial leg for my mother"}}]}}]}]}
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"testsecret", raw, hashlib.sha256).hexdigest()
    rv = client.post("/webhooks/meta", data=raw,
                     headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"})
    assert rv.status_code == 200
    row = dblib.q("SELECT platform, interest, source FROM leads ORDER BY id DESC LIMIT 1", one=True)
    assert row["platform"] == "whatsapp"
    assert row["interest"] == "Lower Limb (Leg)"
