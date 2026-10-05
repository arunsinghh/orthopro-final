"""Staff accounts, lead assignment & monitoring (migration 007)."""
from tests.test_app import app, client, admin_client, dblib, ADMIN_USER, ADMIN_PW  # noqa: F401
from app import security
from app.helpers import now


def _make_staff(username, caps="leads,leads_edit", active=1, full_name=""):
    return dblib.q(
        "INSERT INTO users (username, password_hash, role, full_name, caps, is_active, created_at) "
        "VALUES (?,?,?,?,?,?,?) RETURNING id",
        (username, security.hash_password("Staff#12345"), "staff", full_name, caps,
         active, now()))[0]["id"]


def _make_lead(name, assigned_to=None, status="new"):
    return dblib.q(
        "INSERT INTO leads (patient_id, source, platform, status, notes, assigned_to, created_at) "
        "VALUES (NULL, 'Walk-in', '', ?, '', ?, ?) RETURNING id",
        (status, assigned_to, now()))[0]["id"]


def _login(client, username, password="Staff#12345"):
    return client.post("/admin/login", data={"username": username, "password": password},
                       follow_redirects=False)


def test_staff_sees_only_own_leads(app, client):
    s1 = _make_staff("staff_one")
    _make_staff("staff_two")
    mine = _make_lead("Own Lead Person", s1)
    other = _make_lead("Other Lead Person", s1 + 1)
    assert _login(client, "staff_one").status_code in (302, 303)
    rv = client.get("/admin/leads")
    assert rv.status_code == 200 and b"My Leads" in rv.data
    # leads are identified by their outcome-button URLs (test leads have no patient row)
    assert f"/admin/leads/{mine}/outcome/".encode() in rv.data
    assert f"/admin/leads/{other}/outcome/".encode() not in rv.data


def test_staff_cannot_update_others_lead(app, client):
    s1 = _make_staff("staff_three")
    s2 = _make_staff("staff_four")
    foreign = _make_lead("Foreign Lead", s2)
    assert _login(client, "staff_three").status_code in (302, 303)
    rv = client.post(f"/admin/leads/{foreign}/outcome/appointment", data={})
    assert rv.status_code == 403


def test_staff_without_edit_cap_cannot_post_outcome(app, client):
    s = _make_staff("staff_viewer", caps="leads")
    mine = _make_lead("Viewer Lead", s)
    assert _login(client, "staff_viewer").status_code in (302, 303)
    rv = client.post(f"/admin/leads/{mine}/outcome/appointment", data={})
    assert rv.status_code == 403
    # and no staff-management access
    assert client.get("/admin/staff").status_code == 403


def test_admin_bulk_assign_and_unassign(app, admin_client):
    s = _make_staff("staff_assign")
    l1, l2 = _make_lead("Assign One"), _make_lead("Assign Two")
    rv = admin_client.post("/admin/leads/assign",
                           data={"lead_ids": [l1, l2], "assigned_to": str(s)})
    assert rv.status_code in (302, 303)
    got = dblib.q("SELECT assigned_to FROM leads WHERE id IN (?,?)", (l1, l2))
    assert all(r["assigned_to"] == s for r in got)
    admin_client.post("/admin/leads/assign", data={"lead_ids": [l1], "assigned_to": ""})
    assert dblib.q("SELECT assigned_to FROM leads WHERE id=?", (l1,), one=True)["assigned_to"] is None


def test_disabled_staff_cannot_login(app, client):
    _make_staff("staff_off", active=0)
    rv = _login(client, "staff_off")
    assert rv.status_code == 403


def test_performance_counts(app, admin_client, client):
    s = _make_staff("staff_perf", full_name="Perf Person")
    l1 = _make_lead("Perf Lead A", s)
    _make_lead("Perf Lead B", s)
    admin_client.post(f"/admin/leads/{l1}/outcome/appointment", data={"note": ""})
    rv = admin_client.get("/admin/performance?range=all")
    assert rv.status_code == 200
    assert b"Perf Person" in rv.data
    # assigned=2, appointments=1 visible in table rows
    body = rv.data.decode()
    row = body[body.index("Perf Person"):]
    assert "<td><b>2</b></td>" in row and "<td>1</td>" in row


def test_admin_still_sees_all_leads(app, admin_client):
    s = _make_staff("staff_allview")
    scoped = _make_lead("Scoped Lead X", s)
    free = _make_lead("Unassigned Lead Y")
    rv = admin_client.get("/admin/leads")
    assert f"/admin/leads/{scoped}/outcome/".encode() in rv.data
    assert f"/admin/leads/{free}/outcome/".encode() in rv.data
    assert b"Not assigned" in rv.data


def test_leads_search_and_direct_assignment(app, admin_client):
    s = _make_staff("staff_searcher", full_name="Search Staff")
    rv = admin_client.post("/admin/leads/new", data={
        "name": "Unique Searchable Patient",
        "phone": "9998887776",
        "notes": "Custom special enquiry text",
        "assigned_to": str(s),
        "interest": "Lower Limb (Leg)",
    })
    assert rv.status_code in (302, 303)
    lead = dblib.q("SELECT * FROM leads WHERE notes='Custom special enquiry text'", one=True)
    assert lead["assigned_to"] == s
    assert lead["interest"] == "Lower Limb (Leg)"

    # Test search by name
    res = admin_client.get("/admin/leads?q=Unique+Searchable")
    assert res.status_code == 200
    assert b"Unique Searchable Patient" in res.data

    # Test search by phone
    res_phone = admin_client.get("/admin/leads?q=9998887776")
    assert b"Unique Searchable Patient" in res_phone.data

    # Test search with no match
    res_miss = admin_client.get("/admin/leads?q=NonExistentKeywordXYZ")
    assert b"No leads found" in res_miss.data


def test_leads_sections_whatsapp_and_manual(app, admin_client):
    s = _make_staff("staff_section_test")
    # 1. Create a WhatsApp lead
    wa_lead_id = dblib.q(
        "INSERT INTO leads (patient_id, source, platform, status, notes, assigned_to, created_at) "
        "VALUES (NULL, 'WhatsApp', 'whatsapp', 'new', 'WhatsApp Test Message', ?, ?) RETURNING id",
        (s, now()))[0]["id"]

    # 2. Create a Manual / Website lead
    man_lead_id = dblib.q(
        "INSERT INTO leads (patient_id, source, platform, status, notes, assigned_to, created_at) "
        "VALUES (NULL, 'Walk-in', '', 'new', 'Manual Walkin Note', ?, ?) RETURNING id",
        (s, now()))[0]["id"]

    # View All Sections
    rv_all = admin_client.get("/admin/leads?section_type=all")
    assert rv_all.status_code == 200
    assert b"WhatsApp Leads" in rv_all.data
    assert b"Manual / Website &amp; Appointment Leads" in rv_all.data or b"Manual / Website & Appointment Leads" in rv_all.data
    assert b"WhatsApp Test Message" in rv_all.data
    assert b"Manual Walkin Note" in rv_all.data

    # View WhatsApp Section Only
    rv_wa = admin_client.get("/admin/leads?section_type=whatsapp")
    assert rv_wa.status_code == 200
    assert b"WhatsApp Test Message" in rv_wa.data
    assert b"Manual Walkin Note" not in rv_wa.data

    # View Manual Section Only
    rv_man = admin_client.get("/admin/leads?section_type=manual")
    assert rv_man.status_code == 200
    assert b"Manual Walkin Note" in rv_man.data
    assert b"WhatsApp Test Message" not in rv_man.data

    # Bulk assign elements present
    assert b'id="select-all-leads"' in rv_all.data
    assert b'id="bulk-assign-form"' in rv_all.data
    assert f'value="{wa_lead_id}"'.encode() in rv_all.data
    assert f'value="{man_lead_id}"'.encode() in rv_all.data

