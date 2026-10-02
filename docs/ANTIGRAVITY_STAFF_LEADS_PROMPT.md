# PROMPT — Staff Accounts, Lead Assignment & Admin Monitoring
### Paste this entire file into Google Antigravity (Gemini) with the project folder open.

You are working on an existing production Flask website + CRM for a prosthetics clinic
("OrthoPro Artificial Limbs Center", Delhi). Read the code first, then implement the
feature below WITHOUT breaking anything that already works.

## Stack & conventions (already in the repo — follow them exactly)
- Python 3 + Flask + Jinja2 templates. PostgreSQL via `app/db.py`: use `db.q(sql, args)`
  with `?` positional placeholders (it translates them; never use `::cast` after a `?`,
  use `CAST(? AS type)` if needed).
- Admin routes live in `app/admin/routes.py`, guarded by `@login_required` and
  `@role_required("<cap>")`. Security helpers in `app/security.py`
  (`hash_password`, `ROLE_CAPS`, `current_role()`).
- Templates: `app/templates/admin/*.html` (reuse existing CSS classes: `.card`,
  `.tbl-wrap`, `.btn`, `.fgrid`, `.alert`). Public pages must keep working.
- Schema changes ONLY as new additive SQL files in `migrations/` (next number: 007).
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` style. NEVER drop columns/tables,
  NEVER delete existing data. Applied by `scripts/init_db.py` (idempotent).
- Passwords: Argon2 via `hash_password()` only. NEVER store plaintext.
- CSRF tokens (`{{ csrf_field() }}`) on every form. Do not disable CSRF anywhere.
- Tests: pytest in `tests/` (currently 56 passing — all must stay green; add new tests).
- UI language: plain English, common actions in 1–2 clicks, no fake buttons/counters.

## Current relevant schema (for context)
- `users(id, username, password_hash, created_at)` — today only ONE admin uses the CRM.
- `leads(id, patient_id, source, status, interest, notes, assigned_to BIGINT REFERENCES
  users(id), contacted_at, converted_at, lost_reason, created_at)` — `assigned_to`
  EXISTS but is unused in the UI. Lead outcomes are repeatable and logged in
  `lead_history(lead_id, outcome, note, due_date, created_at)` with outcomes:
  appointment / followup / hold / lost.
- `audit_log` exists — log staff actions there via the existing `record()` helper.

## Feature to build

### 1. Staff accounts (admin creates, with permissions)
- New admin page "Staff & Permissions" (cap `staff`): list users with role + caps;
  create/edit/disable staff accounts.
- Add columns (migration 007): `users.role TEXT NOT NULL DEFAULT 'staff'`,
  `users.caps TEXT NOT NULL DEFAULT 'leads_view'` (comma-separated capability keys),
  `users.active SMALLINT NOT NULL DEFAULT 1`.
- Capability keys (checkboxes in the form, plain labels):
  `leads_view` (see assigned leads), `leads_edit` (update outcomes/notes),
  `patients_view`, `followups`, `reports`. Admin (super_admin) always has everything.
- Creating a staff account: username + temporary password (shown once, hashed with
  `hash_password`), role label, capability checkboxes, active toggle. Staff log in on
  the SAME /admin/login page; session stores user id + caps. Disabled (`active=0`)
  users cannot log in.
- Extend `role_required`/sidebar so a staff user only sees menu items for their caps.

### 2. Lead assignment (admin → staff)
- On the admin Leads page: checkbox per lead + "Assign to ▾" staff dropdown + Assign
  button (bulk, 1 click). Also an assign dropdown inside each lead row/detail.
  Re-assign and "Unassign" must work. Store in `leads.assigned_to`; log via `record()`.
- Optional setting toggle "Auto-distribute new leads round-robin among active staff
  with leads_view" (settings table, default off).
- Admin ALWAYS sees ALL leads (assigned + unassigned) with an "Assigned to" column.

### 3. Staff lead workspace (staff sees ONLY their leads)
- A staff user with `leads_view` sees a "My Leads" page: ONLY leads where
  `assigned_to = <their id>`, sorted newest first, with status chips and the lead's
  phone number as tap-to-call + WhatsApp link (wa.me).
- With `leads_edit`: one-tap outcome buttons per lead (Appointment / Follow-up /
  Hold / Lost) + note field — writing to `lead_history` exactly like the current admin
  flow does (reuse that code path). Every action updates `lead_status` fields and is
  visible to admin instantly (same tables = automatic sync).
- Staff must NEVER be able to query other staff's leads (enforce in the SQL WHERE
  clause server-side, not just hide in UI). Add a test that a staff session cannot see
  or modify another staff's lead (expect 404/403).

### 4. Admin monitoring dashboard
- New admin section "Staff Performance" (cap `reports`): table with one row per staff:
  name, active?, assigned total, contacted, appointments, follow-ups, holds, lost,
  completed (converted), and "last activity" (max created_at of their lead_history).
- Clicking a staff row opens their lead list (admin view). Date-range filter
  (default: this month). Numbers computed from `leads` + `lead_history` (real data,
  no fake counters).

### 5. Definition of done
- migration `007_staff_roles.sql` (additive), route + template changes, sidebar update,
  `scripts/create_admin.py` untouched, seed script gives the existing admin
  role 'super_admin'.
- New pytest tests: staff creation + login; staff sees only own leads; staff without
  leads_edit cannot post outcomes; admin bulk-assign works; performance table shows
  correct counts; disabled staff cannot log in.
- Keep all existing 56 tests green. Manual QA list at the end of your summary.

## Rules
- Simplicity over file count: prefer editing existing routes/templates over new
  blueprints. No new JS frameworks. No external services.
- Do not touch the public website pages except where strictly required.
- After implementing, run `python3 -m pytest tests/ -q` and include the result.
