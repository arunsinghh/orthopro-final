-- OrthoPro India — Leads Editable & WhatsApp-style Chat History (v9)
-- Non-destructive, idempotent, additive migration.

-- 1. Patients: flag for confirmed patient vs unconfirmed lead
ALTER TABLE patients ADD COLUMN IF NOT EXISTS is_confirmed SMALLINT NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_patients_confirmed ON patients(is_confirmed);

-- 2. Leads: editable details directly on the lead record
ALTER TABLE leads ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT '';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS phone TEXT NOT NULL DEFAULT '';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS whatsapp TEXT NOT NULL DEFAULT '';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS email TEXT NOT NULL DEFAULT '';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS area TEXT NOT NULL DEFAULT '';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS next_followup DATE;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS converted_by BIGINT REFERENCES users(id) ON DELETE SET NULL;

-- Ensure leads_status_chk includes 'converted'
ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_status_chk;
ALTER TABLE leads ADD CONSTRAINT leads_status_chk CHECK (status IN (
    'new_enquiry','contacted','interested','appointment_scheduled','first_visit',
    'assessment','treatment_ongoing','active_patient','completed','inactive',
    'not_interested','lost',
    'new','appointment','followup','hold','converted'));

-- 3. Lead History: WhatsApp-style conversation & interaction tracking
ALTER TABLE lead_history ADD COLUMN IF NOT EXISTS interaction_type TEXT NOT NULL DEFAULT 'call';
ALTER TABLE lead_history ADD COLUMN IF NOT EXISTS summary TEXT NOT NULL DEFAULT '';
ALTER TABLE lead_history ADD COLUMN IF NOT EXISTS logged_by BIGINT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE lead_history ADD COLUMN IF NOT EXISTS followup_id BIGINT REFERENCES followups(id) ON DELETE SET NULL;
ALTER TABLE lead_history ADD COLUMN IF NOT EXISTS interaction_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_lh_logged_by ON lead_history(logged_by);
CREATE INDEX IF NOT EXISTS idx_lh_interaction_at ON lead_history(interaction_at);

-- 4. Followups: link directly to lead
ALTER TABLE followups ADD COLUMN IF NOT EXISTS lead_id BIGINT REFERENCES leads(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_followups_lead ON followups(lead_id);

-- 5. Backfill existing leads from linked patients if empty
UPDATE leads l
SET name = COALESCE(NULLIF(l.name, ''), p.name, ''),
    phone = COALESCE(NULLIF(l.phone, ''), p.phone, ''),
    whatsapp = COALESCE(NULLIF(l.whatsapp, ''), p.whatsapp, ''),
    email = COALESCE(NULLIF(l.email, ''), p.email, ''),
    area = COALESCE(NULLIF(l.area, ''), p.area, '')
FROM patients p
WHERE l.patient_id = p.id;

