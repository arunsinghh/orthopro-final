# OrthoPro India — Production-Hardened Website + Admin Panel

Prosthetics & orthotics clinic website with a full admin panel, rebuilt for
production: **PostgreSQL, secure authentication, CSRF protection, hardened
sessions, secure uploads, environment-based secrets, audit logging, encrypted
backups** — while keeping every public URL, SEO tag, template and admin feature
working exactly as before.

> See `AUDIT.md` (what was found), `SECURITY.md` (security model) and
> `DATABASE.md` (schema, migration, backup/restore).

---

## Project layout

```
clinic/
├── app/                        # Flask application package
│   ├── __init__.py             # app factory
│   ├── config.py               # dev / test / prod config (env-driven)
│   ├── db.py                   # SQLAlchemy engine, q() helper, transactions
│   ├── security.py             # Argon2id hashing, login guard, throttling, headers
│   ├── uploads.py              # upload validation + safe serving
│   ├── audit.py                # audit logging
│   ├── helpers.py              # settings, counters, SEO meta, template filters
│   ├── auth/routes.py          # login / logout
│   ├── public/routes.py        # all public SEO pages
│   ├── admin/routes.py         # admin panel routes
│   ├── templates/              # moved from top-level
│   └── static/                 # css / js / img
├── migrations/001_initial.sql  # PostgreSQL schema (idempotent)
├── scripts/
│   ├── init_db.py              # apply schema (never drops data)
│   ├── migrate_sqlite_to_postgres.py
│   ├── seed_dev.py             # safe idempotent seeding
│   ├── create_admin.py         # secure admin creation
│   └── backup.sh               # encrypted backup + retention
├── tests/test_app.py           # 36 tests (public, admin, CSRF, attacks)
├── .env.example  .gitignore  requirements.txt
├── run.py  wsgi.py  gunicorn.conf.py  Procfile
└── data.db                     # original SQLite, kept as migration source
```

## Quick start (development)

```bash
pip install -r requirements.txt
cp .env.example .env            # fill SECRET_KEY + DATABASE_URL
python scripts/init_db.py       # create schema
python scripts/migrate_sqlite_to_postgres.py   # import data.db (or seed_dev.py)
python scripts/create_admin.py  # create the admin account securely
python run.py                   # dev server on :5000
```

## Admin panel
- URL: `/admin` (redirects to `/admin/login`).
- Authentication is **username + password → secure session**. There is no
  access-key/magic-link (removed). CSRF-protected; sessions expire; failed
  logins are rate-limited and audited.
- Features (unchanged): dashboard, patients (area/service filters), follow-up
  notifications, appointments, patient journeys, products & prices, blog/SEO
  guides, reviews, media library (images/videos), clinic settings.

## Running tests

```bash
FLASK_ENV=testing DATABASE_URL=postgresql://orthopro_app:<pw>@127.0.0.1:5432/orthopro_test \
    python -m pytest tests/ -v
```

## Production deployment

```bash
export FLASK_ENV=production
# .env must contain a strong SECRET_KEY and a PostgreSQL DATABASE_URL
gunicorn -c gunicorn.conf.py wsgi:app      # or: use the Procfile
```

Terminate TLS in front (nginx/ALB) so `SESSION_COOKIE_SECURE` and HSTS apply.
Schedule `scripts/backup.sh` via cron. Full checklist in `SECURITY.md §11`.

## What changed from the previous build
- SQLite → **PostgreSQL** (SQLAlchemy, pooling, FKs, indexes) with a verified
  zero-loss migration from `data.db` (which is retained, never deleted).
- Removed hardcoded secret key, default `admin123`, and the permanent admin
  access-key/magic-link; replaced with Argon2id password auth + secure sessions.
- Added **CSRF protection** on all 24 forms, security headers/CSP, login
  throttling, audit logging, secure upload validation, encrypted backups.
- Refactored the single 839-line file into a clean package; removed dead code.
- All public URLs, SEO meta, structured data and templates preserved.

---

## ️ Simple Map (non-developer friendly)

Don't worry about the number of files — you only ever need these:

| What | Where | Meaning |
|---|---|---|
| **Your website pages** | `app/templates/` | home, services, gallery, prices, contact |
| **Admin / CRM screens** | `app/templates/admin/` | leads, patients, staff, settings |
| **Page logic (the "engine")** | `app/public/routes.py` (site) · `app/admin/routes.py` (CRM) | which page does what |
| **Photos & videos** | `app/static/img/` · `app/static/vid/` | everything you see |
| **Database** | PostgreSQL (`orthopro`) | your real data — never in files |
| **Start site locally** | `python3 run.py` | opens on port 5000 |
| **Run all self-checks** | `python3 -m pytest tests/ -q` | "64 passed" = healthy |
| **AWS deployment steps** | `AWS_DEPLOY.md` | when you're ready to go live |
| **WhatsApp/Facebook leads setup** | `docs/META_WHATSAPP_SETUP.md` | webhook + tunnel guide |

Everything else (`app/db.py`, `app/security.py`, `app/helpers.py` …) is internal
plumbing — like the wiring behind the walls. You never need to open it.

**Rule of thumb:** content changes (prices, photos, reviews, staff, leads) are done
in the **Admin panel**, not in files. Structural changes are requested in plain
English and implemented for you.
