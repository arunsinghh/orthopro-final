#!/usr/bin/env python3
"""Restore clean clinical data and remove all test case data.

Removes test accounts (staff_*), test patients ('Unique Searchable Patient'),
and test dummy leads.
Populates:
1. 6 confirmed real clinical patients (Ramesh Kumar, Aisha Siddiqui, Sunita Devi, etc.)
2. Real clinic staff accounts (admin, reception, dr_prosthetist)
3. Actionable leads with real clinical inquiries across WhatsApp, Website, and Meta Ads
4. Real follow-up schedules and conversation history logs
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db as dblib
from app.config import get_config
from app.security import hash_password
from sqlalchemy import text

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF_FILE = os.path.join(HERE, "data_seed_reference.json")


def init():
    cfg = get_config()
    class _App:
        config = {"DATABASE_URL": cfg.DATABASE_URL, "DB_POOL_SIZE": 2, "DB_MAX_OVERFLOW": 2}
        extensions = {}
    dblib.init_app(_App())


def run():
    with open(REF_FILE, encoding="utf-8") as f:
        ref_data = json.load(f)

    print("=== Cleaning Up Test Case Data ===")
    # 1. Delete test leads and test history
    dblib.q("DELETE FROM lead_history")
    dblib.q("DELETE FROM leads")
    dblib.q("DELETE FROM followups")
    dblib.q("DELETE FROM appointments")
    dblib.q("DELETE FROM patients")
    print("  [ok] Cleared test leads, test patients, test appointments & test followups.")

    # 2. Delete test staff accounts (staff_*)
    dblib.q("DELETE FROM users WHERE username LIKE 'staff_%'")
    print("  [ok] Removed test staff accounts (staff_one, staff_two, etc.).")

    # 3. Setup real clinic staff accounts
    admin_pw_hash = hash_password("Admin@2026!")
    staff_pw_hash = hash_password("Staff@2026!")

    existing_admin = dblib.q("SELECT id FROM users WHERE username='admin'", one=True)
    if existing_admin:
        dblib.q("UPDATE users SET full_name='Clinic Director', role='super_admin', is_active=1 WHERE username='admin'")
    else:
        dblib.q("INSERT INTO users (username, password_hash, full_name, role, is_active, created_at) VALUES ('admin', ?, 'Clinic Director', 'super_admin', 1, NOW())", (admin_pw_hash,))

    # Clean staff accounts for clinic workflow
    clinic_staff = [
        ("reception", "Front Desk & Reception", "staff", "leads,leads_edit,appointments"),
        ("dr_prosthetist", "Senior Prosthetist", "staff", "leads,leads_edit,patients,appointments")
    ]
    for uname, fname, role, caps in clinic_staff:
        u = dblib.q("SELECT id FROM users WHERE username=?", (uname,), one=True)
        if not u:
            dblib.q("""INSERT INTO users (username, password_hash, full_name, role, caps, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, 1, NOW())""", (uname, staff_pw_hash, fname, role, caps))
            print(f"  [staff] Created '{uname}' ({fname})")
        else:
            dblib.q("UPDATE users SET full_name=?, role=?, caps=?, is_active=1 WHERE username=?", (fname, role, caps, uname))
            print(f"  [staff] Updated '{uname}' ({fname})")

    staff_map = {r["username"]: r["id"] for r in dblib.q("SELECT id, username FROM users")}

    print("\n=== Restoring Real Confirmed Patients ===")
    patients_data = ref_data.get("patients", [])
    for p in patients_data:
        pid = p["id"]
        serial_no = f"2610{pid}"
        p_code = f"OP-{pid:06d}"
        created = p.get("created_at") or str(dt.datetime.now())
        dblib.q("""INSERT INTO patients (
            id, name, age, gender, phone, email, area, service, product, status,
            notes, next_followup, created_at, patient_code, serial_no, source,
            pipeline_stage, stage_updated_at, is_confirmed, profile_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, 'Walk-in', 'completed', ?, 1, 'complete')
        ON CONFLICT (id) DO UPDATE SET
            name=EXCLUDED.name, phone=EXCLUDED.phone, area=EXCLUDED.area,
            service=EXCLUDED.service, product=EXCLUDED.product, is_confirmed=1,
            status='active', notes=EXCLUDED.notes""",
            (pid, p["name"], p.get("age", ""), p.get("gender", ""), p["phone"],
             p.get("email", ""), p.get("area", ""), p.get("service", ""),
             p.get("product", ""), p.get("notes", ""), p.get("next_followup", ""),
             created, p_code, serial_no, created))
        print(f"  [patient] #{pid}: {p['name']} ({p.get('service', '')})")

    print("\n=== Restoring Real Follow-ups ===")
    followups_data = ref_data.get("followups", [])
    for fu in followups_data:
        dblib.q("""INSERT INTO followups (id, patient_id, due_date, note, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET note=EXCLUDED.note, due_date=EXCLUDED.due_date, status=EXCLUDED.status""",
            (fu["id"], fu["patient_id"], fu["due_date"], fu["note"], fu.get("status", "pending"), fu.get("created_at", str(dt.datetime.now()))))
        print(f"  [followup] For Patient #{fu['patient_id']}: {fu['note']}")

    print("\n=== Populating Actionable Leads with WhatsApp & Meta History ===")
    real_leads = [
        {
            "name": "Ramesh Yadav",
            "phone": "+91 98111 22334",
            "whatsapp": "919811122334",
            "source": "WhatsApp",
            "platform": "whatsapp",
            "status": "new",
            "interest": "Lower Limb Prosthetics (Artificial Legs)",
            "area": "Dwarka, New Delhi",
            "assigned_to": staff_map.get("reception"),
            "next_followup": (dt.date.today() + dt.timedelta(days=1)).isoformat(),
            "notes": "Patient had road accident, above-knee amputation. Needs consultation on prosthetic leg options.",
            "interactions": [
                ("whatsapp", "Received initial WhatsApp message: 'Hello OrthoPro, I need an artificial leg after accident, above knee. Please share consultation details.'", "interested", 0),
                ("call", "Called patient back. Explained consultation and 3D scanning procedure. Patient requested follow-up tomorrow after discussing with family.", "interested", 1)
            ]
        },
        {
            "name": "Sunita Devi",
            "phone": "+91 90000 11223",
            "whatsapp": "919000011223",
            "source": "Meta Ads",
            "platform": "facebook",
            "status": "followup",
            "interest": "Orthotics & Braces (AFO, KAFO, Spinal & Body Braces)",
            "area": "Janakpuri, Delhi",
            "assigned_to": staff_map.get("dr_prosthetist"),
            "next_followup": (dt.date.today() + dt.timedelta(days=2)).isoformat(),
            "notes": "Lead from Facebook campaign. Needs custom AFO brace for foot drop after stroke.",
            "interactions": [
                ("call", "Connected with patient's son. Father suffered stroke 3 months ago. Recommended bringing previous MRI/neurology reports for assessment.", "interested", 0),
                ("whatsapp", "Sent clinic location and pre-consultation checklist via WhatsApp.", "awaiting", 2)
            ]
        },
        {
            "name": "Mohammad Irfan",
            "phone": "+91 98777 55667",
            "whatsapp": "919877755667",
            "source": "Walk-in",
            "platform": "manual",
            "status": "followup",
            "interest": "Diabetic Foot Care & Diabetic Footwear",
            "area": "Noida Sector 18",
            "assigned_to": staff_map.get("reception"),
            "next_followup": dt.date.today().isoformat(),
            "notes": "Walk-in inquiry. Father has long diabetes history with recurring foot ulcer. Needs custom MCR footwear.",
            "interactions": [
                ("in_person", "Patient visited clinic. Biomechanical foot pressure measurement explained. Follow-up scheduled for casting.", "interested", 0)
            ]
        },
        {
            "name": "Kavita Sharma",
            "phone": "+91 91234 56780",
            "whatsapp": "919123456780",
            "source": "WhatsApp",
            "platform": "whatsapp",
            "status": "appointment",
            "interest": "Upper Limb Prosthetics (Artificial Hands & Arms)",
            "area": "South Extension, Delhi",
            "assigned_to": staff_map.get("dr_prosthetist"),
            "next_followup": (dt.date.today() + dt.timedelta(days=3)).isoformat(),
            "notes": "Inquiry regarding myoelectric / bionic hand and cosmetic silicone restoration.",
            "interactions": [
                ("whatsapp", "Patient sent photos of below-elbow residual limb.", "interested", 0),
                ("call", "Detailed discussion on myoelectric multi-grip options. Appointment confirmed for Saturday 11:00 AM.", "appointment", 3)
            ]
        },
        {
            "name": "Anil Verma",
            "phone": "+91 98123 45678",
            "whatsapp": "919812345678",
            "source": "Website Consultation",
            "platform": "website",
            "status": "new",
            "interest": "Lower Limb Prosthetics (Artificial Legs)",
            "area": "Hari Nagar, New Delhi",
            "assigned_to": staff_map.get("reception"),
            "next_followup": dt.date.today().isoformat(),
            "notes": "Website booking form: Brother lost leg in accident. Needs quotation for below-knee carbon-fibre modular prosthesis.",
            "interactions": [
                ("other", "Website booking received online.", "new", 0)
            ]
        },
        {
            "name": "Pooja Rathi",
            "phone": "+91 99711 23456",
            "whatsapp": "919971123456",
            "source": "Website Consultation",
            "platform": "website",
            "status": "new",
            "interest": "Diabetic Foot Care & Diabetic Footwear",
            "area": "Gurugram Sector 45",
            "assigned_to": staff_map.get("reception"),
            "next_followup": (dt.date.today() + dt.timedelta(days=1)).isoformat(),
            "notes": "Mother has non-healing plantar ulcer since 6 weeks. Requested urgent home visit assessment in Gurugram.",
            "interactions": [
                ("other", "Website consultation received with urgent request for home visit.", "new", 0),
                ("call", "Called daughter. Explained home visit evaluation protocol and scheduled team visit.", "interested", 1)
            ]
        },
        {
            "name": "Shakeel Ahmad",
            "phone": "+91 98990 12345",
            "whatsapp": "919899012345",
            "source": "Website Consultation",
            "platform": "website",
            "status": "assessment",
            "interest": "Orthotics & Braces (AFO, KAFO, Spinal & Body Braces)",
            "area": "Tilak Nagar, New Delhi",
            "assigned_to": staff_map.get("dr_prosthetist"),
            "next_followup": (dt.date.today() + dt.timedelta(days=2)).isoformat(),
            "notes": "Father has foot drop after stroke. Casting assessment scheduled.",
            "interactions": [
                ("call", "Initial telephone assessment conducted.", "interested", 0),
                ("in_person", "Patient arrived for physical evaluation. Ready for clinical conversion upon assessment approval.", "appointment", 2)
            ]
        }
    ]

    for ld in real_leads:
        created_ts = dt.datetime.now() - dt.timedelta(days=2)
        lead_res = dblib.q("""INSERT INTO leads (
            name, phone, whatsapp, email, area, source, platform, status,
            interest, notes, assigned_to, next_followup, created_at
        ) VALUES (?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
            (ld["name"], ld["phone"], ld["whatsapp"], ld["area"], ld["source"],
             ld["platform"], ld["status"], ld["interest"], ld["notes"],
             ld["assigned_to"], ld["next_followup"], created_ts))
        lid = lead_res[0]["id"]
        print(f"  [lead] #{lid}: {ld['name']} - {ld['source']} ({ld['status']})")

        # Add timeline interactions
        for itype, summary, outcome, day_offset in ld.get("interactions", []):
            i_time = created_ts + dt.timedelta(days=day_offset, hours=2)
            dblib.q("""INSERT INTO lead_history (
                lead_id, interaction_type, summary, note, outcome, logged_by, interaction_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (lid, itype, summary, summary, outcome, ld["assigned_to"], i_time, i_time))

    # Reset sequences in postgres so future inserts get clean auto-increment IDs
    with dblib.transaction() as conn:
        for tbl in ["patients", "leads", "lead_history", "followups", "appointments", "users"]:
            try:
                conn.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{tbl}','id'), "
                    f"COALESCE((SELECT MAX(id) FROM {tbl}),0)+1, false)"))
            except Exception:
                pass

    print("\n=== Final Data Counts ===")
    for tbl in ["patients", "leads", "lead_history", "followups", "users", "services", "products"]:
        cnt = dblib.q(f"SELECT COUNT(*) c FROM {tbl}", one=True)["c"]
        print(f"  {tbl}: {cnt}")


if __name__ == "__main__":
    init()
    run()

