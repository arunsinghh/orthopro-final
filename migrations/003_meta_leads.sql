-- OrthoPro India — Meta leads & staff schema (v3)
-- Idempotent + additive. Extends leads with Meta attribution + idempotency.

-- ---- Meta / platform attribution on leads ----
ALTER TABLE leads ADD COLUMN IF NOT EXISTS platform TEXT NOT NULL DEFAULT '';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS meta_lead_id TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS form_id TEXT NOT NULL DEFAULT '';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS campaign_id TEXT NOT NULL DEFAULT '';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS adset_id TEXT NOT NULL DEFAULT '';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS ad_id TEXT NOT NULL DEFAULT '';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS lead_fields TEXT NOT NULL DEFAULT '';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS raw_event TEXT NOT NULL DEFAULT '';

-- Idempotency: the same Meta leadgen id must never create twice.
CREATE UNIQUE INDEX IF NOT EXISTS ux_leads_meta_lead_id
    ON leads(meta_lead_id) WHERE meta_lead_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_leads_platform ON leads(platform);

-- followups: keep the original due date when rescheduling (Part: history).
ALTER TABLE followups ADD COLUMN IF NOT EXISTS original_due_date DATE;
