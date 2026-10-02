# SECURITY.md — OrthoPro India

This document describes the security model of the production-hardened build.
**No real secrets appear in this file or anywhere in the repository.**

---

## 1. Authentication model
- Single admin role (kept deliberately simple — one clinic, one trusted operator).
- Login: **username + password → secure server-side session**. The old permanent
  "access key / magic link in URL" was **removed** because secrets in URLs leak via
  browser history, server/proxy logs, referrer headers and screenshots.
- Passwords are hashed with **Argon2id** (time_cost=3, memory=64 MiB, parallelism=2).
  Legacy Werkzeug `scrypt/pbkdf2` hashes (from the migrated SQLite data) are still
  *verified* so existing accounts keep working until the password is reset — but
  the weak default `admin123` was **removed** (re-hashed to Argon2id).
- Admin accounts are created/rotated only via `python scripts/create_admin.py`,
  which enforces a strength policy (≥12 chars, upper/lower/digit/symbol, no common
  passwords), prompts via `getpass`, and stores **only the hash**.
- **Session fixation defence:** the session is cleared and re-issued on login.
- **Session expiry:** `PERMANENT_SESSION_LIFETIME` (default 8h).
- **Login throttling:** after `LOGIN_MAX_ATTEMPTS` (5) failures per IP+username,
  the pair is locked for `LOGIN_LOCKOUT_SECONDS` (15 min). Failures and lockouts
  are logged.

## 2. Authorization
- Every `/admin/*` route is wrapped in `@login_required`, which requires a valid
  `session["admin_uid"]`. Unauthenticated requests are redirected to login and logged.
- There is no per-record ownership model (single admin role); the guarantee is that
  **no patient/product/content mutation is reachable without authentication**.
- Public website exposes **no patient data** (only anonymized, featured success
  stories and approved testimonials that the clinic chooses to publish).

## 3. Secrets management
- All secrets come from **environment variables** (loaded from `.env` by python-dotenv).
  See `.env.example` for names. **Nothing sensitive is hardcoded.**
- `.env` is git-ignored; `.env.example` contains no real values.
- Production **fails fast** (`ProductionConfig.validate`) if `SECRET_KEY` is missing/
  weak or `DATABASE_URL` is missing/not PostgreSQL. It never falls back to dev secrets.
- Values moved to env: `SECRET_KEY`, `DATABASE_URL`, `UPLOAD_DIR`, `MAX_UPLOAD_MB`,
  `SESSION_LIFETIME_SECONDS`, `LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCKOUT_SECONDS`,
  `LOG_FILE`, `TRUST_PROXY`, backup variables.

## 4. Session & transport hardening
- `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE="Lax"` always.
- `SESSION_COOKIE_SECURE=True` and `PREFERRED_URL_SCHEME=https` in **production**
  (terminate TLS at nginx/load balancer).
- Security headers on every response: `X-Content-Type-Options: nosniff`,
  `Referrer-Policy`, `Permissions-Policy`; in production also `X-Frame-Options`,
  `Strict-Transport-Security` (HSTS) and a restrictive `Content-Security-Policy`
  (`script-src 'self'`, `object-src 'none'`, `form-action 'self'`). Inline event
  handlers were removed from all templates to allow a strict CSP.
- Gunicorn (never the Flask dev server) in production; request-body cap enforced.

## 5. CSRF protection
- **Flask-WTF `CSRFProtect`** validates every state-changing POST. A `csrf_token`
  hidden field is injected into all 24 forms (`{{ csrf_field() }}`).
- Requests without a valid token receive **HTTP 400**. Verified by tests and live.

## 6. Database security
- **PostgreSQL** in production with a **least-privilege** role (`orthopro_app`) that
  is NOT the `postgres` superuser; `PUBLIC` privileges revoked on the database.
- All queries are **parameterized** via a single `db.q()` helper — no string-built SQL.
- Real **foreign keys + `ON DELETE CASCADE`** (e.g. `followups.patient_id`).
- Targeted **indexes** on hot columns (patients.name/phone/area, appointments.status,
  followups.due_date, posts.slug, services.slug, products.category).
- Transactions via `db.transaction()`; rollback on error; settings saved atomically.
- Raw DB exceptions are never returned to users (generic 500 handler); details go to logs.

## 7. File-upload security
- **Whitelist** of extensions **and magic-byte/content sniffing** — the extension alone
  is never trusted (a `.png` containing HTML is rejected).
- Random 32-hex storage filenames; the user-supplied name is never used on disk
  (prevents path traversal/overwrite). Filenames are validated by regex before serving.
- Hard size cap (`MAX_UPLOAD_MB`, default 50 MB; also enforced by Gunicorn).
- Files are served with a **forced Content-Type** + `X-Content-Type-Options: nosniff`
  so a stored file can never execute as HTML/JS. PDFs get a sandboxed CSP.
- Executable/web types (py, php, js, html, svg, sh, …) are not in the whitelist.
- Media can be flagged **private**; private files are only served through the
  authenticated `/uploads/private/<file>` route (403 for anonymous).

## 8. Patient-data protection
- Patient records live only in PostgreSQL, reachable only through authenticated admin.
- List views select **explicit columns** (not `SELECT *`) to minimize exposure.
- **Audit logging** (`audit_log` table + structured logs) records login success/failure,
  logout, and every create/update/delete — recording identifiers and action, **never**
  passwords, session cookies, or free-text clinical notes.
- Logs avoid PII; error responses are generic.

## 9. Backups (see `scripts/backup.sh`)
- **Daily** `pg_dump` → gzip → **AES-256-CBC (pbkdf2) encryption**, `chmod 600`.
- **Retention:** `BACKUP_RETENTION_DAYS` (default 14) with automatic pruning.
- Backups are encrypted at rest; the passphrase comes from env, never the repo.
- **Restore test:** periodically decrypt + `psql` into a scratch DB (procedure in
  DATABASE.md). A backup you have never restored is not a backup.

## 9bis. Meta webhook security (leads)
- `GET /webhooks/meta` echoes `hub.challenge` only when `hub.verify_token`
  matches `META_VERIFY_TOKEN`; otherwise 403.
- `POST /webhooks/meta` accepts events only with a valid `X-Hub-Signature-256`
  (HMAC-SHA256 of the raw body using `META_APP_SECRET`); invalid signatures →
  403 + audit entry. Without `META_APP_SECRET` configured the endpoint is
  disabled (503) — it never accepts unsigned traffic.
- CSRF is exempted for this blueprint only: it is machine-to-machine traffic
  with no browser session, protected by the signature check instead.
- Idempotency: each event's external id (`leadgen:<id>` / `wa:<message-id>`)
  is stored in a unique partial index — Meta retries never duplicate leads,
  patients or follow-ups.
- No Meta secret ever reaches frontend code; all live in `.env`.

## 10. Incident response basics
1. **Suspected compromise:** rotate `SECRET_KEY` (invalidates all sessions), reset the
   admin password via `create_admin.py`, rotate the DB password, and restart workers.
2. **Review `audit_log`** and application logs to scope the activity (times, IPs, actions).
3. **Restore** from the most recent verified encrypted backup if data was tampered with.
4. Check for unauthorized media in `uploads/` and unauthorized users in `users`.

## 11. Production checklist
- [ ] `FLASK_ENV=production`; strong unique `SECRET_KEY`; PostgreSQL `DATABASE_URL`.
- [ ] Admin created via `create_admin.py` (no default passwords anywhere).
- [ ] TLS terminated upstream; `SESSION_COOKIE_SECURE` active.
- [ ] Least-privilege DB role; PostgreSQL not exposed publicly.
- [ ] Cron backup job configured + restore tested at least once.
- [ ] Run `pytest tests/ -v` — all pass.
- [ ] Serve with Gunicorn (`Procfile` / `gunicorn.conf.py`), not `run.py`.
