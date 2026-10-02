"""Simple CRM tests — serial numbers, leads with 4 outcomes, one-patient
pipeline (9 stages, re-openable), lifetime history, search."""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_app import app, client, admin_client, dblib  # noqa: F401,E402


def _yymm():
    d = dt.date.today()
    return f"{d.year % 100:02d}{d.month:02d}"


# -------------------------------------------------------------- serial numbers
def test_serial_number_format_and_sequence(admin_client):
    admin_client.post("/admin/patients/new", data={"name": "Serial One", "phone": "9800000101"})
    admin_client.post("/admin/patients/new", data={"name": "Serial Two", "phone": "9800000102"})
    p1 = dblib.q("SELECT serial_no FROM patients WHERE name='Serial One'", one=True)
    p2 = dblib.q("SELECT serial_no FROM patients WHERE name='Serial Two'", one=True)
    yymm = _yymm()
    assert p1["serial_no"].startswith(yymm)
    assert p2["serial_no"].startswith(yymm)
    assert int(p2["serial_no"][4:]) == int(p1["serial_no"][4:]) + 1


def test_serial_helper_no_padding(admin_client):
    from app import helpers as h
    s = h.next_serial_no()
    assert s[:4] == _yymm()
    assert not s[4:].startswith("0") or s[4:] == "0"  # no zero padding
    fixed = dt.date(2026, 9, 1)
    assert h.next_serial_no(fixed)[:4] == "2609"


# ------------------------------------------------------------------- patients
def test_patient_create_stage_and_log(admin_client):
    admin_client.post("/admin/patients/new", data={"name": "Pipe Start", "phone": "9800000201"})
    p = dblib.q("SELECT * FROM patients WHERE name='Pipe Start'", one=True)
    assert p["pipeline_stage"] == "consultation"
    log = dblib.q("SELECT * FROM patient_stage_log WHERE patient_id=?", (p["id"],))
    assert log and log[0]["stage"] == "consultation"


def test_duplicate_phone_opens_existing(admin_client):
    admin_client.post("/admin/patients/new", data={"name": "Dup Phone", "phone": "9800000301"})
    before = dblib.q("SELECT COUNT(*) c FROM patients", one=True)["c"]
    admin_client.post("/admin/patients/new", data={"name": "Dup Phone Again",
                                                   "phone": "9800000301"})
    assert dblib.q("SELECT COUNT(*) c FROM patients", one=True)["c"] == before
    # force_new bypasses the guard
    admin_client.post("/admin/patients/new", data={"name": "Dup Forced",
                                                   "phone": "9800000301",
                                                   "force_new": "1"})
    assert dblib.q("SELECT COUNT(*) c FROM patients", one=True)["c"] == before + 1


def test_search_by_serial_and_phone(admin_client):
    admin_client.post("/admin/patients/new", data={"name": "Searchable", "phone": "9800000401"})
    p = dblib.q("SELECT serial_no FROM patients WHERE name='Searchable'", one=True)
    r = admin_client.get(f"/admin/patients?q={p['serial_no']}")
    assert b"Searchable" in r.data
    r = admin_client.get("/admin/patients?q=9800000401")
    assert b"Searchable" in r.data
    r = admin_client.get("/admin/patients?q=00000401")  # partial phone works
    assert b"Searchable" in r.data


# ------------------------------------------------------------------- pipeline
def _mkpatient(name="Pipeline Person"):
    admin_client_local = None
    return dblib.q("""INSERT INTO patients (name, phone, status, profile_status,
        serial_no, pipeline_stage, stage_updated_at, created_at)
        VALUES (?, ?, 'active', 'complete', ?, 'consultation', now(), now())
        RETURNING id""",
        (name, "9800000501", f"{_yymm()}99"))[0]["id"]


def test_pipeline_walks_all_nine_stages(admin_client):
    admin_client.post("/admin/patients/new", data={"name": "Stage Walker", "phone": "9800000601"})
    p = dblib.q("SELECT id FROM patients WHERE name='Stage Walker'", one=True)
    pid = p["id"]
    expected = ["assessment", "quotation", "approved", "order_items", "processing",
                "clinical_fitting", "dispatch", "completed"]
    for stage in expected:
        admin_client.post(f"/admin/patients/{pid}/stage", data={"stage": "next",
                                                                "note": f"to {stage}"})
        got = dblib.q("SELECT pipeline_stage FROM patients WHERE id=?", (pid,), one=True)
        assert got["pipeline_stage"] == stage
    # history preserved, append-only, in order
    log = dblib.q("SELECT stage FROM patient_stage_log WHERE patient_id=? ORDER BY id", (pid,))
    assert [x["stage"] for x in log] == ["consultation"] + expected
    assert dblib.q("SELECT completed_cycles FROM patients WHERE id=?", (pid,),
                   one=True)["completed_cycles"] == 1
    # re-open for repeat visit
    admin_client.post(f"/admin/patients/{pid}/stage",
                      data={"stage": "reopen", "note": "came back for repair"})
    p2 = dblib.q("SELECT pipeline_stage FROM patients WHERE id=?", (pid,), one=True)
    assert p2["pipeline_stage"] == "consultation"
    last = dblib.q("SELECT note FROM patient_stage_log WHERE patient_id=? ORDER BY id DESC",
                   (pid,), one=True)
    assert "re-opened" in last["note"].lower()
    # invalid stage rejected
    assert admin_client.post(f"/admin/patients/{pid}/stage",
                             data={"stage": "bogus"}).status_code == 400


def test_pipeline_jump_and_amounts(admin_client):
    admin_client.post("/admin/patients/new", data={"name": "Jump Person", "phone": "9800000701"})
    pid = dblib.q("SELECT id FROM patients WHERE name='Jump Person'", one=True)["id"]
    admin_client.post(f"/admin/patients/{pid}/stage", data={"stage": "quotation"})
    assert dblib.q("SELECT pipeline_stage FROM patients WHERE id=?", (pid,),
                   one=True)["pipeline_stage"] == "quotation"
    admin_client.post(f"/admin/patients/{pid}/amounts",
                      data={"total_amount": "45000", "advance_amount": "10000"})
    p = dblib.q("SELECT total_amount, advance_amount FROM patients WHERE id=?", (pid,),
                one=True)
    assert float(p["total_amount"]) == 45000 and float(p["advance_amount"]) == 10000
    # negative rejected
    admin_client.post(f"/admin/patients/{pid}/amounts", data={"total_amount": "-5"})
    assert float(dblib.q("SELECT total_amount FROM patients WHERE id=?", (pid,),
                         one=True)["total_amount"]) == 45000


# ---------------------------------------------------------------------- leads
def test_lead_new_creates_patient(admin_client):
    admin_client.post("/admin/leads/new", data={"name": "Fresh Lead", "phone": "9800000801",
                                                "source": "Walk-in"})
    l = dblib.q("""SELECT l.*, p.serial_no FROM leads l JOIN patients p ON p.id=l.patient_id
        ORDER BY l.id DESC LIMIT 1""", one=True)
    assert l["status"] == "new" and l["serial_no"]


def test_lead_links_to_existing_patient_by_phone(admin_client):
    admin_client.post("/admin/patients/new", data={"name": "Known Person",
                                                   "phone": "9800000901"})
    before = dblib.q("SELECT COUNT(*) c FROM patients", one=True)["c"]
    admin_client.post("/admin/leads/new", data={"name": "Known Person Lead",
                                                "phone": "9800000901"})
    assert dblib.q("SELECT COUNT(*) c FROM patients", one=True)["c"] == before
    l = dblib.q("SELECT * FROM leads ORDER BY id DESC LIMIT 1", one=True)
    p = dblib.q("SELECT id FROM patients WHERE name='Known Person'", one=True)
    assert l["patient_id"] == p["id"]


def test_lead_outcome_appointment_opens_pipeline(admin_client):
    admin_client.post("/admin/leads/new", data={"name": "Conv Lead", "phone": "9800001001"})
    l = dblib.q("SELECT * FROM leads ORDER BY id DESC LIMIT 1", one=True)
    r = admin_client.post(f"/admin/leads/{l['id']}/outcome/appointment")
    assert r.status_code == 302 and f"/admin/patients/{l['patient_id']}" in r.headers["Location"]
    assert dblib.q("SELECT status FROM leads WHERE id=?", (l["id"],),
                   one=True)["status"] == "appointment"
    assert dblib.q("SELECT pipeline_stage FROM patients WHERE id=?", (l["patient_id"],),
                   one=True)["pipeline_stage"] == "consultation"
    hist = dblib.q("SELECT * FROM lead_history WHERE lead_id=?", (l["id"],))
    assert hist and hist[0]["outcome"] == "appointment"


def test_lead_outcome_followup_creates_followup(admin_client):
    admin_client.post("/admin/leads/new", data={"name": "FU Lead", "phone": "9800001101"})
    l = dblib.q("SELECT * FROM leads ORDER BY id DESC LIMIT 1", one=True)
    admin_client.post(f"/admin/leads/{l['id']}/outcome/followup",
                      data={"due_date": "2026-10-05", "note": "call again"})
    assert dblib.q("SELECT status FROM leads WHERE id=?", (l["id"],),
                   one=True)["status"] == "followup"
    fu = dblib.q("SELECT * FROM followups WHERE patient_id=?", (l["patient_id"],), one=True)
    assert fu and fu["status"] == "pending" and fu["due_date"] == "2026-10-05"


def test_lead_hold_lost_and_repeat_history(admin_client):
    admin_client.post("/admin/leads/new", data={"name": "Bounce Lead", "phone": "9800001201"})
    l = dblib.q("SELECT * FROM leads ORDER BY id DESC LIMIT 1", one=True)
    # the process repeats: followup -> followup -> appointment, all recorded
    admin_client.post(f"/admin/leads/{l['id']}/outcome/followup", data={"due_date": "2026-10-01"})
    admin_client.post(f"/admin/leads/{l['id']}/outcome/followup", data={"due_date": "2026-10-03"})
    admin_client.post(f"/admin/leads/{l['id']}/outcome/hold")
    assert dblib.q("SELECT status FROM leads WHERE id=?", (l["id"],), one=True)["status"] == "hold"
    admin_client.post(f"/admin/leads/{l['id']}/outcome/appointment")
    hist = dblib.q("SELECT outcome FROM lead_history WHERE lead_id=? ORDER BY id", (l["id"],))
    assert [x["outcome"] for x in hist] == ["followup", "followup", "hold", "appointment"]
    # lost is final-able too
    admin_client.post(f"/admin/leads/{l['id']}/outcome/lost")
    assert dblib.q("SELECT status FROM leads WHERE id=?", (l["id"],),
                   one=True)["status"] == "lost"
    # invalid outcome rejected
    assert admin_client.post(f"/admin/leads/{l['id']}/outcome/bogus").status_code == 400


# -------------------------------------------------------------- meta webhook
def test_meta_webhook_creates_serial_and_new_lead(admin_client):
    """Signed Meta event -> patient with serial + lead with status 'new'."""
    import hashlib
    import hmac
    import json
    from flask import current_app
    secret = admin_client.application.config.get("META_APP_SECRET") or "local-dev-secret"
    payload = {"object": "page", "entry": [{"id": "PAGE_ID", "time": 1000, "changes": [{
        "field": "leadgen", "value": {"leads": [{
            "leadgen_id": "SIMPLE-TEST-1", "created_time": 1759000000,
            "form_id": "FORM123", "ad_id": "AD1", "adset_id": "AS1",
            "campaign_id": "C1",
            "field_data": {"full_name": "Meta Simple",
                           "phone_number": "9800001301",
                           "interested_in": "BK Prosthesis"}}]}}]}]}
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    r = admin_client.post("/webhooks/meta", data=body,
                          headers={"Content-Type": "application/json",
                                   "X-Hub-Signature-256": f"sha256={sig}"})
    assert r.status_code == 200
    p = dblib.q("SELECT * FROM patients WHERE name='Meta Simple'", one=True)
    assert p and p["serial_no"] and p["serial_no"].startswith(_yymm())
    l = dblib.q("SELECT * FROM leads WHERE patient_id=?", (p["id"],), one=True)
    assert l["status"] == "new" and l["platform"] in ("facebook", "instagram")


# --------------------------------------------------------------- pages / nav
def test_pages_render(admin_client):
    for path in ["/admin", "/admin/leads", "/admin/patients", "/admin/followups",
                 "/admin/settings", "/admin/journeys", "/admin/products"]:
        assert admin_client.get(path).status_code == 200, path


def test_removed_modules_gone_from_nav(admin_client):
    r = admin_client.get("/admin")
    # staff & performance returned with the 2026-09 staff-assignment feature
    for gone in [b"/admin/appointments", b"/admin/reports",
                 b"/admin/notifications", b"/admin/activity"]:
        assert gone not in r.data, gone
    for keep in [b"/admin/leads", b"/admin/patients", b"/admin/followups",
                 b"/admin/settings", b"/admin/staff", b"/admin/performance"]:
        assert keep in r.data, keep


def test_followup_complete_and_reschedule(admin_client):
    admin_client.post("/admin/patients/new", data={"name": "FU Life", "phone": "9800001401"})
    pid = dblib.q("SELECT id FROM patients WHERE name='FU Life'", one=True)["id"]
    admin_client.post("/admin/followups/new", data={"patient_id": str(pid),
                                                    "due_date": "2026-10-01",
                                                    "note": "review"})
    fu = dblib.q("SELECT * FROM followups WHERE patient_id=?", (pid,), one=True)
    admin_client.post(f"/admin/followups/{fu['id']}/reschedule", data={"due_date": "2026-10-09"})
    assert dblib.q("SELECT due_date, original_due_date FROM followups WHERE id=?",
                   (fu["id"],), one=True)["due_date"] == "2026-10-09"
    admin_client.post(f"/admin/followups/{fu['id']}/complete", data={"note": "done well"})
    got = dblib.q("SELECT * FROM followups WHERE id=?", (fu["id"],), one=True)
    assert got["status"] == "completed" and "done well" in got["note"]
