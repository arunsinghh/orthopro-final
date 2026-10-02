-- ============================================================ 006 — review source tag
-- Marks where a published review came from (e.g. 'google'), additive only.
ALTER TABLE testimonials ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT '';
