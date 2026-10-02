# OrthoPro India — Clinical CRM Upgrade: Architecture Plan

Step 1–2 of the implementation process (audit + architecture). Reviewed 2026-09-14.

---

## 1. Current state audit (what exists today)

**Codebase** (hardened production build — see `AUDIT.md`, `REPORT.md`):
- Flask app package: `app/{config,db,security,uploads,audit,helpers}.py` +
  `auth/`, `public/`, `admin/` blueprints; 14 public templates, 15 admin templates.
- **PostgreSQL already in production** (`orthopro`, least-priv role `orthopro_app`),
  migrated from `data.db` with zero loss (68 rows, verified). SQLite retained only
  as the migration source.
- Security already done (spec Parts 47–56 largely satisfied): Argon2id passwords,
  secure sessions (HttpOnly/SameSite/expiry/regeneration), CSRF on all 24 forms,
  security headers/CSP, login throttling, audit_log table, secure uploads
  (magic-byte validation, random filenames, private auth-gated serving),
  `.env` secrets, fail-fast prod config, encrypted backup script, 36 passing tests.

**Current data model** (`migrations/001_initial.sql`): users, settings, services,
products, journeys, patients, appointments, followups, media, testimonials, posts,
audit_log. Patients are flat records (name/age/gender/phone/email/area/service/
product/status/notes/next_followup). Follow-ups are minimal (patient_id, due_date,
note, status). Appointments are website contact-form submissions. **No concept of:**
permanent patient IDs, leads/lifecycle, sources, staff/roles/assignment, treatment
episodes, devices/components, structured measurements, repairs/warranty, billing,
documents, communication history, notifications.

**Gap vs spec:** Parts 1–43, 62–68, 75–78 (the clinical CRM itself) are new work.
Parts 42, 44–56, 69, 72–73 (Postgres, security, backups, env config) are largely
COMPLETE from the hardening build and will be extended, not redone.

## 2. Core architectural decisions

### D1. Master Patient = existing `patients` table, evolved
No new `persons` table. The existing `patients` table becomes the Master Patient
Record: it gains `patient_code` (`OP-000001`, UNIQUE, permanent), demographics,
source, consent flags, and profile-status. Existing 6 records are backfilled with
codes. Everything else FKs to `patients.id`. This preserves existing data, URLs and
admin UI, and makes "never duplicate a patient" a foreign-key guarantee.

### D2. Leads/Enquiries are a first-class module
New `leads` table with lifecycle states (Part 4) and optional `patient_id` link.
Website contact submissions (`appointments`) become promotable to leads; matching
uses duplicate-detection (D6). Converting a lead creates or links the master patient
— never a second record.

### D3. Follow-ups grow in place
Existing `followups` table gains assignment, type, purpose, priority, outcome,
completion metadata, visit dates. Rescheduling is history-preserving (audit + old
values kept in detail). The completion flow (Part 15) is a single transaction:
complete + outcome + optional next visit in one commit.

### D4. Raw-SQL data layer is kept (no ORM rewrite)
`db.q()` with parameterized queries and dict rows is proven, tested and simple.
~30 new queries are better served by consistent helpers than by introducing
SQLAlchemy ORM + Alembic for a 10-patients/day clinic (Part 79). Schema stays
versioned in `migrations/*.sql` (idempotent), applied by `init_db.py`.

### D5. Roles in the database, permissions in code
`users.role` ∈ {super_admin, receptionist, prosthetist, physiotherapist} +
`is_active`. A single permission map in `security.py` maps role → capabilities;
route decorators enforce it. No RBAC tables (expandable later without rewrite).

### D6. Duplicate prevention
Matching service: normalized phone (last-10-digits), WhatsApp, email exact match,
plus name+area similarity. Shown as "possible match" warning before creation
(Open Existing / Create New Anyway). Never auto-merge.

### D7. Storage abstraction for deployment portability
`uploads.py` already isolates file handling. Patient documents/media reuse the
existing `media` table with `scope='patient'` + `patient_id` (auth-gated serving
already exists). If the site moves to serverless hosting (see §6), only the
storage backend swaps — schema and routes stay.

## 3. Target data model (master-patient hub, spec Part 78)

```
                 MASTER PATIENT (patients + patient_code OP-xxxxxx)
                       │
   leads ─ appointments ─ followups ─ treatment_episodes
                                        │
                        devices ─ measurements ─ repairs
                        device_components  device_history
   documents ─ payments/invoices ─ communications ─ (patient) media
   assignment_log ─ notifications ─ audit_log  (cross-cutting)
```

New tables (full DDL in `migrations/002_clinical_crm.sql`, idempotent, additive):
`sources`, `leads`, `treatment_episodes`, `treatment_events`, `devices`,
`device_components`, `device_history`, `measurements` + `measurement_values`,
`followup_templates` + `followup_template_steps`, `repairs`, `invoices`, `payments`,
`communications`, `documents`, `assignment_log`, `notifications`.
Extended: `users` (role/full_name/is_active), `patients` (code/demographics/consent),
`appointments` (patient link/staff/time/reschedule chain), `followups` (lifecycle),
`media` (scope/patient/category), `audit_log` (entity refs), `journeys` (consent link).

History rules (Part 68): treatment/clinical events are append-only
(`treatment_events`); appointment reschedules keep the original row + a new row
linked via `rescheduled_from`; reassignments write `assignment_log`; everything
else lands in `audit_log` with entity refs. Nothing important is overwritten.

## 4. Key workflows

**Quick Add (Part 2):** `+ Quick Add` → name + area (+optional phone/source) →
creates master patient `profile_status='incomplete'`, assigns OP-code → lands on the
patient profile with "Complete profile" and "Add follow-up" quick actions.

**Lead lifecycle (Part 4):** New Enquiry → Contacted → Interested → Appointment
Scheduled → First Visit → Assessment → Treatment Ongoing → Active Patient
(+ Completed/Inactive/Not Interested/Lost). Every transition audited; assignment to
staff recorded in `assignment_log`.

**Follow-up completion (Part 15):** Complete form captures outcome
(working well / adjustment / repair / new device / assessment / other), notes, and
Next Visit = Yes (date+purpose+staff) | Later | No further follow-up. One
transaction: mark completed (who/when) → optionally insert next follow-up → timeline
event → audit → dashboard/workload update automatically (queries are live).

**Measurement structure (Part 12):** header row (patient/episode/device/service/
date/staff) + key/value rows per field. Field sets per service type (BK prosthesis,
AFO, diabetic footwear…) are defined in code — irrelevant fields are never forced,
history is never lost.

## 5. Phased implementation roadmap (spec Part 80)

- **Phase A — Foundation (Steps 3–8): ✅ DONE** — `002` schema live (17 new tables,
  additive); Master Patient with permanent OP-codes (backfilled); Quick Add with
  duplicate warning; Master Profile with 13 tabs (overview/clinical/treatments/
  appointments/follow-ups/devices/measurements/repairs/documents/media/payments/
  communication/activity); global patient search; consent flags; profile
  completeness tracking; entity-tagged audit log. 48 tests passing.
- **Phase B — Leads, Meta & Staff (Steps 9–11 + 22): ✅ DONE** — Meta webhook
  (GET verification + HMAC-SHA256 signed POST, Facebook/Instagram leadgen +
  WhatsApp parsers, idempotency via meta_lead_id, attribution storage, Master
  Patient match/create, local fixtures); Leads UI (All/New/Mine, platform
  filters, marketing performance counts, detail with attribution/assign/
  status/follow-up); follow-up completion flow with mandatory next-visit
  scheduling (same/different staff, history preserved); staff accounts with 4
  roles + backend-enforced permissions; grouped collapsible sidebar
  (CLINIC/WEBSITE/MANAGEMENT, role-aware); action-focused dashboard
  (Needs Attention + Today's Follow-ups); Activity log page. 63 tests passing.
- **Phase C — Care cycle (Steps 12–16): ✅ DONE** — one unified Visits section
  (today/tomorrow/upcoming/past/requests) replacing the old website-request
  table; walk-in capture (find-or-create patient + today's visit, duplicate
  warning via `find_patient_matches`, `force_new` bypass); scheduled visits with
  full status pipeline (Confirm → Arrived → In consultation → Completed,
  completed_at stamped); reschedule preserves the original row (`rescheduled` +
  `rescheduled_from` + reason, history never lost); no-show → one-click
  follow-up; website requests linkable to a patient. Treatment episodes
  (`episode_num` per patient, planned/ongoing/completed, `completed_date`
  stamped) with append-only care timeline (`treatment_events`) — every status
  change and manual event is added, never overwritten. Devices (`DEV-xxxxxx`
  codes) with status history, components (add / mark-replaced, keeps record),
  warranty + replacement-due fields, episode linkage. 74 tests passing; every
  flow live-verified then fixture data removed.
- **Phase D — Clinic ops (Steps 17–21): ✅ DONE** — historical measurements
  with dynamic per-service field sets (BK/AK/AFO/diabetic footwear/upper
  limb/other; only filled fields stored, unknown keys rejected); repairs
  RP-##### with 8-step pipeline, cost estimate/final, device auto-flagged
  under_repair and restored on delivery; billing without accounting —
  quotations (QT-) + invoices (INV-) with discount, payments/advances/refunds
  that auto-sync invoice status (draft→sent→partial→paid); private documents
  + patient media stored scope='patient'/is_private=1, random unguessable
  filenames, auth-gated serving (anonymous access 403), disguised-file and
  extension rejections, delete-with-file; communication log (call/whatsapp/
  sms/email/note, in/out) with no unverified delivery claims; warranty +
  replacement alerts on the Devices tab with one-click follow-up creation.
  84 tests passing; every flow live-verified then fixture data removed.
- **Phase E — Intelligence & polish (Steps 21–26): ✅ DONE** — notifications
  system (assignment, next-visit, warranty events; per-user, deduplicated,
  bell badge + list page + mark-read; never fakes activity); dashboard
  "My Work" block (today's visits + follow-ups assigned to the signed-in
  user, open leads, unread notifications); Reports page (7/30/90/365 days:
  patients, visits, walk-ins, follow-ups, no-shows, repairs, deliveries,
  invoiced vs collected, follow-up outcomes, leads funnel by
  source/platform with contacted/appointment/converted — backend role-gated);
  journey publishing now requires explicit public consent (backend-enforced);
  website Media Library + journey picker strictly exclude patient-scope
  private media; sidebar Reports link + mobile nav flattening.
  `scripts/backfill_002.py` added (idempotent post-refresh re-seed).
  93 tests passing; every flow live-verified then fixture data removed.
- **Phase F — Deployment (27):** final hardening pass + deployment per §6.

Each phase: schema already additive → code → templates → tests → live verification.
Nothing public breaks at any phase boundary.

## 6. Deployment analysis — Vercel (spec Part 71)

**Finding:** Flask on Vercel runs as serverless functions (via `api/` handler /
`vercel.json`). That works for the *website*, but constrains the expanded backend:

1. **No persistent local filesystem** — uploaded patient documents/media would not
   survive cold starts/scales. → Patient files must use object storage (e.g.
   Supabase Storage, Cloudflare R2, or Cloudinary) behind the `uploads.py`
   abstraction (D7), or the app moves to an always-on host.
2. **No local PostgreSQL** — the DB must be a hosted Postgres reachable over TLS
   (Neon / Supabase / Aiven / RDS). The app is already env-driven
   (`DATABASE_URL`), so this is a config change, not a code change.
3. **Stateless instances** — the in-memory login throttle resets per instance
   (acceptable at this scale; noted in SECURITY.md). Sessions are cookie-based and
   already stateless-friendly.
4. **Request limits** — Vercel's body limits (~4.5 MB Hobby) cap upload sizes;
   large gait videos would need the object-storage route anyway.

**Recommendation (smallest reliable change):** keep the public website on Vercel;
add a **hosted PostgreSQL (Neon free tier is sufficient for 10 patients/day)** via
`DATABASE_URL`; put **patient documents/media in Supabase Storage or R2** behind the
existing private-serving route. Alternative if uploads must stay on-disk: move the
whole app to a small VPS (₹300–500/mo) with the provided Gunicorn setup — the
codebase already supports that with zero changes. Decision needed from owner (§7).

## 7. Open decisions for the clinic owner
1. Hosting: Vercel + Neon + object storage, **or** single VPS? (Affects Phase D storage.)
2. Staff list: names + roles of the people who will log in (super admin /
   receptionist / prosthetist / physiotherapist) — to create accounts via `create_admin.py`
   (extended for roles) at Phase B.
3. Currency/billing: GST handling on invoices — simple totals for now (assumed),
   or GST fields needed?

## 8. What will NOT change
All public URLs, SEO/meta/JSON-LD, sitemap/robots, services/products/prices/
journeys/blog/reviews/media/settings management, `data.db` (untouched), the
`.env` secret model, the 36 existing tests (extended, never removed).


---

## 7. 2026-09-25 — Simplification pivot (owner decision)

The owner requested a **radically simpler app**; the phases A–E feature set was
replaced by a minimal, WhatsApp-easy model. Nothing was deleted from the
database (all old tables remain, empty and unused, as a safety net); the
unused routes/templates/tests were removed from the code.

**Current model (live, tested 54/54):**
* **Single admin login** (staff UI removed; backend role system dormant).
* **Leads**: two origins (admin-created; Meta/WhatsApp webhook). Four
  repeatable outcomes: **Appointment / Follow-up / Hold / Lost**, each
  appended to `lead_history` so the repeated process is never lost.
* **Patient**: `serial_no` = YYMM + running number, no padding (first patient
  of Sept 2026 = **26091**). Search by serial or phone. Lifetime record.
* **Pipeline (one per patient, re-openable)**: Consultation →
  Assessment/Measurement → Quotation → Approved → Order Items → Processing →
  Clinical Fitting → Dispatch → Completed. Append-only `patient_stage_log`.
* **Money**: one simple field set on the patient — Total (quotation),
  Advance, Balance. No accounting.
* **Follow-ups**: pending list (overdue / today / upcoming) with one-tap
  Done / Later; WhatsApp deep links.
* **PostgreSQL only** (already the case) + `AWS_DEPLOY.md` for one-EC2 + RDS.
* **Website**: Services pages rebuilt in the iasgroups.in image-card style
  (8 generated, optimized images at /static/img/services/), SEO meta kept.

Schema: migration `004_simple_pipeline.sql` (additive). Tests:
`tests/test_app.py` (public + security + uploads) and `tests/test_simple.py`
(new workflow end-to-end).

## 8. Staff accounts & lead assignment (2026-09-29)
- Migration 007: users gains `caps` (comma list); role CHECK widened with `staff`;
  stray `active` column dropped (existing `is_active` used).
- Permissions (checkboxes per staff): leads (see own), leads_edit (post outcomes),
  patients, followups, reports. super_admin has everything.
- Leads: admin bulk-assign via checkboxes (`/admin/leads/assign`, cap `staff`);
  staff see ONLY their assigned leads (server-side WHERE), outcome buttons gated
  by `leads_edit` + ownership (403 otherwise).
- `/admin/performance` (cap `reports`): per-staff assigned/appointments/follow-ups/
  holds/lost/completed + last activity, range filter, drill-down to their leads.
- Sidebar links gated by `can(...)`; disabled accounts (is_active=0) cannot log in.
- Tests: tests/test_staff.py (7) — suite now 63 passing.

## 9. Leads simplification, WhatsApp webhook live-test, SQLite removal (2026-09-29)
- Leads page: per-lead colored TYPE badge (7 plain types), per-lead assign select,
  type filter; auto-detect type from WhatsApp message text (`helpers.detect_lead_type`).
- Webhook proven end-to-end locally: signed WhatsApp POST → lead with type;
  bad signature → 403. Tunnel tested with cloudflared (no account); ngrok guide in
  docs/META_WHATSAPP_SETUP.md (needs free authtoken).
- SQLite removed: data.db + migrate_sqlite_to_postgres.py deleted; seed data now in
  data_seed_reference.json; config/db refuse sqlite URLs anywhere (Postgres only).
