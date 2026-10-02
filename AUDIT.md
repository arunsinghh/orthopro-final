# OrthoPro India — Pre-Refactor Security & Code Audit

Audited **before any changes**. Scope: `app.py` (839 lines), `seed.py` (540 lines), 24 templates, 2 CSS files, SQLite `data.db`.

## Environment facts
- Python 3.13, Flask 3.x, Werkzeug. Data volumes: patients 6, products 21, services 8, posts 3, journeys 3, testimonials 6, appointments 4, followups 4, users 1, settings 12, media 0.
- All SQL is parameterized through a single `q()` helper (no string-concatenated SQL found). Good baseline.
- Templates use hardcoded paths (no `url_for`), so route refactoring will not break templates.

## Findings (Problem → Risk → Fix)

### Critical
1. **Hardcoded Flask `secret_key`** (`app.py:16`). Risk: session-cookie forgery, CSRF-token forgery. Fix: env var, fail-fast in production.
2. **Default admin password `admin123`** (`seed.py`). Risk: trivial takeover of a clinical admin panel. Fix: remove; interactive `create_admin.py`; Argon2id hashing.
3. **Permanent admin access-key + magic link in URLs** (`app.py`, `settings.admin_key`, `/admin/key/<key>`). Risk: key leaks via browser history, server/proxy logs, referrers, screenshots → full admin access. Fix: **remove entirely**; replace with username+password → secure session.
4. **No CSRF protection** on any of the 24 forms. Risk: cross-site forged admin actions (delete patients, change settings). Fix: Flask-WTF `CSRFProtect` + token in every form.
5. **Destructive seed** (`seed.py:8` `os.remove(DB)`). Risk: wipes production data on re-run. Fix: separate idempotent init/seed that never deletes.

### High
6. **Uploads validated by extension only** (`file_ok`). Risk: executable/HTML/SVG upload, content-type confusion, stored XSS. Fix: magic-byte/MIME sniffing, whitelist, forced safe Content-Type + `nosniff`, random names, size cap.
7. **Unauthenticated, guessable `/uploads/...`** for all media incl. any private patient documents. Risk: private patient files publicly reachable. Fix: `is_private` flag + authenticated serving for private files; public images hardened.
8. **No security headers** (no CSP/HSTS/X-Content-Type-Options/X-Frame-Options/Referrer-Policy). Fix: `after_request` header middleware.
9. **Session cookies not hardened** (no explicit Secure/HttpOnly/SameSite, no expiry). Fix: configure all; `Secure` in prod; session expiry.
10. **No login throttling.** Risk: brute force. Fix: per-IP+username attempt limiter with lockout.
11. **SQLite-specific SQL** (`date('now')`, `PRAGMA foreign_keys`) is non-portable. Fix: parameterized current-date, dialect-aware FK pragma.
12. **No foreign keys / cascades** (e.g. `followups.patient_id`). Fix: real FKs + `ON DELETE CASCADE`.

### Medium
13. **`SELECT *` in 32 queries.** Fix: explicit columns where only a few fields needed (esp. sensitive patient rows); keep where templates use most columns.
14. **No audit logging** of admin actions. Fix: `audit_log` table + structured logging (no PII/passwords).
15. **No transactions across multi-statement writes** (settings loop). Fix: transaction context manager.
16. **No `.env` / `.gitignore`**; secrets live in code/DB. Fix: env-based config, `.env.example`, `.gitignore`.
17. **Dev server used in prod path.** Fix: Gunicorn config.

### Low / cleanup
18. `secure_filename` imported but unused; `jsonld()` helper defined but never used; redundant `import json` inside `jsonld`. Remove.
19. `settings.admin_key` surfaced in `settings.html` — remove with the key feature.
20. No indexes on hot columns. Fix: targeted indexes (patients.name/phone/area, appointments.status, followups.due_date, posts.slug, services.slug, products.category).

## What is already good (kept)
- Parameterized queries everywhere.
- Random generated upload filenames.
- Jinja autoescape on for `.html` (stored content escaped; `|md` filter escapes HTML first).
- Clean, SEO-friendly public URLs (all preserved).
