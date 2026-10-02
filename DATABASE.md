# DATABASE.md — OrthoPro India

## 1. PostgreSQL setup

The app uses **PostgreSQL** in production (SQLite is development-only and is
rejected by `ProductionConfig`).

```sql
-- Least-privilege role (NOT the postgres superuser)
CREATE ROLE orthopro_app LOGIN PASSWORD '<strong-password-from-env>';
CREATE DATABASE orthopro OWNER orthopro_app;
REVOKE ALL ON DATABASE orthopro FROM PUBLIC;
GRANT CONNECT, TEMP ON DATABASE orthopro TO orthopro_app;
```

Set `DATABASE_URL=postgresql://orthopro_app:<pw>@<host>:5432/orthopro` in `.env`.
Keep PostgreSQL on a private network; do not expose port 5432 publicly.

## 2. Schema overview

Defined in `migrations/001_initial.sql` (idempotent `IF NOT EXISTS`).

| Table         | Purpose                              | Key relationships / constraints |
|---------------|--------------------------------------|---------------------------------|
| users         | admin accounts                       | username UNIQUE, password_hash  |
| settings      | key/value clinic settings            | key PRIMARY KEY                 |
| services      | service pages (SEO)                  | slug UNIQUE                     |
| products      | products + prices                    | CHECK price_max >= price_min    |
| journeys      | public patient stories               |                                 |
| patients      | clinical patient records (sensitive) |                                 |
| appointments  | website booking requests             | status default 'new'            |
| followups     | follow-up notifications              | **FK → patients ON DELETE CASCADE** |
| media         | uploaded files                       | filename UNIQUE, is_private flag|
| testimonials  | reviews                              | CHECK rating 1..5               |
| posts         | blog / SEO guides                    | slug UNIQUE                     |
| audit_log     | admin action audit trail             |                                 |

### Types
- IDs: `BIGSERIAL`. Dates: `DATE`. Timestamps: `TIMESTAMPTZ`. Prices: `NUMERIC(12,2)`.
  Flags: `SMALLINT` 0/1 (matches existing template truthiness).

### Indexes (added for real query patterns)
`patients(name, phone, area, service)`, `appointments(status, created_at)`,
`followups(due_date, status, patient_id)`, `products(category)`, `journeys(featured)`,
`audit_log(action)`, plus the UNIQUE indexes on `users.username`, `services.slug`,
`posts.slug`, `media.filename`, `settings.key`.

## 3. Initialising a fresh database

```bash
python scripts/init_db.py        # applies migrations/001_initial.sql (idempotent)
python scripts/create_admin.py   # create the admin securely
python scripts/seed_dev.py       # optional reference content (never overwrites)
```

`init_db.py` never drops data; it only creates tables/indexes that are missing.

## 4. Migrating existing SQLite data

The original SQLite file `data.db` is migrated **without loss**:

```bash
python scripts/migrate_sqlite_to_postgres.py            # safe: refuses if destination non-empty
python scripts/migrate_sqlite_to_postgres.py --overwrite  # truncate destination first
```

Behaviour:
- Reads `data.db` read-only (never modifies/deletes it).
- Preserves IDs, relationships, timestamps, text, and upload references.
- Renames `users.password` → `users.password_hash`; coerces `NULL`→default for
  `NOT NULL` columns; parses timestamps.
- Resets `BIGSERIAL` sequences to `MAX(id)+1` after inserting explicit IDs.
- Prints a per-table **source vs inserted vs failed** report; exits non-zero on
  any failure and rolls back (nothing is partially committed).

Verified result for this project: all 68 rows across 11 tables migrated, 0 failures,
0 orphaned follow-ups, sequences correct.

## 5. Application data access

- Single helper `app/db.py :: q(sql, args, one)` — parameterized (`?` translated to
  named binds), returns dict rows, atomic per call.
- `db.transaction()` groups multiple statements into one commit/rollback.
- Connection pooling via SQLAlchemy (pool_size/max_overflow configurable).

## 6. Backup & restore

Backup (cron, encrypted): see `scripts/backup.sh`.
```bash
DATABASE_URL=... BACKUP_PASSPHRASE=... scripts/backup.sh
```

Restore (disaster recovery) into a scratch database:
```bash
createdb orthopro_restore
openssl enc -d -aes-256-cbc -pbkdf2 -in backups/orthopro-<stamp>.sql.gz.enc \
  | gunzip | pql postgresql://orthopro_app:<pw>@host:5432/orthopro_restore
```
(Then verify row counts before pointing the app at it.)

**Policy:** daily backups, 14-day retention (configurable), AES-256 encryption at
rest, and a scheduled restore test. See SECURITY.md §9.

## 7. Notes
- SQLite `data.db` is retained as the migration source and is git-ignored. After a
  successful migration and verification it can be archived offline; it is never
  deleted by any script.
