"""Admin panel routes — simple CRM (leads -> pipeline -> lifetime patient file).

Every route is behind :func:`security.login_required`. State-changing actions
are POST-only, CSRF-protected (Flask-WTF), and audited.
"""
import datetime as dt
import os
import re

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   session, url_for)

from .. import db
from .. import security
from .. import helpers as h
from .. import uploads as up
from ..audit import record
from ..security import (has_cap, login_required, role_required)

bp = Blueprint("admin", __name__, url_prefix="/admin")

# ================================================================ PIPELINE
PIPELINE_STAGES = ["consultation", "assessment", "quotation", "approved",
                   "order_items", "processing", "clinical_fitting", "dispatch",
                   "completed"]
PIPELINE_LABELS = {"consultation": "Consultation", "assessment": "Assessment / Measurement",
                   "quotation": "Quotation", "approved": "Approved",
                   "order_items": "Order Items", "processing": "Processing",
                   "clinical_fitting": "Clinical Fitting", "dispatch": "Dispatch",
                   "completed": "Completed"}

LEAD_OUTCOMES = {
    "appointment": ("appointment", "Converted to Appointment"),
    "followup": ("followup", "Follow-up"),
    "hold": ("hold", "On Hold"),
    "lost": ("lost", "Lost"),
}


def _next_stage(stage):
    try:
        i = PIPELINE_STAGES.index(stage)
    except ValueError:
        return PIPELINE_STAGES[0]
    return PIPELINE_STAGES[min(i + 1, len(PIPELINE_STAGES) - 1)]


def _service_names():
    return [r["name"] for r in db.q("SELECT name FROM services ORDER BY sort")]


def _platform_badge(lead):
    """Admin-created vs Meta/WhatsApp vs other sources."""
    plat = (lead.get("platform") or "").lower()
    src = (lead.get("source") or "").lower()
    if plat == "whatsapp" or "whatsapp" in src:
        return "💬 WhatsApp"
    if plat == "facebook" or "facebook" in src:
        return "📘 Facebook"
    if plat == "instagram" or "instagram" in src:
        return "📷 Instagram"
    raw_src = lead.get("source") or ""
    if raw_src:
        return f"🧑 {raw_src}"
    return "🧑 Admin"


# --------------------------------------------------------------- dashboard
@bp.route("")
@bp.route("/")
@login_required
def dashboard():
    today = h.today()
    stats = {
        "patients": db.q("SELECT COUNT(*) c FROM patients", one=True)["c"],
        "new_leads": db.q("SELECT COUNT(*) c FROM leads WHERE status='new'", one=True)["c"],
        "fu_today": db.q("SELECT COUNT(*) c FROM followups WHERE status='pending' "
                         "AND due_date<=?", (today,), one=True)["c"],
        "active_pipeline": db.q("SELECT COUNT(*) c FROM patients WHERE pipeline_stage<>'' "
                                "AND pipeline_stage<>'completed'", one=True)["c"],
    }
    attention = []
    if stats["new_leads"]:
        attention.append(("📞", f"{stats['new_leads']} new lead(s) to contact",
                          "/admin/leads?view=new"))
    if stats["fu_today"]:
        attention.append(("🔔", f"{stats['fu_today']} follow-up(s) due",
                          "/admin/followups"))
    todays = db.q("""SELECT f.id, f.due_date, f.note, p.id pid, p.name pname, p.serial_no
        FROM followups f JOIN patients p ON p.id=f.patient_id
        WHERE f.status='pending' AND f.due_date<=? ORDER BY f.due_date, f.id""", (today,))
    new_leads = db.q("""SELECT l.id, l.status, l.source, l.platform, l.created_at,
            p.name pname, p.phone pphone, p.serial_no FROM leads l
        LEFT JOIN patients p ON p.id=l.patient_id
        WHERE l.status='new' ORDER BY l.id DESC LIMIT 10""")
    in_progress = db.q("""SELECT id, serial_no, name, phone, pipeline_stage, stage_updated_at
        FROM patients WHERE pipeline_stage<>'' AND pipeline_stage<>'completed'
        ORDER BY stage_updated_at DESC NULLS LAST LIMIT 8""")
    return render_template("admin/dashboard.html", stats=stats, attention=attention,
                           todays=todays, new_leads=new_leads, in_progress=in_progress,
                           stages=PIPELINE_LABELS, section="dashboard")


# --------------------------------------------------------------- patients
@bp.route("/patients")
@login_required
def patients():
    q = request.args.get("q", "").strip()
    if q:
        # search by serial number or phone (also matches name as a courtesy)
        like = f"%{q}%"
        phone_like = f"%{q.replace(' ', '').replace('+', '')}%"
        rows = db.q("""SELECT id, serial_no, name, phone, area, notes, pipeline_stage,
                total_amount, advance_amount, created_at FROM patients
            WHERE serial_no LIKE ? OR REPLACE(REPLACE(phone,' ',''),'+','') LIKE ?
                OR name LIKE ?
            ORDER BY id DESC""", (like, phone_like, like))
    else:
        rows = db.q("""SELECT id, serial_no, name, phone, area, notes, pipeline_stage,
                total_amount, advance_amount, created_at FROM patients ORDER BY id DESC""")
    return render_template("admin/patients.html", rows=rows, q=q,
                           stages=PIPELINE_LABELS, section="patients")


@bp.route("/patients/new", methods=["POST"])
@login_required
def patient_new():
    f = request.form
    name = f.get("name", "").strip()
    phone = f.get("phone", "").strip()
    if not name:
        flash("Name is required.", "err")
        return redirect(url_for("admin.patients"))
    # duplicate guard by phone — never auto-merge, just warn
    if phone:
        norm = phone.replace(" ", "").replace("+", "")
        dup = db.q("""SELECT id, serial_no, name FROM patients
            WHERE REPLACE(REPLACE(phone,' ',''),'+','')=?""", (norm,), one=True)
        if dup and f.get("force_new") != "1":
            flash(f"Possible duplicate: {dup['name']} ({dup['serial_no']}). "
                  "Open that patient or submit again to force a new record.", "err")
            return redirect(url_for("admin.patient_detail", pid=dup["id"]))
    serial = h.next_serial_no()
    rows = db.q("""INSERT INTO patients (name, phone, area, notes, source, status,
        profile_status, patient_code, serial_no, pipeline_stage, stage_updated_at,
        created_at) VALUES (?,?,?,?,?, 'active', 'complete', ?, ?, 'consultation', ?, ?)
        RETURNING id""",
        (name, phone, f.get("area", "").strip(), f.get("notes", "").strip(),
         f.get("source", "") or "Walk-in", h.next_patient_code(), serial, h.now(), h.now()))
    pid = rows[0]["id"]
    db.q("INSERT INTO patient_stage_log (patient_id, stage, note, created_at) "
         "VALUES (?, 'consultation', 'Patient registered', ?)", (pid, h.now()))
    record("patient_create", f"id={pid} serial={serial}", entity_type="patient",
           entity_id=pid)
    flash(f"Patient {serial} added.", "ok")
    return redirect(url_for("admin.patient_detail", pid=pid))


@bp.route("/patients/<int:pid>")
@login_required
def patient_detail(pid):
    p = db.q("SELECT * FROM patients WHERE id=?", (pid,), one=True)
    if not p:
        abort(404)
    history = db.q("""SELECT s.*, u.username staff FROM patient_stage_log s
        LEFT JOIN users u ON u.id=NULL WHERE s.patient_id=?
        ORDER BY s.id DESC LIMIT 100""", (pid,))
    fups = db.q("""SELECT * FROM followups WHERE patient_id=?
        ORDER BY (status='pending') DESC, due_date DESC, id DESC LIMIT 30""", (pid,))
    leads = db.q("""SELECT * FROM leads WHERE patient_id=? ORDER BY id DESC""", (pid,))
    balance = float(p["total_amount"] or 0) - float(p["advance_amount"] or 0)
    try:
        current_idx = PIPELINE_STAGES.index(p["pipeline_stage"])
    except ValueError:
        current_idx = -1
    return render_template("admin/patient_detail.html", p=p, history=history, fups=fups,
                           leads=leads, balance=balance, stages=PIPELINE_STAGES,
                           labels=PIPELINE_LABELS, current_idx=current_idx,
                           next_stage=_next_stage(p["pipeline_stage"]), section="patients")


@bp.route("/patients/<int:pid>/save", methods=["POST"])
@login_required
def patient_save(pid):
    p = db.q("SELECT id FROM patients WHERE id=?", (pid,), one=True)
    if not p:
        abort(404)
    f = request.form
    db.q("UPDATE patients SET name=?, phone=?, area=?, notes=? WHERE id=?",
         (f.get("name", "").strip(), f.get("phone", "").strip(),
          f.get("area", "").strip(), f.get("notes", "").strip(), pid))
    record("patient_update", f"id={pid}", entity_type="patient", entity_id=pid)
    flash("Saved.", "ok")
    return redirect(url_for("admin.patient_detail", pid=pid))


@bp.route("/patients/<int:pid>/stage", methods=["POST"])
@login_required
def patient_stage(pid):
    p = db.q("SELECT id, name, serial_no, pipeline_stage FROM patients WHERE id=?",
             (pid,), one=True)
    if not p:
        abort(404)
    f = request.form
    stage = f.get("stage", "")
    if stage == "next":
        stage = _next_stage(p["pipeline_stage"] or "consultation")
    if stage == "reopen":
        stage = "consultation"
    if stage not in PIPELINE_STAGES:
        abort(400)
    if stage == p["pipeline_stage"]:
        flash("Already at that stage.", "err")
        return redirect(url_for("admin.patient_detail", pid=pid))
    reopened = f.get("stage") == "reopen"
    db.q("UPDATE patients SET pipeline_stage=?, stage_updated_at=? WHERE id=?",
         (stage, h.now(), pid))
    if stage == "completed":
        db.q("UPDATE patients SET completed_cycles=completed_cycles+1 WHERE id=?", (pid,))
    db.q("INSERT INTO patient_stage_log (patient_id, stage, note, created_at) "
         "VALUES (?,?,?,?)",
         (pid, stage, ("Pipeline re-opened — repeat visit. " if reopened else "") +
          f.get("note", "").strip(), h.now()))
    record("pipeline_stage", f"serial={p['serial_no']} -> {stage}",
           entity_type="patient", entity_id=pid)
    flash(f"{p['name']} → {PIPELINE_LABELS[stage]}.", "ok")
    return redirect(url_for("admin.patient_detail", pid=pid))


@bp.route("/patients/<int:pid>/amounts", methods=["POST"])
@login_required
def patient_amounts(pid):
    p = db.q("SELECT id, total_amount, advance_amount FROM patients WHERE id=?",
             (pid,), one=True)
    if not p:
        abort(404)
    try:
        total = float(request.form.get("total_amount", 0) or 0)
        advance = float(request.form.get("advance_amount", 0) or 0)
    except (TypeError, ValueError):
        flash("Amounts must be numbers.", "err")
        return redirect(url_for("admin.patient_detail", pid=pid))
    if total < 0 or advance < 0:
        flash("Amounts cannot be negative.", "err")
        return redirect(url_for("admin.patient_detail", pid=pid))
    db.q("UPDATE patients SET total_amount=?, advance_amount=? WHERE id=?",
         (total, advance, pid))
    record("patient_amounts", f"id={pid} total={total} advance={advance}",
           entity_type="patient", entity_id=pid)
    flash("Amounts saved.", "ok")
    return redirect(url_for("admin.patient_detail", pid=pid))


@bp.route("/patients/<int:pid>/delete", methods=["POST"])
@login_required
def patient_delete(pid):
    db.q("DELETE FROM patients WHERE id=?", (pid,))
    record("patient_delete", f"id={pid}")
    flash("Patient deleted.", "ok")
    return redirect(url_for("admin.patients"))


# ------------------------------------------------------------------ leads
@bp.route("/leads")
@login_required
def leads():
    if not has_cap("leads"):
        abort(403)
    view = request.args.get("view", "all")
    staff_filter = request.args.get("staff", "")
    type_f = request.args.get("t", "")
    src_f = request.args.get("src", "").strip()
    q = request.args.get("q", "").strip()
    section_type = request.args.get("section_type", "all").strip().lower()
    if section_type not in ("all", "whatsapp", "manual"):
        section_type = "all"
    scoped_uid = None if security.current_role() == "super_admin" \
        else session["admin_uid"]
    base = """SELECT l.id, l.status, l.source, l.platform, l.interest, l.notes, l.created_at,
        l.assigned_to, su.username assigned_name, su.full_name assigned_full_name,
        p.id pid, p.name pname, p.phone pphone, p.serial_no, p.pipeline_stage, p.area,
        (SELECT note FROM lead_history WHERE lead_id=l.id ORDER BY id DESC LIMIT 1) last_note,
        (SELECT outcome FROM lead_history WHERE lead_id=l.id ORDER BY id DESC LIMIT 1) last_outcome,
        (SELECT due_date FROM lead_history WHERE lead_id=l.id AND due_date IS NOT NULL ORDER BY id DESC LIMIT 1) last_due_date,
        (SELECT COUNT(*) FROM lead_history WHERE lead_id=l.id) history_count
        FROM leads l LEFT JOIN patients p ON p.id=l.patient_id
        LEFT JOIN users su ON su.id=l.assigned_to"""
    filters = {
        "all": " WHERE 1=1",
        "new": " WHERE l.status='new'",
        "followup": " WHERE l.status='followup'",
        "hold": " WHERE l.status='hold'",
        "lost": " WHERE l.status='lost'",
        "appointment": " WHERE l.status='appointment'",
    }
    where = filters.get(view, filters["all"])
    args = []
    if type_f:
        where += " AND l.interest=?"
        args.append(type_f)
    if src_f:
        if src_f.lower() == "whatsapp":
            where += " AND (l.platform='whatsapp' OR l.source ILIKE '%whatsapp%')"
        elif src_f.lower() == "facebook":
            where += " AND (l.platform='facebook' OR l.source ILIKE '%facebook%')"
        elif src_f.lower() == "instagram":
            where += " AND (l.platform='instagram' OR l.source ILIKE '%instagram%')"
        else:
            where += " AND (l.source=?)"
            args.append(src_f)
    if scoped_uid:
        where += " AND l.assigned_to=?"
        args.append(scoped_uid)
    elif staff_filter.isdigit():
        where += " AND l.assigned_to=?"
        args.append(int(staff_filter))
    if q:
        where += " AND (p.name ILIKE ? OR p.phone ILIKE ? OR CAST(p.serial_no AS TEXT) ILIKE ? OR l.notes ILIKE ?)"
        like = f"%{q}%"
        args.extend([like, like, like, like])
    sql = base + where + " ORDER BY l.id DESC LIMIT 300"
    rows = db.q(sql, tuple(args))
    cargs = [scoped_uid] if scoped_uid else ([int(staff_filter)] if staff_filter.isdigit() else [])

    c_where = " WHERE assigned_to=?" if cargs else ""
    c_res = db.q(f"""SELECT
        COUNT(*) AS c_all,
        COUNT(*) FILTER (WHERE status='new') AS c_new,
        COUNT(*) FILTER (WHERE status='followup') AS c_followup,
        COUNT(*) FILTER (WHERE status='appointment') AS c_appointment,
        COUNT(*) FILTER (WHERE status='hold') AS c_hold,
        COUNT(*) FILTER (WHERE status='lost') AS c_lost,
        COUNT(*) FILTER (WHERE platform='whatsapp' OR source ILIKE '%whatsapp%') AS c_whatsapp
        FROM leads{c_where}""", tuple(cargs), one=True)
    counts = {
        "all": c_res["c_all"] if c_res else 0,
        "new": c_res["c_new"] if c_res else 0,
        "followup": c_res["c_followup"] if c_res else 0,
        "appointment": c_res["c_appointment"] if c_res else 0,
        "hold": c_res["c_hold"] if c_res else 0,
        "lost": c_res["c_lost"] if c_res else 0,
        "whatsapp": c_res["c_whatsapp"] if c_res else 0,
    }
    counts["manual"] = max(0, counts["all"] - counts["whatsapp"])
    for r in rows:
        r["badge"] = _platform_badge(r)
        r["is_whatsapp"] = (r.get("platform") or "").lower() == "whatsapp" or "whatsapp" in (r.get("source") or "").lower()
    wa_leads = [r for r in rows if r["is_whatsapp"]]
    manual_leads = [r for r in rows if not r["is_whatsapp"]]
    if section_type == "whatsapp":
        rows = wa_leads
    elif section_type == "manual":
        rows = manual_leads
    staff = [] if scoped_uid else db.q(
        "SELECT id, username, full_name FROM users WHERE is_active=1 ORDER BY id")
    return render_template("admin/leads.html", rows=rows, wa_leads=wa_leads, manual_leads=manual_leads,
                           view=view, counts=counts, section_type=section_type,
                           sources=[x["name"] for x in db.q(
                               "SELECT name FROM sources WHERE is_active=1 ORDER BY sort_order")],
                           today=h.today(), section="leads", staff=staff,
                           scoped=bool(scoped_uid), staff_filter=staff_filter,
                           type_f=type_f, src_f=src_f, q=q, lead_types=h.LEAD_TYPES)


@bp.route("/leads/new", methods=["POST"])
@login_required
def lead_new():
    if not (has_cap("leads") or has_cap("leads_edit") or current_role() == "super_admin"):
        abort(403)
    f = request.form
    name = f.get("name", "").strip()
    if not name:
        flash("Name is required.", "err")
        return redirect(url_for("admin.leads"))
    phone = f.get("phone", "").strip()
    # existing patient by phone? link the lead to them — never duplicate people
    pid = None
    if phone:
        norm = phone.replace(" ", "").replace("+", "").replace("-", "").strip()
        p = db.q("""SELECT id FROM patients
            WHERE REPLACE(REPLACE(REPLACE(phone,' ',''),'+',''),'-','')=?""", (norm,), one=True)
        pid = p["id"] if p else None
    if not pid:
        serial = h.next_serial_no()
        pid = db.q("""INSERT INTO patients (name, phone, area, source, status,
            profile_status, patient_code, serial_no, pipeline_stage, created_at)
            VALUES (?,?,?,?, 'active', 'complete', ?, ?, '', ?) RETURNING id""",
            (name, phone, f.get("area", "").strip(), f.get("source", "") or "Walk-in",
             h.next_patient_code(), serial, h.now()))[0]["id"]
    notes = f.get("notes", "").strip()
    interest = (f.get("interest") or "").strip() or h.detect_lead_type(notes)
    assign_val = f.get("assigned_to", "").strip()
    assigned_to = int(assign_val) if assign_val.isdigit() else None
    if not assigned_to and session.get("admin_role") != "super_admin":
        assigned_to = session.get("admin_uid")
    lid = db.q("""INSERT INTO leads (patient_id, source, platform, status, interest, notes, assigned_to, created_at)
        VALUES (?,?,?,?, ?, ?, ?, ?) RETURNING id""",
        (pid, f.get("source", "") or "Walk-in", "", "new", interest, notes, assigned_to, h.now()))[0]["id"]
    record("lead_create", f"id={lid} source={f.get('source','')}", entity_type="lead",
           entity_id=lid)
    flash("Lead added.", "ok")
    return redirect(url_for("admin.leads", view="new"))


@bp.route("/leads/<int:lid>/outcome/<outcome>", methods=["POST"])
@login_required
def lead_outcome(lid, outcome):
    if outcome not in LEAD_OUTCOMES:
        abort(400)
    if not security.has_cap("leads_edit"):
        abort(403)
    lead = db.q("""SELECT l.*, p.id pid, p.name pname, p.pipeline_stage
        FROM leads l LEFT JOIN patients p ON p.id=l.patient_id WHERE l.id=?""",
        (lid,), one=True)
    if not lead:
        abort(404)
    if security.current_role() != "super_admin" and \
            (lead["assigned_to"] or 0) != session["admin_uid"]:
        abort(403)  # staff can only work their own leads
    f = request.form
    note = f.get("note", "").strip()
    status = LEAD_OUTCOMES[outcome][0]
    db.q("UPDATE leads SET status=? WHERE id=?", (status, lid))
    due = f.get("due_date") or None
    db.q("INSERT INTO lead_history (lead_id, outcome, note, due_date, created_at) "
         "VALUES (?,?,?,?,?)", (lid, outcome, note, due, h.now()))

    if outcome == "appointment" and lead["pid"]:
        # Converted: open (or continue) the patient's pipeline at Consultation
        if lead["pipeline_stage"] in ("", "completed"):
            db.q("UPDATE patients SET pipeline_stage='consultation', stage_updated_at=? "
                 "WHERE id=?", (h.now(), lead["pid"]))
            db.q("INSERT INTO patient_stage_log (patient_id, stage, note, created_at) "
                 "VALUES (?, 'consultation', ?, ?)",
                 (lead["pid"], ("Re-opened from lead. " if lead["pipeline_stage"] ==
                                "completed" else "Lead converted to appointment. ") + note,
                  h.now()))
        record("lead_appointment", f"lead={lid} patient={lead['pid']}",
               entity_type="lead", entity_id=lid)
        flash(f"{lead['pname']} converted — pipeline at Consultation.", "ok")
        return redirect(url_for("admin.patient_detail", pid=lead["pid"]))

    if outcome == "followup" and lead["pid"]:
        db.q("""INSERT INTO followups (patient_id, due_date, note, status, followup_type,
            purpose, created_at) VALUES (?,?,?, 'pending', 'Lead follow-up', ?, ?)""",
            (lead["pid"], due or h.today(), note or "Follow up with lead",
             note or "Follow up with lead", h.now()))
        record("lead_followup", f"lead={lid} due={due or h.today()}",
               entity_type="lead", entity_id=lid)
        flash(f"Follow-up scheduled for {due or h.today()}.", "ok")
        return redirect(url_for("admin.leads", view="followup"))

    record("lead_outcome", f"lead={lid} {outcome}", entity_type="lead", entity_id=lid)
    flash(LEAD_OUTCOMES[outcome][1] + ".", "ok")
    return redirect(url_for("admin.leads", view=outcome if outcome in
                            ("followup", "hold", "lost") else "all"))


@bp.route("/leads/<int:lid>/delete", methods=["POST"])
@login_required
def lead_delete(lid):
    db.q("DELETE FROM leads WHERE id=?", (lid,))
    record("lead_delete", f"id={lid}")
    flash("Lead deleted.", "ok")
    return redirect(url_for("admin.leads"))


# -------------------------------------------------------------- follow-ups
@bp.route("/followups")
@login_required
def followups():
    today = h.today()
    overdue = db.q("""SELECT f.*, p.name pname, p.phone pphone, p.serial_no
        FROM followups f JOIN patients p ON p.id=f.patient_id
        WHERE f.status='pending' AND f.due_date < ? ORDER BY f.due_date, f.id""", (today,))
    due_today = db.q("""SELECT f.*, p.name pname, p.phone pphone, p.serial_no
        FROM followups f JOIN patients p ON p.id=f.patient_id
        WHERE f.status='pending' AND f.due_date = ? ORDER BY f.due_date, f.id""", (today,))
    upcoming = db.q("""SELECT f.*, p.name pname, p.phone pphone, p.serial_no
        FROM followups f JOIN patients p ON p.id=f.patient_id
        WHERE f.status='pending' AND f.due_date > ? ORDER BY f.due_date, f.id
        LIMIT 100""", (today,))
    done = db.q("""SELECT f.*, p.name pname FROM followups f
        JOIN patients p ON p.id=f.patient_id WHERE f.status='completed'
        ORDER BY f.id DESC LIMIT 30""")
    return render_template("admin/followups.html", groups=[
        ("⏰ Overdue", overdue), ("📌 Due Today", due_today), ("🗓️ Upcoming", upcoming)],
        done=done, today=today, section="followups")


@bp.route("/followups/new", methods=["POST"])
@login_required
def followup_new():
    f = request.form
    pid = f.get("patient_id")
    p = db.q("SELECT id, name FROM patients WHERE id=?", (pid,), one=True) if pid else None
    if not p:
        flash("Choose a patient.", "err")
        return redirect(url_for("admin.followups"))
    db.q("""INSERT INTO followups (patient_id, due_date, note, status, followup_type,
        purpose, created_at) VALUES (?,?,?, 'pending', 'general', ?, ?)""",
        (pid, f.get("due_date") or h.today(), f.get("note", "").strip(),
         f.get("note", "").strip(), h.now()))
    record("followup_create", f"patient={pid}", entity_type="patient", entity_id=int(pid))
    flash("Follow-up added.", "ok")
    return redirect(url_for("admin.followups"))


@bp.route("/followups/<int:fid>/complete", methods=["POST"])
@login_required
def followup_complete(fid):
    fu = db.q("SELECT * FROM followups WHERE id=?", (fid,), one=True)
    if not fu:
        abort(404)
    note = request.form.get("note", "").strip()
    db.q("UPDATE followups SET status='completed', completed_at=?, completed_by=?, "
         "note=? WHERE id=?",
         (h.now(), session.get("admin_uid"),
          (fu["note"] or "") + ((f" — {note}") if note else ""), fid))
    record("followup_complete", f"id={fid}", entity_type="patient",
           entity_id=fu["patient_id"])
    flash("Follow-up completed.", "ok")
    return redirect(url_for("admin.followups"))


@bp.route("/followups/<int:fid>/reschedule", methods=["POST"])
@login_required
def followup_reschedule(fid):
    fu = db.q("SELECT * FROM followups WHERE id=?", (fid,), one=True)
    if not fu:
        abort(404)
    new_date = request.form.get("due_date", "")
    if not new_date:
        flash("Choose a date.", "err")
        return redirect(url_for("admin.followups"))
    db.q("UPDATE followups SET due_date=?, original_due_date=COALESCE(original_due_date, "
         "due_date) WHERE id=?", (new_date, fid))
    record("followup_reschedule", f"id={fid} -> {new_date}", entity_type="patient",
           entity_id=fu["patient_id"])
    flash("Rescheduled.", "ok")
    return redirect(url_for("admin.followups"))


@bp.route("/followups/<int:fid>/delete", methods=["POST"])
@login_required
def followup_delete(fid):
    db.q("DELETE FROM followups WHERE id=?", (fid,))
    record("followup_delete", f"id={fid}")
    return redirect(url_for("admin.followups"))


# --------------------------------------------------------------- journeys
@bp.route("/journeys")
@role_required("website")
@login_required
def journeys():
    items = db.q("SELECT * FROM journeys ORDER BY id DESC")
    return render_template("admin/journeys.html", items=items, section="journeys")


@bp.route("/journeys/new", methods=["GET", "POST"])
@bp.route("/journeys/<int:jid>/edit", methods=["GET", "POST"])
@role_required("website")
@login_required
def journey_form(jid=None):
    j = db.q("SELECT * FROM journeys WHERE id=?", (jid,), one=True) if jid else None
    if jid and not j:
        abort(404)
    if request.method == "POST":
        f = request.form
        before = f.get("before_image") or (j["before_image"] if j else "")
        after = f.get("after_image") or (j["after_image"] if j else "")
        video = f.get("video") or (j["video"] if j else "")
        consent = 1 if f.get("consent_public") else 0
        vals = (f.get("title", "").strip(), f.get("patient_name", "").strip(),
                f.get("area", "").strip(), f.get("service", ""), f.get("story", ""),
                before, after, video, 1 if f.get("featured") == "1" else 0, consent)
        if not vals[0]:
            flash("Title is required", "err")
        elif not consent:
            # Publishing a patient's story requires their explicit consent —
            # never assumed, never bypassed.
            flash("You must confirm the patient gave consent to publish their story.", "err")
        elif jid:
            db.q("""UPDATE journeys SET title=?,patient_name=?,area=?,service=?,story=?,
                 before_image=?,after_image=?,video=?,featured=?,consent_public=?
                 WHERE id=?""", vals + (jid,))
            record("journey_update", f"id={jid} consent={consent}")
            flash("Journey updated", "ok")
            return redirect(url_for("admin.journeys"))
        else:
            db.q("""INSERT INTO journeys (title,patient_name,area,service,story,before_image,
                 after_image,video,featured,consent_public,created_at)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                 vals + (h.now(),))
            record("journey_create", f"title={vals[0][:60]}")
            flash("Journey published", "ok")
            return redirect(url_for("admin.journeys"))
    # Only PUBLIC website media may be attached to a public journey — private
    # patient media (scope='patient') is never offered here.
    media = db.q("SELECT * FROM media WHERE scope='public' ORDER BY id DESC")
    return render_template("admin/journey_form.html", j=j, services=_service_names(),
                           media=media, section="journeys")


@bp.route("/journeys/<int:jid>/delete", methods=["POST"])
@role_required("website")
@login_required
def journey_delete(jid):
    db.q("DELETE FROM journeys WHERE id=?", (jid,))
    record("journey_delete", f"id={jid}")
    flash("Journey removed from website", "ok")
    return redirect(url_for("admin.journeys"))


# --------------------------------------------------------------- products
@bp.route("/products")
@role_required("website")
@login_required
def products():
    items = db.q("SELECT * FROM products ORDER BY category, price_min")
    return render_template("admin/products.html", items=items, section="products")


@bp.route("/products/new", methods=["GET", "POST"])
@bp.route("/products/<int:pid>/edit", methods=["GET", "POST"])
@role_required("website")
@login_required
def product_form(pid=None):
    p = db.q("SELECT * FROM products WHERE id=?", (pid,), one=True) if pid else None
    if pid and not p:
        abort(404)
    if request.method == "POST":
        f = request.form
        image = f.get("image") or (p["image"] if p else "")
        try:
            pmin = float(f.get("price_min") or 0)
        except ValueError:
            pmin = 0
        try:
            pmax = float(f.get("price_max") or pmin)
        except ValueError:
            pmax = pmin
        if pmax < pmin:
            pmax = pmin
        vals = (f.get("name", "").strip(), f.get("category", "").strip(), f.get("brand", "").strip(),
                f.get("description", ""), pmin, pmax, image,
                1 if f.get("featured") == "1" else 0, f.get("service", ""))
        if not vals[0]:
            flash("Product name required", "err")
        elif pid:
            db.q("""UPDATE products SET name=?,category=?,brand=?,description=?,price_min=?,
                 price_max=?,image=?,featured=?,service=? WHERE id=?""", vals + (pid,))
            record("product_update", f"id={pid}")
            flash("Product updated", "ok")
            return redirect(url_for("admin.products"))
        else:
            db.q("""INSERT INTO products (name,category,brand,description,price_min,price_max,
                 image,featured,service,sort) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                 vals + (999,))
            record("product_create", f"name={vals[0][:60]}")
            flash("Product added to website", "ok")
            return redirect(url_for("admin.products"))
    cats = ["Lower Limb Prosthetics", "Upper Limb Prosthetics", "Orthotics & Braces",
            "Foot Care & Insoles", "Mobility Aids", "Accessories & Care"]
    media = db.q("SELECT * FROM media ORDER BY id DESC")
    return render_template("admin/product_form.html", p=p, services=_service_names(), cats=cats,
                           media=media, section="products")


@bp.route("/products/<int:pid>/delete", methods=["POST"])
@role_required("website")
@login_required
def product_delete(pid):
    db.q("DELETE FROM products WHERE id=?", (pid,))
    record("product_delete", f"id={pid}")
    flash("Product removed", "ok")
    return redirect(url_for("admin.products"))


# --------------------------------------------------------------- posts
@bp.route("/posts")
@role_required("website")
@login_required
def posts():
    items = db.q("SELECT * FROM posts ORDER BY id DESC")
    return render_template("admin/posts.html", items=items, section="posts")


def _slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


@bp.route("/posts/new", methods=["GET", "POST"])
@bp.route("/posts/<int:pid>/edit", methods=["GET", "POST"])
@role_required("website")
@login_required
def post_form(pid=None):
    p = db.q("SELECT * FROM posts WHERE id=?", (pid,), one=True) if pid else None
    if pid and not p:
        abort(404)
    if request.method == "POST":
        f = request.form
        title = f.get("title", "").strip()
        slug = _slugify(f.get("slug", "") or title)
        image = f.get("image") or (p["image"] if p else "")
        vals = (title, slug, f.get("excerpt", ""), f.get("body", ""), image,
                f.get("keywords", ""), f.get("status", "published"))
        if not title:
            flash("Title required", "err")
        elif not slug:
            flash("Slug required", "err")
        elif pid:
            db.q("UPDATE posts SET title=?,slug=?,excerpt=?,body=?,image=?,keywords=?,status=? WHERE id=?",
                 vals + (pid,))
            record("post_update", f"id={pid}")
            flash("Post updated", "ok")
            return redirect(url_for("admin.posts"))
        else:
            db.q("INSERT INTO posts (title,slug,excerpt,body,image,keywords,status,created_at) "
                 "VALUES (?,?,?,?,?,?,?,?)", vals + (h.now(),))
            record("post_create", f"slug={slug}")
            flash("Post published", "ok")
            return redirect(url_for("admin.posts"))
    return render_template("admin/post_form.html", p=p, section="posts")


@bp.route("/posts/<int:pid>/delete", methods=["POST"])
@role_required("website")
@login_required
def post_delete(pid):
    db.q("DELETE FROM posts WHERE id=?", (pid,))
    record("post_delete", f"id={pid}")
    flash("Post deleted", "ok")
    return redirect(url_for("admin.posts"))


# --------------------------------------------------------------- testimonials
@bp.route("/reviews")
@role_required("website")
@login_required
def reviews():
    items = db.q("SELECT * FROM testimonials ORDER BY approved ASC, id DESC")
    return render_template("admin/reviews.html", items=items, section="reviews")


@bp.route("/reviews/<int:rid>/toggle", methods=["POST"])
@role_required("website")
@login_required
def review_toggle(rid):
    db.q("UPDATE testimonials SET approved = 1 - approved WHERE id=?", (rid,))
    record("review_toggle", f"id={rid}")
    return redirect(url_for("admin.reviews"))


@bp.route("/reviews/<int:rid>/delete", methods=["POST"])
@role_required("website")
@login_required
def review_delete(rid):
    db.q("DELETE FROM testimonials WHERE id=?", (rid,))
    record("review_delete", f"id={rid}")
    return redirect(url_for("admin.reviews"))


# --------------------------------------------------------------- media
@bp.route("/media", methods=["GET", "POST"])
@role_required("website")
@login_required
def media():
    if request.method == "POST":
        files = request.files.getlist("files")
        is_private = 1 if request.form.get("is_private") == "1" else 0
        saved = 0
        for file in files:
            if not file or not file.filename:
                continue
            ok, err = up.validate_upload(file)
            if not ok:
                flash(f"Rejected '{file.filename}': {err}", "err")
                record("upload_rejected", f"file={file.filename[:80]} reason={err[:80]}")
                continue
            fname = up.save_upload(file)
            kind = up.ALLOWED[up.extension_of(file.filename)][1]
            up.register_media(fname, file.filename, kind, h.now(), is_private)
            if request.form.get("show_gallery") == "1":
                db.q("UPDATE media SET category='gallery' WHERE filename=?", (fname,))
            saved += 1
        if saved:
            record("upload", f"count={saved} private={bool(is_private)}")
            flash(f"{saved} file(s) uploaded", "ok")
        return redirect(url_for("admin.media"))
    # Website Media Library shows PUBLIC media only. Private patient media lives
    # on the patient profile and is never listed here (strict separation).
    items = db.q("SELECT * FROM media WHERE scope='public' ORDER BY id DESC")
    return render_template("admin/media.html", items=items, section="media")


@bp.route("/media/<int:mid>/delete", methods=["POST"])
@role_required("website")
@login_required
def media_delete(mid):
    m = db.q("SELECT * FROM media WHERE id=?", (mid,), one=True)
    if m:
        try:
            os.remove(os.path.join(up.storage_path(m["filename"])))
        except OSError:
            pass
        db.q("DELETE FROM media WHERE id=?", (mid,))
        record("media_delete", f"id={mid}")
    flash("Media deleted", "ok")
    return redirect(url_for("admin.media"))


# --------------------------------------------------------------- settings
_SETTING_KEYS = ("phone", "phone2", "whatsapp", "email", "address", "hours", "map_url",
                 "gmb_url", "facebook", "instagram", "youtube", "domain")


@bp.route("/settings", methods=["GET", "POST"])
@role_required("settings")
@login_required
def settings():
    from ..security import hash_password, get_current_admin
    if request.method == "POST":
        # All settings writes run atomically.
        with db.transaction() as conn:
            for k in _SETTING_KEYS:
                v = request.form.get(k, "").strip()
                db.q("INSERT INTO settings (key, value) VALUES (?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", (k, v), conn=conn)
            new_user = request.form.get("admin_user", "").strip()
            new_pass = request.form.get("admin_pass", "")
            me = get_current_admin()
            if me:
                if new_user:
                    db.q("UPDATE users SET username=? WHERE id=?", (new_user, me["id"]), conn=conn)
                if new_pass:
                    db.q("UPDATE users SET password_hash=? WHERE id=?",
                         (hash_password(new_pass), me["id"]), conn=conn)
        record("settings_update", "clinic settings changed")
        flash("Settings saved", "ok")
        return redirect(url_for("admin.settings"))
    vals = {k: h.setting(k) for k in _SETTING_KEYS}
    me = get_current_admin()
    vals["admin_user"] = me["username"] if me else ""
    return render_template("admin/settings.html", vals=vals, section="settings")




# ------------------------------------------------------------------ staff & assignment
STAFF_CAP_OPTIONS = [
    ("leads", "See assigned leads & add new leads"),
    ("leads_edit", "Update lead outcomes & notes"),
    ("patients", "See patients"),
    ("followups", "Manage follow-ups"),
    ("reports", "See staff performance report"),
]


@bp.route("/leads/assign", methods=["POST"])
@role_required("staff")
def lead_assign():
    ids = [int(i) for i in request.form.getlist("lead_ids") if str(i).isdigit()]
    uid = request.form.get("assigned_to", "").strip()
    target = int(uid) if uid.isdigit() else None
    if target:
        u = db.q("SELECT id, is_active FROM users WHERE id=?", (target,), one=True)
        if not u or not u["is_active"]:
            flash("Choose a valid active staff member.", "err")
            return redirect(url_for("admin.leads"))
    if ids:
        if target:
            db.q(f"UPDATE leads SET assigned_to=? WHERE id IN ({','.join('?' * len(ids))})",
                 (target, *ids))
        else:
            db.q(f"UPDATE leads SET assigned_to=NULL WHERE id IN ({','.join('?' * len(ids))})",
                 tuple(ids))
        record("lead_assign", f"count={len(ids)} to={target or 'none'}",
               entity_type="lead", entity_id=ids[0])
        flash(f"{len(ids)} lead(s) " + (f"assigned to user #{target}." if target else "unassigned."), "ok")
    return redirect(url_for("admin.leads"))


@bp.route("/leads/<int:lid>/assign_one", methods=["POST"])
@role_required("staff")
def lead_assign_one(lid):
    uid = request.form.get("assigned_to", "").strip()
    target = int(uid) if uid.isdigit() else None
    db.q("UPDATE leads SET assigned_to=? WHERE id=?", (target, lid))
    record("lead_assign", f"lead={lid} to={target or 'none'}",
           entity_type="lead", entity_id=lid)
    who = db.q("SELECT full_name, username FROM users WHERE id=?", (target,), one=True) if target else None
    flash("Lead assigned to " + (who["full_name"] or who["username"]) + "." if who else "Lead unassigned.", "ok")
    return redirect(url_for("admin.leads"))


@bp.route("/staff")
@role_required("staff")
def staff():
    users = db.q("""SELECT u.id, u.username, u.full_name, u.role, u.caps, u.is_active,
        u.created_at, (SELECT COUNT(*) FROM leads l WHERE l.assigned_to=u.id) lead_count
        FROM users u ORDER BY u.id""")
    return render_template("admin/staff.html", users=users,
                           cap_options=STAFF_CAP_OPTIONS, section="staff")


@bp.route("/staff/save", methods=["POST"])
@role_required("staff")
def staff_save():
    f = request.form
    uid = f.get("uid", "").strip()
    username = (f.get("username") or "").strip()
    full_name = (f.get("full_name") or "").strip()
    caps = ",".join(c for c, _ in STAFF_CAP_OPTIONS if f.get(f"cap_{c}") == "1") or "leads"
    if not username or len(username) < 3:
        flash("Username must be at least 3 characters.", "err")
        return redirect(url_for("admin.staff"))
    dup = db.q("SELECT id FROM users WHERE username=? AND (? = '' OR id <> ?)",
               (username, uid, int(uid) if uid.isdigit() else 0), one=True)
    if dup:
        flash("That username already exists.", "err")
        return redirect(url_for("admin.staff"))
    if uid.isdigit():
        if int(uid) == session["admin_uid"]:
            flash("You cannot change your own account here.", "err")
            return redirect(url_for("admin.staff"))
        db.q("UPDATE users SET username=?, full_name=?, caps=? WHERE id=?",
             (username, full_name, caps, int(uid)))
        pw = (f.get("password") or "").strip()
        if pw:
            if len(pw) < 8:
                flash("New password must be at least 8 characters.", "err")
                return redirect(url_for("admin.staff"))
            db.q("UPDATE users SET password_hash=? WHERE id=?",
                 (security.hash_password(pw), int(uid)))
        record("staff_update", f"user={username}")
        flash(f"Staff '{username}' updated.", "ok")
    else:
        pw = (f.get("password") or "").strip()
        if len(pw) < 8:
            flash("Password must be at least 8 characters.", "err")
            return redirect(url_for("admin.staff"))
        db.q("INSERT INTO users (username, password_hash, role, full_name, caps, is_active, created_at) "
             "VALUES (?, ?, 'staff', ?, ?, 1, ?)",
             (username, security.hash_password(pw), full_name, caps, h.now()))
        record("staff_create", f"user={username} caps={caps}")
        flash(f"Staff account '{username}' created — they can log in now.", "ok")
    return redirect(url_for("admin.staff"))


@bp.route("/staff/<int:uid>/toggle", methods=["POST"])
@role_required("staff")
def staff_toggle(uid):
    if uid == session["admin_uid"]:
        flash("You cannot disable your own account.", "err")
        return redirect(url_for("admin.staff"))
    u = db.q("SELECT is_active, username FROM users WHERE id=?", (uid,), one=True)
    if u:
        db.q("UPDATE users SET is_active=? WHERE id=?", (0 if u["is_active"] else 1, uid))
        record("staff_toggle", f"user={u['username']} active={0 if u['is_active'] else 1}")
        flash(f"'{u['username']}' " + ("disabled." if u["is_active"] else "re-enabled."), "ok")
    return redirect(url_for("admin.staff"))


@bp.route("/performance")
@role_required("reports")
def performance():
    rng = request.args.get("range", "month")
    where, args = "", ()
    if rng == "month":
        where, args = "WHERE l.created_at >= date_trunc('month', now())", ()
    elif rng == "week":
        where, args = "WHERE l.created_at >= now() - interval '7 days'", ()
    staff_rows = db.q("SELECT id, username, full_name, is_active FROM users "
                      "WHERE role='staff' ORDER BY id")
    stats = []
    for u in staff_rows:
        lead = db.q(f"SELECT COUNT(*) c FROM leads l {where.replace('l.created_at', 'l.created_at')} "
                    + (" AND" if where else " WHERE") + " l.assigned_to=?",
                    (*args, u["id"]), one=True)["c"]
        hist = db.q("""SELECT outcome, COUNT(*) c FROM lead_history hh
            JOIN leads l ON l.id=hh.lead_id WHERE l.assigned_to=? GROUP BY outcome""",
            (u["id"],))
        hm = {r["outcome"]: r["c"] for r in hist}
        done = db.q("SELECT COUNT(*) c FROM leads l WHERE l.assigned_to=? AND l.converted_at IS NOT NULL",
                    (u["id"],), one=True)["c"]
        last = db.q("""SELECT MAX(hh.created_at) t FROM lead_history hh
            JOIN leads l ON l.id=hh.lead_id WHERE l.assigned_to=?""", (u["id"],), one=True)["t"]
        stats.append(dict(id=u["id"], name=u["full_name"] or u["username"],
                          active=u["is_active"], assigned=lead,
                          appt=hm.get("appointment", 0), fu=hm.get("followup", 0),
                          hold=hm.get("hold", 0), lost=hm.get("lost", 0),
                          done=done, last=last))
    return render_template("admin/performance.html", stats=stats, rng=rng,
                           section="performance")
