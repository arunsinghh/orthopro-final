-- ============================================================ 004 — Simple CRM
-- One pipeline per patient (re-opened on repeat visits), YYMM serial numbers,
-- lead outcomes (appointment / followup / hold / lost). Additive only.

-- ---- patient serial number: 26091 = 2026 September patient #1 (no padding)
ALTER TABLE patients ADD COLUMN IF NOT EXISTS serial_no VARCHAR(12);
ALTER TABLE patients DROP CONSTRAINT IF EXISTS patients_serial_ux;
ALTER TABLE patients ADD CONSTRAINT patients_serial_ux UNIQUE (serial_no);
CREATE INDEX IF NOT EXISTS idx_patients_serial ON patients(serial_no);

-- ---- pipeline (one per patient, re-openable, history in patient_stage_log)
ALTER TABLE patients ADD COLUMN IF NOT EXISTS pipeline_stage TEXT NOT NULL DEFAULT '';
ALTER TABLE patients ADD COLUMN IF NOT EXISTS stage_updated_at TIMESTAMPTZ;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS total_amount NUMERIC(12,2) NOT NULL DEFAULT 0;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS advance_amount NUMERIC(12,2) NOT NULL DEFAULT 0;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS completed_cycles INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS patient_stage_log (
    id         BIGSERIAL PRIMARY KEY,
    patient_id BIGINT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    stage      TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_psl_patient ON patient_stage_log(patient_id);

-- ---- lead outcome history (the process repeats — history is never lost)
CREATE TABLE IF NOT EXISTS lead_history (
    id         BIGSERIAL PRIMARY KEY,
    lead_id    BIGINT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    outcome    TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    due_date   DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_lh_lead ON lead_history(lead_id);

-- ---- leads gain the 4 simple outcomes (old values stay valid for history)
ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_status_chk;
ALTER TABLE leads ADD CONSTRAINT leads_status_chk CHECK (status IN (
    'new_enquiry','contacted','interested','appointment_scheduled','first_visit',
    'assessment','treatment_ongoing','active_patient','completed','inactive',
    'not_interested','lost',
    'new','appointment','followup','hold'));

-- ---- followups: allow simple general entries without legacy type values
ALTER TABLE followups DROP CONSTRAINT IF EXISTS followups_status_chk;
ALTER TABLE followups ADD CONSTRAINT followups_status_chk CHECK
    (status IN ('pending','completed','cancelled','rescheduled'));
