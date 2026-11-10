-- OrthoPro: Clean reset of leads and patients data only.
-- Preserves users (admin/staff logins), products, product images, journeys, stories, media, settings.

TRUNCATE TABLE lead_history, followups, appointments, patient_stage_log, leads, patients RESTART IDENTITY CASCADE;
