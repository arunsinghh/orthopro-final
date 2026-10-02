-- OrthoPro India — PostgreSQL schema (v1)
-- Idempotent: uses IF NOT EXISTS so it never destroys existing data.

CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS services (
    id          BIGSERIAL PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    short       TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL DEFAULT '',
    icon        TEXT NOT NULL DEFAULT '',
    meta_desc   TEXT NOT NULL DEFAULT '',
    keywords    TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    who_for     TEXT NOT NULL DEFAULT '',
    process     TEXT NOT NULL DEFAULT '',
    sort        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT '',
    brand       TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    price_min   NUMERIC(12,2) NOT NULL DEFAULT 0,
    price_max   NUMERIC(12,2) NOT NULL DEFAULT 0,
    image       TEXT NOT NULL DEFAULT '',
    featured    SMALLINT NOT NULL DEFAULT 0,
    service     TEXT NOT NULL DEFAULT '',
    sort        INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT products_price_order CHECK (price_max >= price_min)
);

CREATE TABLE IF NOT EXISTS journeys (
    id           BIGSERIAL PRIMARY KEY,
    title        TEXT NOT NULL,
    patient_name TEXT NOT NULL DEFAULT '',
    area         TEXT NOT NULL DEFAULT '',
    service      TEXT NOT NULL DEFAULT '',
    story        TEXT NOT NULL DEFAULT '',
    before_image TEXT NOT NULL DEFAULT '',
    after_image  TEXT NOT NULL DEFAULT '',
    video        TEXT NOT NULL DEFAULT '',
    featured     SMALLINT NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS patients (
    id            BIGSERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    age           TEXT,
    gender        TEXT,
    phone         TEXT,
    email         TEXT,
    area          TEXT,
    service       TEXT,
    product       TEXT,
    status        TEXT NOT NULL DEFAULT 'active',
    notes         TEXT,
    next_followup DATE,
    created_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS appointments (
    id             BIGSERIAL PRIMARY KEY,
    name           TEXT NOT NULL,
    phone          TEXT NOT NULL,
    email          TEXT,
    area           TEXT,
    service        TEXT,
    preferred_date DATE,
    message        TEXT,
    status         TEXT NOT NULL DEFAULT 'new',
    created_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS followups (
    id         BIGSERIAL PRIMARY KEY,
    patient_id BIGINT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    due_date   DATE NOT NULL,
    note       TEXT,
    status     TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS media (
    id         BIGSERIAL PRIMARY KEY,
    filename   TEXT NOT NULL UNIQUE,
    orig_name  TEXT NOT NULL DEFAULT '',
    kind       TEXT NOT NULL,
    uploaded_at TIMESTAMPTZ,
    is_private SMALLINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS testimonials (
    id       BIGSERIAL PRIMARY KEY,
    name     TEXT NOT NULL,
    rating   SMALLINT NOT NULL DEFAULT 5 CHECK (rating BETWEEN 1 AND 5),
    text     TEXT NOT NULL,
    approved SMALLINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS posts (
    id         BIGSERIAL PRIMARY KEY,
    title      TEXT NOT NULL,
    slug       TEXT NOT NULL UNIQUE,
    excerpt    TEXT,
    body       TEXT,
    image      TEXT,
    keywords   TEXT,
    status     TEXT NOT NULL DEFAULT 'published',
    created_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS audit_log (
    id      BIGSERIAL PRIMARY KEY,
    ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor   TEXT NOT NULL,
    action  TEXT NOT NULL,
    detail  TEXT NOT NULL DEFAULT ''
);

-- ---- Targeted indexes (matched to real query patterns) ----
CREATE INDEX IF NOT EXISTS idx_patients_name     ON patients(name);
CREATE INDEX IF NOT EXISTS idx_patients_phone    ON patients(phone);
CREATE INDEX IF NOT EXISTS idx_patients_area     ON patients(area);
CREATE INDEX IF NOT EXISTS idx_patients_service  ON patients(service);
CREATE INDEX IF NOT EXISTS idx_appointments_status ON appointments(status);
CREATE INDEX IF NOT EXISTS idx_appointments_created ON appointments(created_at);
CREATE INDEX IF NOT EXISTS idx_followups_due     ON followups(due_date);
CREATE INDEX IF NOT EXISTS idx_followups_status  ON followups(status);
CREATE INDEX IF NOT EXISTS idx_followups_patient ON followups(patient_id);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_journeys_featured ON journeys(featured);
CREATE INDEX IF NOT EXISTS idx_audit_action      ON audit_log(action);
