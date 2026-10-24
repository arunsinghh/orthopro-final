"""Comprehensive tests for Leads, WhatsApp-Style Conversation History, and Patient Conversion."""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_app import app, client, admin_client, dblib  # noqa: F401,E402
from tests.test_staff import _make_staff


def test_lead_creation_and_separation_from_confirmed_patients(admin_client):
    """Requirement: Manual lead appears in Leads, NOT in Confirmed Master Patient List."""
    # 1. Add lead manually with follow_redirects=True so flash message is consumed on /admin/leads
    rv = admin_client.post("/admin/leads/new", data={
        "name": "Exclusive Lead Prospect",
        "phone": "9811122233",
        "whatsapp": "9811122233",
        "area": "South Extension",
        "interest": "Lower Limb (Leg)",
        "source": "Phone Call",
        "notes": "Patient enquiring about below-knee prosthesis"
    }, follow_redirects=True)
    assert rv.status_code == 200

    # 2. Verify lead is in leads table and unconfirmed
    lead = dblib.q("SELECT * FROM leads WHERE name='Exclusive Lead Prospect'", one=True)
    assert lead is not None
    assert lead["status"] == "new"
    assert lead["source"] == "Phone Call"

    # 3. Verify the linked patient record has is_confirmed=0
    p = dblib.q("SELECT * FROM patients WHERE id=?", (lead["patient_id"],), one=True)
    assert p is not None
    assert p["is_confirmed"] == 0

    # 4. Confirm that unconfirmed lead does NOT appear in Confirmed Master Patient List (/admin/patients)
    res_pts = admin_client.get("/admin/patients")
    assert b"Exclusive Lead Prospect" not in res_pts.data
    assert f'href="/admin/patients/{lead["patient_id"]}"'.encode() not in res_pts.data

    # 5. Verify it DOES appear in Leads view (/admin/leads)
    res_leads = admin_client.get("/admin/leads?view=new")
    assert b"Exclusive Lead Prospect" in res_leads.data
    assert b"9811122233" in res_leads.data


def test_edit_existing_lead_details(admin_client):
    """Requirement: Staff can edit lead details; original ID and history preserved; no duplicates."""
    # 1. Create initial lead
    admin_client.post("/admin/leads/new", data={
        "name": "Typo Name",
        "phone": "9876500001",
        "area": "Noida",
        "interest": "Other",
        "source": "Walk-in",
        "notes": "Initial typo note"
    }, follow_redirects=True)
    lead_before = dblib.q("SELECT * FROM leads WHERE name='Typo Name'", one=True)
    lead_id = lead_before["id"]
    created_at_before = lead_before["created_at"]

    # 2. GET edit page
    res_edit_page = admin_client.get(f"/admin/leads/{lead_id}/edit")
    assert res_edit_page.status_code == 200
    assert b"Typo Name" in res_edit_page.data

    # 3. POST corrected details
    res_post_edit = admin_client.post(f"/admin/leads/{lead_id}/edit", data={
        "name": "Corrected Rahul Sharma",
        "phone": "9876500002",
        "whatsapp": "9876500002",
        "email": "rahul.corrected@example.com",
        "area": "Greater Kailash, Delhi",
        "interest": "Lower Limb (Leg)",
        "source": "WhatsApp",
        "status": "contacted",
        "next_followup": "2026-11-01",
        "notes": "Updated accurate consultation notes"
    }, follow_redirects=True)
    assert res_post_edit.status_code == 200

    # 4. Verify same lead record updated (no duplicates)
    lead_after = dblib.q("SELECT * FROM leads WHERE id=?", (lead_id,), one=True)
    assert lead_after["name"] == "Corrected Rahul Sharma"
    assert lead_after["phone"] == "9876500002"
    assert lead_after["whatsapp"] == "9876500002"
    assert lead_after["email"] == "rahul.corrected@example.com"
    assert lead_after["area"] == "Greater Kailash, Delhi"
    assert lead_after["interest"] == "Lower Limb (Leg)"
    assert lead_after["source"] == "WhatsApp"
    assert lead_after["status"] == "contacted"
    assert lead_after["notes"] == "Updated accurate consultation notes"
    # Creation timestamp preserved
    assert lead_after["created_at"] == created_at_before

    # Verify audit log recorded the edit
    audit = dblib.q("SELECT * FROM audit_log WHERE entity_type='lead' AND entity_id=? AND action='lead_edit'",
                    (lead_id,), one=True)
    assert audit is not None


def test_six_sequential_interactions_whatsapp_style_history(admin_client):
    """Requirement: Staff records 6 separate interactions for the same lead; all 6 preserved chronologically."""
    # 1. Create a lead
    admin_client.post("/admin/leads/new", data={
        "name": "Rahul Sharma Multicall",
        "phone": "9812345670",
        "interest": "Lower Limb (Leg)",
        "source": "Phone Call",
        "notes": "Initial inquiry"
    }, follow_redirects=True)
    lead = dblib.q("SELECT * FROM leads WHERE name='Rahul Sharma Multicall'", one=True)
    lead_id = lead["id"]

    interactions = [
        ("call", "Called the patient. Explained the prosthesis consultation process.", "Interested", "yes", "2026-10-15"),
        ("whatsapp", "Shared the requested appointment information.", "No Response", "yes", "2026-10-16"),
        ("call", "Patient asked about pricing and available appointment times.", "Appointment Requested", "yes", "2026-10-17"),
        ("sms", "Sent clinic location map and metro directions.", "Interested", "no", ""),
        ("in_person", "Patient visited clinic for physical inspection of stump.", "Interested", "yes", "2026-10-18"),
        ("call", "Final booking confirmation call before doctor consultation.", "Appointment Requested", "no", ""),
    ]

    # Record each interaction
    for comm_type, summary, outcome, fu_req, fu_date in interactions:
        r = admin_client.post(f"/admin/leads/{lead_id}/interaction", data={
            "interaction_type": comm_type,
            "summary": summary,
            "outcome": outcome,
            "next_followup_required": fu_req,
            "next_followup_date": fu_date,
            "notes": f"Additional note for {comm_type}"
        }, follow_redirects=True)
        assert r.status_code == 200

    # Verify all 6 separate interactions exist in lead_history
    history = dblib.q("""SELECT * FROM lead_history
        WHERE lead_id=? AND interaction_type IN ('call','whatsapp','sms','in_person')
        ORDER BY id ASC""", (lead_id,))
    assert len(history) == 6

    # Verify each interaction preserved its exact summary, outcome, and type
    for i, (comm_type, summary, outcome, fu_req, fu_date) in enumerate(interactions):
        assert history[i]["interaction_type"] == comm_type
        assert summary in history[i]["summary"]
        assert history[i]["outcome"] == outcome
        assert history[i]["interaction_at"] is not None
        assert history[i]["logged_by"] is not None  # automatic staff tracking
        if fu_req == "yes" and fu_date:
            assert str(history[i]["due_date"]) == fu_date

    # Verify all 6 are rendered on the Lead Details page (/admin/leads/<id>)
    res_detail = admin_client.get(f"/admin/leads/{lead_id}")
    assert res_detail.status_code == 200
    for comm_type, summary, outcome, _, _ in interactions:
        assert summary.encode() in res_detail.data


def test_followup_scheduling_and_completion_preserves_history(admin_client):
    """Requirement: Follow-up is linked to lead; completing follow-up adds to conversation history."""
    admin_client.post("/admin/leads/new", data={
        "name": "Followup Test Lead",
        "phone": "9812345671",
        "interest": "Upper Limb (Hand/Arm)",
        "source": "Walk-in"
    }, follow_redirects=True)
    lead = dblib.q("SELECT * FROM leads WHERE name='Followup Test Lead'", one=True)
    lead_id = lead["id"]

    # Schedule a follow-up via interaction
    admin_client.post(f"/admin/leads/{lead_id}/interaction", data={
        "interaction_type": "call",
        "summary": "Initial discussion about myoelectric hand",
        "outcome": "Interested",
        "next_followup_required": "yes",
        "next_followup_date": dt.date.today().isoformat()
    }, follow_redirects=True)

    # Verify follow-up exists in followups table linked to lead_id
    fu = dblib.q("SELECT * FROM followups WHERE lead_id=? AND status='pending'", (lead_id,), one=True)
    assert fu is not None
    assert fu["due_date"] == dt.date.today().isoformat()

    # Complete the follow-up
    r_done = admin_client.post(f"/admin/followups/{fu['id']}/complete",
                               data={"note": "Call completed successfully"},
                               follow_redirects=True)
    assert r_done.status_code == 200

    # Verify follow-up is completed
    fu_done = dblib.q("SELECT * FROM followups WHERE id=?", (fu["id"],), one=True)
    assert fu_done["status"] == "completed"

    # Verify that a completion entry was added to lead_history (history preserved!)
    comp_history = dblib.q("SELECT * FROM lead_history WHERE lead_id=? AND outcome='completed'", (lead_id,), one=True)
    assert comp_history is not None
    assert "Call completed successfully" in comp_history["summary"] or "Call completed successfully" in comp_history["note"]


def test_explicit_lead_conversion_workflow(admin_client):
    """Requirement: Explicit conversion workflow makes patient confirmed in Master Patient List and preserves history."""
    # 1. Create a lead and record interaction
    admin_client.post("/admin/leads/new", data={
        "name": "Vikram Malhotra",
        "phone": "9812345672",
        "whatsapp": "9812345672",
        "area": "Chandigarh",
        "interest": "Lower Limb (Leg)",
        "source": "Referral",
        "notes": "Referred by Dr. Verma for transtibial prosthesis"
    }, follow_redirects=True)
    lead = dblib.q("SELECT * FROM leads WHERE name='Vikram Malhotra'", one=True)
    lead_id = lead["id"]

    admin_client.post(f"/admin/leads/{lead_id}/interaction", data={
        "interaction_type": "call",
        "summary": "Detailed clinical assessment discussed.",
        "outcome": "Interested",
        "next_followup_required": "no"
    }, follow_redirects=True)

    # Before conversion: NOT in confirmed Master Patient List
    r_pts_before = admin_client.get("/admin/patients")
    assert b"Vikram Malhotra" not in r_pts_before.data

    # 2. Perform Explicit Conversion
    r_conv = admin_client.post(f"/admin/leads/{lead_id}/convert", follow_redirects=True)
    assert r_conv.status_code == 200

    # 3. Verify lead status updated to converted
    lead_conv = dblib.q("SELECT * FROM leads WHERE id=?", (lead_id,), one=True)
    assert lead_conv["status"] == "converted"
    assert lead_conv["converted_at"] is not None

    # 4. Verify patient is now confirmed
    pid = lead_conv["patient_id"]
    patient = dblib.q("SELECT * FROM patients WHERE id=?", (pid,), one=True)
    assert patient["is_confirmed"] == 1
    assert patient["status"] == "active"
    assert patient["pipeline_stage"] == "consultation"

    # 5. Verify patient NOW appears in Master Patient List (/admin/patients)
    r_pts_after = admin_client.get("/admin/patients")
    assert b"Vikram Malhotra" in r_pts_after.data

    # 6. Verify patient detail displays all conversation history from lead
    r_pdetail = admin_client.get(f"/admin/patients/{pid}")
    assert r_pdetail.status_code == 200
    assert b"Detailed clinical assessment discussed." in r_pdetail.data
    assert b"Lead #" in r_pdetail.data

    # 7. Verify no duplicate patient is created if conversion is triggered again
    pts_count_before = dblib.q("SELECT COUNT(*) c FROM patients", one=True)["c"]
    admin_client.post(f"/admin/leads/{lead_id}/convert", follow_redirects=True)
    pts_count_after = dblib.q("SELECT COUNT(*) c FROM patients", one=True)["c"]
    assert pts_count_before == pts_count_after


def test_unauthorized_user_cannot_edit_lead(client):
    """Requirement: Unauthorized / non-logged-in users cannot edit leads."""
    # Anonymous client attempting to edit lead
    r = client.post("/admin/leads/1/edit", data={"name": "Hacked Name"})
    assert r.status_code in (302, 303)  # redirected to login

