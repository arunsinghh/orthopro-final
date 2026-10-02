-- OrthoPro India — Clinical CRM schema (v2)
-- Idempotent + additive: extends the live schema without touching existing rows.
-- Design: CLINICAL_CRM_PLAN.md — Master Patient hub (patients table), all modules
-- FK to patients.id. History-preserving: append-only event tables, reschedule
-- chains, assignment_log, audit_log entity refs.

-- ============================================================ users & roles
ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS role      TEXT NOT NULL DEFAULT 'super_admin';
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone     TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active SMALLINT NOT NULL DEFAULT 1;
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_chk;
ALTER TABLE users ADD CONSTRAINT users_role_chk CHECK
    (role IN ('super_admin','receptionist','prosthetist','physiotherapist'));

-- ============================================================ sources lookup
CREATE TABLE IF NOT EXISTS sources (
    id         BIGSERIAL PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    is_active  SMALLINT NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0
);

-- ============================================================ master patient
-- patients = Master Patient Record. Additive columns only.
ALTER TABLE patients ADD COLUMN IF NOT EXISTS patient_code VARCHAR(12);
ALTER TABLE patients ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT '';
ALTER TABLE patients ADD COLUMN IF NOT EXISTS dob DATE;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS whatsapp TEXT;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS address TEXT NOT NULL DEFAULT '';
ALTER TABLE patients ADD COLUMN IF NOT EXISTS city TEXT NOT NULL DEFAULT '';
ALTER TABLE patients ADD COLUMN IF NOT EXISTS emergency_contact TEXT NOT NULL DEFAULT '';
ALTER TABLE patients ADD COLUMN IF NOT EXISTS photo TEXT NOT NULL DEFAULT '';
ALTER TABLE patients ADD COLUMN IF NOT EXISTS referring_doctor TEXT NOT NULL DEFAULT '';
-- clinical core (Part 7): free-text clinical block lives here. Structured data
-- lives in episodes/devices/measurements so no patient gets irrelevant fields.
ALTER TABLE patients ADD COLUMN IF NOT EXISTS primary_condition TEXT NOT NULL DEFAULT '';
ALTER TABLE patients ADD COLUMN IF NOT EXISTS diagnosis TEXT NOT NULL DEFAULT '';
ALTER TABLE patients ADD COLUMN IF NOT EXISTS amputation_level TEXT NOT NULL DEFAULT '';
ALTER TABLE patients ADD COLUMN IF NOT EXISTS amputation_side TEXT NOT NULL DEFAULT '';
ALTER TABLE patients ADD COLUMN IF NOT EXISTS amputation_date DATE;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS amputation_cause TEXT NOT NULL DEFAULT '';
ALTER TABLE patients ADD COLUMN IF NOT EXISTS medical_history TEXT NOT NULL DEFAULT '';
ALTER TABLE patients ADD COLUMN IF NOT EXISTS current_problems TEXT NOT NULL DEFAULT '';
ALTER TABLE patients ADD COLUMN IF NOT EXISTS prescription TEXT NOT NULL DEFAULT '';
-- consent (Part 61)
ALTER TABLE patients ADD COLUMN IF NOT EXISTS consent_records SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS consent_photos SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS consent_videos SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS consent_public_story SMALLINT NOT NULL DEFAULT 0;
-- profile completeness (Part 2)
ALTER TABLE patients ADD COLUMN IF NOT EXISTS profile_status TEXT NOT NULL DEFAULT 'incomplete';
ALTER TABLE patients DROP CONSTRAINT IF EXISTS patients_profile_chk;
ALTER TABLE patients ADD CONSTRAINT patients_profile_chk CHECK
    (profile_status IN ('incomplete','complete'));
ALTER TABLE patients DROP CONSTRAINT IF EXISTS patients_code_ux;
ALTER TABLE patients ADD CONSTRAINT patients_code_ux UNIQUE (patient_code);
CREATE INDEX IF NOT EXISTS idx_patients_whatsapp ON patients(whatsapp);
CREATE INDEX IF NOT EXISTS idx_patients_source  ON patients(source);

-- ============================================================ leads / enquiries
CREATE TABLE IF NOT EXISTS leads (
    id           BIGSERIAL PRIMARY KEY,
    patient_id   BIGINT REFERENCES patients(id) ON DELETE SET NULL,
    source       TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'new_enquiry',
    interest     TEXT NOT NULL DEFAULT '',
    notes        TEXT NOT NULL DEFAULT '',
    assigned_to  BIGINT REFERENCES users(id) ON DELETE SET NULL,
    contacted_at TIMESTAMPTZ,
    converted_at TIMESTAMPTZ,
    lost_reason  TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT leads_status_chk CHECK (status IN (
        'new_enquiry','contacted','interested','appointment_scheduled','first_visit',
        'assessment','treatment_ongoing','active_patient','completed','inactive',
        'not_interested','lost'))
);
CREATE INDEX IF NOT EXISTS idx_leads_status   ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_assigned ON leads(assigned_to);
CREATE INDEX IF NOT EXISTS idx_leads_patient  ON leads(patient_id);
CREATE INDEX IF NOT EXISTS idx_leads_created  ON leads(created_at);

-- ============================================================ appointments (extended)
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS patient_id BIGINT REFERENCES patients(id) ON DELETE SET NULL;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS assigned_to BIGINT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS appt_time TIME;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS visit_type TEXT NOT NULL DEFAULT '';
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS rescheduled_from BIGINT REFERENCES appointments(id) ON DELETE SET NULL;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS reschedule_reason TEXT NOT NULL DEFAULT '';
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE appointments DROP CONSTRAINT IF EXISTS appts_status_chk;
ALTER TABLE appointments ADD CONSTRAINT appts_status_chk CHECK (status IN (
    'new','requested','confirmed','arrived','in_consultation','completed',
    'cancelled','no_show','rescheduled'));
CREATE INDEX IF NOT EXISTS idx_appts_patient  ON appointments(patient_id);
CREATE INDEX IF NOT EXISTS idx_appts_date     ON appointments(preferred_date);
CREATE INDEX IF NOT EXISTS idx_appts_assigned ON appointments(assigned_to);

-- ============================================================ treatment episodes & timeline
CREATE TABLE IF NOT EXISTS treatment_episodes (
    id                  BIGSERIAL PRIMARY KEY,
    patient_id          BIGINT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    episode_num         INTEGER NOT NULL DEFAULT 1,
    treatment_type      TEXT NOT NULL DEFAULT '',
    description         TEXT NOT NULL DEFAULT '',
    start_date          DATE,
    expected_completion DATE,
    completed_date      DATE,
    status              TEXT NOT NULL DEFAULT 'planned',
    assigned_to         BIGINT REFERENCES users(id) ON DELETE SET NULL,
    notes               TEXT NOT NULL DEFAULT '',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT episodes_status_chk CHECK (status IN ('planned','ongoing','completed','cancelled'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_episode_patient_num ON treatment_episodes(patient_id, episode_num);
CREATE INDEX IF NOT EXISTS idx_episodes_patient ON treatment_episodes(patient_id);
CREATE INDEX IF NOT EXISTS idx_episodes_status  ON treatment_episodes(status);

-- Append-only clinical timeline (Part 8). Never updated, never overwritten.
CREATE TABLE IF NOT EXISTS treatment_events (
    id          BIGSERIAL PRIMARY KEY,
    patient_id  BIGINT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    episode_id  BIGINT REFERENCES treatment_episodes(id) ON DELETE SET NULL,
    event_date  DATE NOT NULL,
    event_type  TEXT NOT NULL DEFAULT '',
    summary     TEXT NOT NULL DEFAULT '',
    notes       TEXT NOT NULL DEFAULT '',
    recorded_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tevents_patient ON treatment_events(patient_id);
CREATE INDEX IF NOT EXISTS idx_tevents_date    ON treatment_events(event_date);

-- ============================================================ devices & components
CREATE TABLE IF NOT EXISTS devices (
    id              BIGSERIAL PRIMARY KEY,
    device_code     VARCHAR(16),
    patient_id      BIGINT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    episode_id      BIGINT REFERENCES treatment_episodes(id) ON DELETE SET NULL,
    device_type     TEXT NOT NULL DEFAULT '',
    name            TEXT NOT NULL,
    side            TEXT NOT NULL DEFAULT '',
    manufacturer    TEXT NOT NULL DEFAULT '',
    model           TEXT NOT NULL DEFAULT '',
    serial_number   TEXT NOT NULL DEFAULT '',
    supplied_date   DATE,
    warranty_start  DATE,
    warranty_end    DATE,
    replacement_due DATE,
    status          TEXT NOT NULL DEFAULT 'planned',
    notes           TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT devices_code_ux UNIQUE (device_code),
    CONSTRAINT devices_side_chk CHECK (side IN ('','left','right','bilateral')),
    CONSTRAINT devices_status_chk CHECK (status IN (
        'planned','in_production','delivered','active','under_repair','replaced',
        'retired','lost'))
);
CREATE INDEX IF NOT EXISTS idx_devices_patient  ON devices(patient_id);
CREATE INDEX IF NOT EXISTS idx_devices_status   ON devices(status);
CREATE INDEX IF NOT EXISTS idx_devices_warranty ON devices(warranty_end);
CREATE INDEX IF NOT EXISTS idx_devices_replace  ON devices(replacement_due);

CREATE TABLE IF NOT EXISTS device_components (
    id             BIGSERIAL PRIMARY KEY,
    device_id      BIGINT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    component_type TEXT NOT NULL,
    manufacturer   TEXT NOT NULL DEFAULT '',
    model          TEXT NOT NULL DEFAULT '',
    serial_number  TEXT NOT NULL DEFAULT '',
    installed_date DATE,
    warranty_end   DATE,
    replaced_date  DATE,
    notes          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_components_device ON device_components(device_id);

CREATE TABLE IF NOT EXISTS device_history (
    id          BIGSERIAL PRIMARY KEY,
    device_id   BIGINT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    event_date  DATE NOT NULL DEFAULT CURRENT_DATE,
    event_type  TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    user_id     BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_devhist_device ON device_history(device_id);

-- ============================================================ measurements (structured)
CREATE TABLE IF NOT EXISTS measurements (
    id           BIGSERIAL PRIMARY KEY,
    patient_id   BIGINT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    episode_id   BIGINT REFERENCES treatment_episodes(id) ON DELETE SET NULL,
    device_id    BIGINT REFERENCES devices(id) ON DELETE SET NULL,
    service_type TEXT NOT NULL DEFAULT '',
    taken_date   DATE NOT NULL DEFAULT CURRENT_DATE,
    taken_by     BIGINT REFERENCES users(id) ON DELETE SET NULL,
    notes        TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_measure_patient ON measurements(patient_id);

CREATE TABLE IF NOT EXISTS measurement_values (
    id             BIGSERIAL PRIMARY KEY,
    measurement_id BIGINT NOT NULL REFERENCES measurements(id) ON DELETE CASCADE,
    field_key      TEXT NOT NULL,
    field_label    TEXT NOT NULL DEFAULT '',
    value          TEXT NOT NULL DEFAULT '',
    unit           TEXT NOT NULL DEFAULT '',
    sort_order     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_mvals_measurement ON measurement_values(measurement_id);

-- ============================================================ follow-ups (extended)
ALTER TABLE followups ADD COLUMN IF NOT EXISTS assigned_to BIGINT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE followups ADD COLUMN IF NOT EXISTS treatment_id BIGINT REFERENCES treatment_episodes(id) ON DELETE SET NULL;
ALTER TABLE followups ADD COLUMN IF NOT EXISTS device_id BIGINT REFERENCES devices(id) ON DELETE SET NULL;
ALTER TABLE followups ADD COLUMN IF NOT EXISTS followup_type TEXT NOT NULL DEFAULT 'general';
ALTER TABLE followups ADD COLUMN IF NOT EXISTS purpose TEXT NOT NULL DEFAULT '';
ALTER TABLE followups ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'normal';
ALTER TABLE followups ADD COLUMN IF NOT EXISTS visit_date DATE;
ALTER TABLE followups ADD COLUMN IF NOT EXISTS outcome TEXT NOT NULL DEFAULT '';
ALTER TABLE followups ADD COLUMN IF NOT EXISTS completed_by BIGINT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE followups ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE followups ADD COLUMN IF NOT EXISTS next_visit_date DATE;
ALTER TABLE followups ADD COLUMN IF NOT EXISTS next_visit_type TEXT NOT NULL DEFAULT '';
ALTER TABLE followups DROP CONSTRAINT IF EXISTS followups_status_chk;
ALTER TABLE followups ADD CONSTRAINT followups_status_chk CHECK
    (status IN ('pending','completed','cancelled','rescheduled'));
ALTER TABLE followups DROP CONSTRAINT IF EXISTS followups_priority_chk;
ALTER TABLE followups ADD CONSTRAINT followups_priority_chk CHECK
    (priority IN ('low','normal','high','urgent'));
CREATE INDEX IF NOT EXISTS idx_followups_assigned ON followups(assigned_to);
CREATE INDEX IF NOT EXISTS idx_followups_treatment ON followups(treatment_id);

-- Follow-up templates (Part 17)
CREATE TABLE IF NOT EXISTS followup_templates (
    id           BIGSERIAL PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    service_type TEXT NOT NULL DEFAULT '',
    is_active    SMALLINT NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS followup_template_steps (
    id            BIGSERIAL PRIMARY KEY,
    template_id   BIGINT NOT NULL REFERENCES followup_templates(id) ON DELETE CASCADE,
    step_order    INTEGER NOT NULL,
    offset_days   INTEGER NOT NULL DEFAULT 0,
    followup_type TEXT NOT NULL DEFAULT '',
    purpose       TEXT NOT NULL DEFAULT '',
    priority      TEXT NOT NULL DEFAULT 'normal'
);
CREATE INDEX IF NOT EXISTS idx_ftsteps_template ON followup_template_steps(template_id);

-- ============================================================ repairs & warranty
CREATE TABLE IF NOT EXISTS repairs (
    id                  BIGSERIAL PRIMARY KEY,
    repair_code         VARCHAR(16),
    patient_id          BIGINT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    device_id           BIGINT REFERENCES devices(id) ON DELETE SET NULL,
    problem             TEXT NOT NULL,
    received_date       DATE NOT NULL DEFAULT CURRENT_DATE,
    expected_completion DATE,
    completed_date      DATE,
    status              TEXT NOT NULL DEFAULT 'received',
    cost_estimate       NUMERIC(12,2) NOT NULL DEFAULT 0,
    cost_final          NUMERIC(12,2) NOT NULL DEFAULT 0,
    payment_status      TEXT NOT NULL DEFAULT 'pending',
    assigned_to         BIGINT REFERENCES users(id) ON DELETE SET NULL,
    notes               TEXT NOT NULL DEFAULT '',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT repairs_code_ux UNIQUE (repair_code),
    CONSTRAINT repairs_status_chk CHECK (status IN (
        'received','inspection','estimate','awaiting_approval','under_repair',
        'ready','delivered','cancelled')),
    CONSTRAINT repairs_pay_chk CHECK (payment_status IN ('pending','partial','paid','waived'))
);
CREATE INDEX IF NOT EXISTS idx_repairs_patient ON repairs(patient_id);
CREATE INDEX IF NOT EXISTS idx_repairs_status  ON repairs(status);
CREATE INDEX IF NOT EXISTS idx_repairs_device  ON repairs(device_id);

-- ============================================================ billing
CREATE TABLE IF NOT EXISTS invoices (
    id         BIGSERIAL PRIMARY KEY,
    invoice_no VARCHAR(20),
    patient_id BIGINT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    episode_id BIGINT REFERENCES treatment_episodes(id) ON DELETE SET NULL,
    kind       TEXT NOT NULL DEFAULT 'invoice',
    issue_date DATE NOT NULL DEFAULT CURRENT_DATE,
    status     TEXT NOT NULL DEFAULT 'draft',
    subtotal   NUMERIC(12,2) NOT NULL DEFAULT 0,
    discount   NUMERIC(12,2) NOT NULL DEFAULT 0,
    total      NUMERIC(12,2) NOT NULL DEFAULT 0,
    notes      TEXT NOT NULL DEFAULT '',
    created_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT invoices_no_ux UNIQUE (invoice_no),
    CONSTRAINT invoices_kind_chk CHECK (kind IN ('quotation','invoice')),
    CONSTRAINT invoices_status_chk CHECK (status IN ('draft','sent','partial','paid','cancelled')),
    CONSTRAINT invoices_amounts_chk CHECK (subtotal >= 0 AND discount >= 0 AND total >= 0)
);
CREATE INDEX IF NOT EXISTS idx_invoices_patient ON invoices(patient_id);

CREATE TABLE IF NOT EXISTS payments (
    id          BIGSERIAL PRIMARY KEY,
    patient_id  BIGINT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    invoice_id  BIGINT REFERENCES invoices(id) ON DELETE SET NULL,
    episode_id  BIGINT REFERENCES treatment_episodes(id) ON DELETE SET NULL,
    kind        TEXT NOT NULL DEFAULT 'payment',
    amount      NUMERIC(12,2) NOT NULL,
    method      TEXT NOT NULL DEFAULT 'cash',
    reference   TEXT NOT NULL DEFAULT '',
    paid_date   DATE NOT NULL DEFAULT CURRENT_DATE,
    recorded_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT payments_kind_chk CHECK (kind IN ('payment','advance','refund')),
    CONSTRAINT payments_amount_chk CHECK (amount >= 0),
    CONSTRAINT payments_method_chk CHECK (method IN
        ('cash','upi','card','bank_transfer','cheque','other'))
);
CREATE INDEX IF NOT EXISTS idx_payments_patient ON payments(patient_id);
CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);
CREATE INDEX IF NOT EXISTS idx_payments_date    ON payments(paid_date);

-- ============================================================ documents & patient media
CREATE TABLE IF NOT EXISTS documents (
    id          BIGSERIAL PRIMARY KEY,
    patient_id  BIGINT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    media_id    BIGINT REFERENCES media(id) ON DELETE SET NULL,
    doc_type    TEXT NOT NULL DEFAULT 'other',
    title       TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    episode_id  BIGINT REFERENCES treatment_episodes(id) ON DELETE SET NULL,
    device_id   BIGINT REFERENCES devices(id) ON DELETE SET NULL,
    uploaded_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_docs_patient ON documents(patient_id);

-- media gains scope separation (Part 33): 'public' website media vs 'patient'
-- private clinical media. Patient media is always served auth-gated.
ALTER TABLE media ADD COLUMN IF NOT EXISTS scope TEXT NOT NULL DEFAULT 'public';
ALTER TABLE media ADD COLUMN IF NOT EXISTS patient_id BIGINT REFERENCES patients(id) ON DELETE SET NULL;
ALTER TABLE media ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT '';
ALTER TABLE media DROP CONSTRAINT IF EXISTS media_scope_chk;
ALTER TABLE media ADD CONSTRAINT media_scope_chk CHECK (scope IN ('public','patient'));
CREATE INDEX IF NOT EXISTS idx_media_scope   ON media(scope);
CREATE INDEX IF NOT EXISTS idx_media_patient ON media(patient_id);

-- ============================================================ communications
CREATE TABLE IF NOT EXISTS communications (
    id         BIGSERIAL PRIMARY KEY,
    patient_id BIGINT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    comm_type  TEXT NOT NULL,
    direction  TEXT NOT NULL DEFAULT 'out',
    summary    TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    logged_by  BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT comms_type_chk CHECK (comm_type IN ('call','whatsapp','sms','email','note')),
    CONSTRAINT comms_dir_chk CHECK (direction IN ('in','out'))
);
CREATE INDEX IF NOT EXISTS idx_comms_patient ON communications(patient_id);

-- ============================================================ cross-cutting
-- Visible assignment history (Part 23) — never silently change ownership.
CREATE TABLE IF NOT EXISTS assignment_log (
    id           BIGSERIAL PRIMARY KEY,
    entity_type  TEXT NOT NULL,
    entity_id    BIGINT NOT NULL,
    from_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    to_user_id   BIGINT REFERENCES users(id) ON DELETE SET NULL,
    reason       TEXT NOT NULL DEFAULT '',
    changed_by   BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT asg_entity_chk CHECK (entity_type IN
        ('lead','followup','appointment','treatment','repair','device'))
);
CREATE INDEX IF NOT EXISTS idx_asglog_entity ON assignment_log(entity_type, entity_id);

-- Notifications (Part 62) — dedup_key makes generation idempotent.
CREATE TABLE IF NOT EXISTS notifications (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT REFERENCES users(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id   BIGINT,
    message     TEXT NOT NULL DEFAULT '',
    dedup_key   TEXT UNIQUE,
    is_read     SMALLINT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, is_read);

-- audit_log gains structured entity references (additive; old rows keep working)
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS entity_type TEXT NOT NULL DEFAULT '';
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS entity_id BIGINT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS user_id BIGINT;

-- Public journeys may link to a patient ONLY with explicit consent (Part 60)
ALTER TABLE journeys ADD COLUMN IF NOT EXISTS patient_id BIGINT REFERENCES patients(id) ON DELETE SET NULL;
ALTER TABLE journeys ADD COLUMN IF NOT EXISTS consent_public SMALLINT NOT NULL DEFAULT 0;
