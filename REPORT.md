# Production-Readiness Refactor — Final Report (A–J)

OrthoPro India Flask application. Audit-first, zero data loss, all public URLs /
SEO / admin functionality preserved. Date: 2026-09-12.

---

## A. Audit findings (before any change)
Full report: `AUDIT.md` (20 findings). Highlights:
- **Critical:** hardcoded `SECRET_KEY`; default credential `admin123`; permanent
  admin access-key + magic links in URLs (leak via logs/history/referrers); zero
  CSRF protection on 24 forms; `seed.py` dropped & recreated all tables
  (destructive in production).
- **High:** upload validation by file extension only; unauthenticated, guessable
  `/uploads/<filename>`; no security headers; unhardened session cookies; no login
  throttling; SQLite-only SQL with no FKs/cascades.
- **Medium:** 32 `SELECT *` queries; no audit logging; non-transactional settings
  writes; no `.env`/`.gitignore`; Flask dev server intended for production.
- **Low:** dead code, unused imports, admin key exposed in settings page, missing indexes.

## B. Changes made (refactor)
- Restructured the 839-line single file into a clean package (`app/`): factory +
  `config.py`, `db.py`, `security.py`, `uploads.py`, `audit.py`, `helpers.py`, and
  `auth/`, `public/`, `admin/` blueprints. Simplicity kept — 3 small route modules.
- `db.q()` keeps `?` placeholders, dict rows, ISO-string dates → **zero rewrites**
  of the ~120 existing queries and all templates.
- All inline `onclick/onsubmit/onchange` handlers externalized to
  `static/js/site.js` + `admin.js` (data-attributes) so a strict CSP
  (`script-src 'self'`) works.
- Flask-WTF `CSRFProtect` + `csrf_field()` context processor; every one of the 24
  forms carries a token; CSRF cannot be disabled in production.
- Dev/Test/Prod config classes; prod **fails fast** without strong secrets
  (verified: missing SECRET_KEY/DATABASE_URL, weak key, and sqlite URLs all abort).
- Public URLs, templates, meta tags, JSON-LD, sitemap and robots preserved 1:1.

## C. SQLite → PostgreSQL migration
- Schema: `migrations/001_initial.sql` — 12 tables, real FKs with
  `ON DELETE CASCADE` (followups→patients), CHECK constraints (rating 1–5,
  price_max ≥ price_min), UNIQUE slugs/usernames, targeted indexes on hot columns
  (patients.name/phone/area, appointments.status, followups.due_date, posts.slug…).
- `python scripts/migrate_sqlite_to_postgres.py`:
  - reads `data.db` read-only, **never deletes it** (file still present, untouched);
  - preserves IDs, relationships, timestamps; explicit-id inserts + sequence reset;
  - refuses to run against a non-empty destination unless `--overwrite`;
  - single transaction per table group; full rollback on any failure;
  - prints a per-table source/inserted/failed verification report.
- **Result: 68/68 rows, 11/11 tables, 0 failures** (users 1, settings 12, services 8,
  products 21, journeys 3, patients 6, appointments 4, followups 4, testimonials 6,
  posts 3, media 0). Post-checks: 0 orphaned follow-ups, sequences correct
  (e.g. patients next id = 7).

## D. Authentication & authorization
- **Access-key / magic-link mechanism removed entirely** (not kept for compatibility).
- Now: username + password → server-side session. Login clears/re-issues the
  session (fixation defence); `PERMANENT_SESSION_LIFETIME` expiry; logout route.
- Cookies: `HttpOnly`, `SameSite=Lax` always; `Secure` + HTTPS scheme in production.
- Throttling: 5 failed attempts per IP+user → 15-minute lockout (logged; documented
  in-memory per worker, with redis noted for multi-worker scale-out).
- Every `/admin/*` route gated by `@login_required`; unauthenticated access → 302
  to login (verified). Single admin role — no IDOR surface: all mutations require
  the authenticated session; there are no per-user ownership endpoints to bypass.
- Default `admin123` **destroyed**; new admin password is Argon2id, generated once,
  verified by hash round-trip, plaintext discarded (recoverable only by resetting
  via `python scripts/create_admin.py`).

## E. Secrets management
- All secrets moved to `.env` (chmod 600, git-ignored) + `.env.example` template.
- Generated and rotated: `SECRET_KEY` (token_hex(32)), DB password, backup passphrase.
  Nothing sensitive exists in code, docs, or this report.
- `.gitignore`: `.env`, `*.db`/`data.db`, `uploads/`, `backups/`, `__pycache__`, logs.
- Old sources containing hardcoded secrets were deleted after verification.
- Source scan confirms zero hardcoded secrets remain (remaining matches are the
  validation logic and a weak-password blocklist, which are intentional).

## F. Patient data protection
- Patient records exist only in PostgreSQL, reachable only via authenticated admin;
  public site shows only clinic-published anonymized stories/testimonials.
- List views select explicit columns (no `SELECT *` on patient data).
- `audit_log` table + structured logs record logins, lockouts, and every
  create/update/delete (actor, action, target id) — never passwords, cookies, or
  clinical note text. Sample: `login ×2, login_failed ×2, review_toggle ×1`.
- DB connections via the least-privilege `orthopro_app` role; TLS-ready
  `DATABASE_URL`; `uploads/` git-ignored; private media auth-gated (see G).
- Patient identifiers never appear in URLs of public routes.

## G. Upload security
- Whitelist by extension **and** magic-byte content sniffing:
  - valid PNG accepted; HTML disguised as `.png` → rejected; `.py` → rejected.
- Random 32-hex storage filenames; original names stored only in DB (no path
  traversal possible; filenames regex-validated before serving).
- Size cap 50 MB (config) + Gunicorn limit; forced `Content-Type` and
  `X-Content-Type-Options: nosniff` on serve (stored file can't execute as HTML).
- `is_private` media served only through the authenticated
  `/uploads/private/<file>` route (anonymous → 403; verified by tests).

## H. Cleanup
- Deleted the superseded originals (`app.py`, `seed.py`, top-level
  `templates/`, `static/`) — they contained hardcoded secrets and duplicated code.
- Removed dead helpers/imports; kept merely verbose but functional code per spec.
- `seed_dev.py` is idempotent and never drops tables; `init_db.py` only creates
  missing objects. Destructive seeding eliminated.
- `data.db` retained untouched as the migration source (archivable after sign-off).

## I. Deployment
- `wsgi.py` + `gunicorn.conf.py` + `Procfile` (Gunicorn, never the dev server).
- `.env`: `FLASK_ENV=production`, strong `SECRET_KEY`, PostgreSQL `DATABASE_URL`.
- Production hardening active only in prod: `Secure` cookies, HSTS, `X-Frame-Options`,
  strict CSP, HTTPS scheme — dev preview stays usable over plain HTTP.
- Backups: `scripts/backup.sh` — daily `pg_dump`, gzip, AES-256 (pbkdf2), chmod 600,
  14-day retention, passphrase from env. Restore procedure + test in `DATABASE.md`.
- Runbook: `README.md`; security model in `SECURITY.md`; schema/migration/backup
  details in `DATABASE.md`; pre-change findings in `AUDIT.md`.

## J. Tests
`tests/test_app.py` — **36 tests, all passing** against a dedicated `orthopro_test`
PostgreSQL database:
- **Public:** all 13 routes return 200 (incl. `/sitemap.xml`, `/robots.txt`);
  SEO meta + schema.org JSON-LD present; unknown service/blog slug → 404.
- **Admin:** login success/failure, logout, wrong-password lockout path,
  default/weak passwords rejected; full CRUD for patients/products/followups
  incl. cascade delete.
- **Security:** CSRF-less POST → 400 (with CSRF enforced); SQL-injection payload in
  search is stored literally, not executed (`Robert'); DROP TABLE…` round-trips);
  path-traversal upload names neutralized; extension/content-type spoofing blocked;
  private media 403 anonymous / 200 authenticated; upload endpoint requires auth;
  security headers asserted; security headers + session flags verified.

---
### Operational notes
- Admin login: username `admin`; password was generated during setup, stored only as
  an Argon2id hash, and intentionally not written anywhere. To set a new one:
  `python scripts/create_admin.py`.
- PostgreSQL: databases `orthopro` (live) + `orthopro_test` (tests), role
  `orthopro_app` (password only in `.env`). Restart DB if needed:
  `sudo service postgresql start`.
