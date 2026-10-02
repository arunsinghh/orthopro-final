#!/usr/bin/env python3
"""Idempotent backfill for migration 002 reference data.

Safe to run any number of times (e.g. after a sandbox refresh):
  * assigns OP-xxxxxx codes to patients that have none
  * inserts the 12 lead sources if missing
  * creates the "Prosthetic Initial Fitting" follow-up template if missing
  * sets users.role='super_admin' where NULL/empty

Never touches existing values.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db  # noqa: E402
from app.config import get_config  # noqa: E402


def _init():
    cfg = get_config()

    class _App:
        config = {"DATABASE_URL": cfg.DATABASE_URL, "DB_POOL_SIZE": 2, "DB_MAX_OVERFLOW": 2}
        extensions = {}

    db.init_app(_App())


SOURCES = ["Website", "WhatsApp", "Instagram", "Facebook", "Google", "Phone Call",
           "Walk-in", "Doctor Referral", "Existing Patient Referral", "Known Person",
           "Home Visit", "Other"]

FITTING_STEPS = [(7, "First check — socket comfort and skin"),
                 (30, "One month review — gait and alignment"),
                 (90, "Three month review — volume and fit"),
                 (180, "Six month review — component check"),
                 (365, "Annual review — full device check")]
# (offset_days, followup_type, purpose)


def main():
    _init()
    # 1) patient codes
    rows = db.q("SELECT id FROM patients WHERE patient_code IS NULL OR patient_code='' "
                "ORDER BY id")
    for i, r in enumerate(rows):
        n = db.q("SELECT COALESCE(MAX(CAST(SUBSTRING(patient_code FROM 4) AS INTEGER)),0)+1 "
                 "AS n FROM patients WHERE patient_code IS NOT NULL", one=True)["n"]
        db.q("UPDATE patients SET patient_code=? WHERE id=?", (f"OP-{n:06d}", r["id"]))
    print(f"[backfill] patient codes assigned: {len(rows)}")

    # 2) sources
    for s in SOURCES:
        db.q("INSERT INTO sources (name) SELECT ? WHERE NOT EXISTS "
             "(SELECT 1 FROM sources WHERE name=?)", (s, s))
    print(f"[backfill] sources present: {db.q('SELECT COUNT(*) c FROM sources', one=True)['c']}")

    # 3) fitting template
    t = db.q("SELECT id FROM followup_templates WHERE name='Prosthetic Initial Fitting'",
             one=True)
    if not t:
        t = db.q("INSERT INTO followup_templates (name, service_type) "
                 "VALUES ('Prosthetic Initial Fitting', 'Prosthetic fitting') "
                 "RETURNING id")[0]
        for i, (days, desc) in enumerate(FITTING_STEPS, start=1):
            db.q("INSERT INTO followup_template_steps (template_id, step_order, offset_days, "
                 "followup_type, purpose) VALUES (?,?,?,?,?)",
                 (t["id"], i, days, "Routine Check", desc))
        print("[backfill] fitting template created")
    else:
        print("[backfill] fitting template already present")

    # 4) roles
    missing = db.q("SELECT COUNT(*) c FROM users WHERE role IS NULL OR role=''")
    db.q("UPDATE users SET role='super_admin' WHERE role IS NULL OR role=''")
    print(f"[backfill] roles defaulted: {missing[0]['c'] if missing else 0}")


    # 5) serial numbers (YYMM + running no.) for patients that have none
    from datetime import date as _date
    todo = db.q("SELECT id, created_at FROM patients WHERE serial_no IS NULL OR serial_no='' "
                "ORDER BY created_at, id")
    for r in todo:
        ts = r["created_at"] or ""
        try:
            d = _date.fromisoformat(str(ts)[:10])
        except (ValueError, TypeError):
            d = _date.today()
        yymm = f"{d.year % 100:02d}{d.month:02d}"
        n = db.q("SELECT COALESCE(MAX(CAST(SUBSTRING(serial_no FROM 5) AS INTEGER)),0)+1 AS n "
                 "FROM patients WHERE serial_no LIKE ?", (yymm + "%",), one=True)["n"]
        db.q("UPDATE patients SET serial_no=? WHERE id=?", (f"{yymm}{n}", r["id"]))
    print(f"[backfill] serial numbers assigned: {len(todo)}")


if __name__ == "__main__":
    main()
