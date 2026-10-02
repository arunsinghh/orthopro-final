-- ============================================================ 007 — Staff accounts & lead assignment
-- users already has role/full_name/is_active (002). Here we:
--  * allow the 'staff' role,
--  * add a per-user capability list (comma separated),
--  * clean up the stray 'active' column from an earlier 007 draft (no data).
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_chk;
ALTER TABLE users ADD CONSTRAINT users_role_chk CHECK
    (role IN ('super_admin','receptionist','prosthetist','physiotherapist','staff'));
ALTER TABLE users ADD COLUMN IF NOT EXISTS caps TEXT NOT NULL DEFAULT '';
ALTER TABLE users DROP COLUMN IF EXISTS active;
UPDATE users SET role='super_admin' WHERE role NOT IN
    ('super_admin','receptionist','prosthetist','physiotherapist','staff');
