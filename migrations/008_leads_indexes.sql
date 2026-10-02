-- ============================================================ 008 — Lead query optimizations
CREATE INDEX IF NOT EXISTS idx_leads_interest ON leads(interest);
CREATE INDEX IF NOT EXISTS idx_leads_assigned_status ON leads(assigned_to, status);
CREATE INDEX IF NOT EXISTS idx_lh_lead_id_id ON lead_history(lead_id, id DESC);

