"""Admin panel routes — simple CRM (leads -> pipeline -> lifetime patient file).

Every route is behind :func:`security.login_required`. State-changing actions
are POST-only, CSRF-protected (Flask-WTF), and audited.
"""
import datetime as dt
import os
import math
import re

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template, request,
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
    if plat == "website" or "website" in src:
        return "🌐 Website Consultation"
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
        "patients": db.q("SELECT COUNT(*) c FROM patients WHERE is_confirmed=1 AND status<>'lead'", one=True)["c"],
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
    if not has_cap("patients"):
        abort(403)
    q = request.args.get("q", "").strip()
    stage_f = request.args.get("stage", "").strip()
    due_f = request.args.get("due", "").strip()
    status_f = request.args.get("status", "").strip()

    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1
    limit_arg = request.args.get("limit", "50").strip().lower()
    if limit_arg == "all":
        limit = 500
    else:
        try:
            limit = int(limit_arg)
            if limit not in (10, 25, 50, 100, 200, 500):
                limit = 50
        except ValueError:
            limit = 50

    sort_col = request.args.get("sort", "id").strip().lower()
    sort_order = request.args.get("order", "desc").strip().lower()
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"

    sort_map = {
        "id": "p.id",
        "serial_no": "p.serial_no",
        "name": "p.name",
        "phone": "p.phone",
        "area": "p.area",
        "age": "p.age",
        "gender": "p.gender",
        "status": "p.status",
        "stage": "p.pipeline_stage",
        "pipeline_stage": "p.pipeline_stage",
        "next_followup": "p.next_followup",
        "source": "p.source",
        "balance": "(COALESCE(p.total_amount, 0) - COALESCE(p.advance_amount, 0))",
        "created_at": "p.created_at"
    }
    order_sql = f"{sort_map.get(sort_col, 'p.id')} {sort_order.upper()}"

    where = " WHERE p.is_confirmed=1 AND p.status<>'lead'"
    args = []

    if q:
        like = f"%{q}%"
        phone_like = f"%{q.replace(' ', '').replace('+', '')}%"
        where += """ AND (p.serial_no LIKE ?
            OR REPLACE(REPLACE(p.phone,' ',''),'+','') LIKE ?
            OR p.name ILIKE ?
            OR p.area ILIKE ?
            OR p.notes ILIKE ?
            OR CAST(p.id AS TEXT) LIKE ?)"""
        args.extend([like, phone_like, like, like, like, like])

    if stage_f and stage_f != "all":
        if stage_f == "active":
            where += " AND p.pipeline_stage<>'' AND p.pipeline_stage<>'completed'"
        elif stage_f == "completed":
            where += " AND p.pipeline_stage='completed'"
        elif stage_f in PIPELINE_STAGES:
            where += " AND p.pipeline_stage=?"
            args.append(stage_f)

    if due_f == "1":
        where += " AND (COALESCE(p.total_amount, 0) - COALESCE(p.advance_amount, 0)) > 0"

    if status_f and status_f != "all":
        where += " AND p.status=?"
        args.append(status_f)

    count_sql = f"SELECT COUNT(*) c FROM patients p{where}"
    total_count = db.q(count_sql, tuple(args), one=True)["c"]
    total_pages = max(1, math.ceil(total_count / limit)) if limit else 1
    if page > total_pages:
        page = total_pages
    offset = (page - 1) * limit

    sql = f"""SELECT p.*,
        (SELECT due_date FROM followups WHERE patient_id=p.id AND status='pending' ORDER BY due_date ASC LIMIT 1) fu_next,
        (SELECT note FROM followups WHERE patient_id=p.id ORDER BY id DESC LIMIT 1) fu_last_note,
        (SELECT created_at FROM followups WHERE patient_id=p.id ORDER BY id DESC LIMIT 1) fu_last_date
        FROM patients p{where} ORDER BY {order_sql} LIMIT ? OFFSET ?"""
    page_args = list(args) + [limit, offset]
    rows = db.q(sql, tuple(page_args))

    c_res = db.q("""SELECT
        COUNT(*) FILTER (WHERE is_confirmed=1 AND status<>'lead') AS c_all,
        COUNT(*) FILTER (WHERE is_confirmed=1 AND status<>'lead' AND pipeline_stage<>'' AND pipeline_stage<>'completed') AS c_active,
        COUNT(*) FILTER (WHERE is_confirmed=1 AND status<>'lead' AND pipeline_stage='completed') AS c_completed,
        COUNT(*) FILTER (WHERE is_confirmed=1 AND status<>'lead' AND (COALESCE(total_amount,0) - COALESCE(advance_amount,0)) > 0) AS c_due
        FROM patients""", one=True)
    counts = {
        "all": c_res["c_all"] if c_res else 0,
        "active": c_res["c_active"] if c_res else 0,
        "completed": c_res["c_completed"] if c_res else 0,
        "due": c_res["c_due"] if c_res else 0,
    }

    start_idx = offset + 1 if total_count > 0 else 0
    end_idx = min(offset + limit, total_count)

    sources = [x["name"] for x in db.q("SELECT name FROM sources WHERE is_active=1 ORDER BY sort_order")]
    if not sources:
        sources = ['Walk-in', 'WhatsApp', 'Doctor Referral', 'Patient Referral', 'Website', 'Other']

    stage_options = [{"id": s, "name": PIPELINE_LABELS.get(s, s)} for s in PIPELINE_STAGES]

    return render_template("admin/patients.html", rows=rows, q=q,
                           page=page, limit=limit, limit_arg=limit_arg,
                           total_count=total_count, total_pages=total_pages,
                           start_idx=start_idx, end_idx=end_idx,
                           sort=sort_col, order=sort_order,
                           stage_f=stage_f, due_f=due_f, status_f=status_f,
                           counts=counts, stages=PIPELINE_LABELS,
                           pipeline_stages=PIPELINE_STAGES,
                           stage_options=stage_options,
                           sources=sources, today=h.today(), section="patients")


@bp.route("/patients/<int:pid>/inline", methods=["POST"])
@login_required
def patient_inline(pid):
    if not has_cap("patients_edit") and not has_cap("patients"):
        return jsonify({"ok": False, "error": "Permission denied"}), 403

    p = db.q("SELECT * FROM patients WHERE id=?", (pid,), one=True)
    if not p:
        return jsonify({"ok": False, "error": "Patient not found"}), 404

    data = request.get_json(silent=True) or request.form
    field = (data.get("field") or "").strip().lower()
    value = (data.get("value") or "").strip()

    allowed = {
        "name", "phone", "area", "age", "gender", "status",
        "pipeline_stage", "next_followup", "notes", "source"
    }
    if field not in allowed:
        return jsonify({"ok": False, "error": f"Field '{field}' cannot be edited inline"}), 400

    display_value = value

    if field == "name":
        if not value:
            return jsonify({"ok": False, "error": "Name cannot be empty"}), 400
        db.q("UPDATE patients SET name=? WHERE id=?", (value, pid))
    elif field == "phone":
        db.q("UPDATE patients SET phone=? WHERE id=?", (value, pid))
    elif field == "area":
        db.q("UPDATE patients SET area=? WHERE id=?", (value, pid))
    elif field == "age":
        db.q("UPDATE patients SET age=? WHERE id=?", (value, pid))
    elif field == "gender":
        if value not in ("Male", "Female", "Other", ""):
            return jsonify({"ok": False, "error": "Invalid gender"}), 400
        db.q("UPDATE patients SET gender=? WHERE id=?", (value, pid))
    elif field == "status":
        valid_status = {"active", "lead", "completed", "archived", "inactive"}
        if value.lower() not in valid_status:
            return jsonify({"ok": False, "error": "Invalid status"}), 400
        db.q("UPDATE patients SET status=? WHERE id=?", (value.lower(), pid))
        display_value = value.lower()
    elif field == "pipeline_stage":
        if value and value not in PIPELINE_STAGES:
            return jsonify({"ok": False, "error": "Invalid pipeline stage"}), 400
        old_stage = p.get("pipeline_stage") or ""
        db.q("UPDATE patients SET pipeline_stage=?, stage_updated_at=? WHERE id=?",
             (value, h.now(), pid))
        if value != old_stage:
            db.q("INSERT INTO patient_stage_log (patient_id, stage, note, created_at) VALUES (?, ?, 'Inline stage change', ?)",
                 (pid, value, h.now()))
        display_value = PIPELINE_LABELS.get(value, value)
    elif field == "next_followup":
        val = value if value else None
        db.q("UPDATE patients SET next_followup=? WHERE id=?", (val, pid))
    elif field == "source":
        db.q("UPDATE patients SET source=? WHERE id=?", (value, pid))
    elif field == "notes":
        db.q("UPDATE patients SET notes=? WHERE id=?", (value, pid))

    record("patient_inline_edit", f"id={pid} field={field} val={value[:50]}", entity_type="patient", entity_id=pid)
    return jsonify({"ok": True, "field": field, "value": value, "display_value": display_value})


@bp.route("/patients/<int:pid>/history-json")
@login_required
def patient_history_json(pid):
    if not has_cap("patients"):
        return jsonify({"ok": False, "error": "Unauthorized"}), 403
    p = db.q("SELECT id, serial_no, name, phone, pipeline_stage FROM patients WHERE id=?", (pid,), one=True)
    if not p:
        return jsonify({"ok": False, "error": "Patient not found"}), 404
    fups = db.q("SELECT * FROM followups WHERE patient_id=? ORDER BY id DESC", (pid,))
    items = []
    for fu in fups:
        items.append({
            "id": fu["id"],
            "note": fu.get("note") or "",
            "due_date": str(fu["due_date"]) if fu.get("due_date") else "",
            "status": fu.get("status") or "pending",
            "date": str(fu.get("created_at") or "")[:10]
        })
    return jsonify({
        "ok": True,
        "patient": {"id": p["id"], "serial_no": p["serial_no"], "name": p["name"], "phone": p["phone"]},
        "followups": items
    })

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
        is_confirmed, created_at) VALUES (?,?,?,?,?, 'active', 'complete', ?, ?, 'consultation', ?, 1, ?)
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
    interactions = db.q("""SELECT lh.*, l.source lead_source, u.full_name staff_name, u.username staff_user
        FROM lead_history lh
        JOIN leads l ON l.id=lh.lead_id
        LEFT JOIN users u ON u.id=lh.logged_by
        WHERE l.patient_id=?
        ORDER BY COALESCE(lh.interaction_at, lh.created_at) DESC, lh.id DESC""", (pid,))
    balance = float(p["total_amount"] or 0) - float(p["advance_amount"] or 0)
    try:
        current_idx = PIPELINE_STAGES.index(p["pipeline_stage"])
    except ValueError:
        current_idx = -1
    return render_template("admin/patient_detail.html", p=p, history=history, fups=fups,
                           leads=leads, interactions=interactions, balance=balance, stages=PIPELINE_STAGES,
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
    view = request.args.get("view", "all").strip().lower()
    staff_filter = request.args.get("staff", "")
    type_f = request.args.get("t", "")
    src_f = request.args.get("src", "").strip()
    q = request.args.get("q", "").strip()
    section_type = request.args.get("section_type", "all").strip().lower()
    if section_type not in ("all", "whatsapp", "manual"):
        section_type = "all"
    scoped_uid = None if security.current_role() == "super_admin"         else session["admin_uid"]

    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1
    limit_arg = request.args.get("limit", "50").strip().lower()
    if limit_arg == "all":
        limit = 500
    else:
        try:
            limit = int(limit_arg)
            if limit not in (10, 25, 50, 100, 200, 500):
                limit = 50
        except ValueError:
            limit = 50

    sort_col = request.args.get("sort", "id").strip().lower()
    sort_order = request.args.get("order", "desc").strip().lower()
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"

    sort_map = {
        "id": "l.id",
        "name": "COALESCE(NULLIF(l.name, ''), p.name, '')",
        "phone": "COALESCE(NULLIF(l.phone, ''), p.phone, '')",
        "area": "COALESCE(NULLIF(l.area, ''), p.area, '')",
        "source": "l.source",
        "interest": "l.interest",
        "status": "l.status",
        "assigned": "su.full_name",
        "assigned_to": "su.full_name",
        "last_contact": "(SELECT interaction_at FROM lead_history WHERE lead_id=l.id ORDER BY id DESC LIMIT 1)",
        "next_followup": "COALESCE(l.next_followup, (SELECT due_date FROM lead_history WHERE lead_id=l.id AND due_date IS NOT NULL ORDER BY id DESC LIMIT 1))",
        "created_at": "l.created_at"
    }
    order_sql = f"{sort_map.get(sort_col, 'l.id')} {sort_order.upper()}"

    base = """SELECT l.id, l.status, l.source, l.platform, l.interest, l.notes, l.created_at,
        l.assigned_to, l.next_followup, l.converted_at,
        COALESCE(NULLIF(l.name, ''), p.name, '') pname,
        COALESCE(NULLIF(l.phone, ''), p.phone, '') pphone,
        COALESCE(NULLIF(l.whatsapp, ''), p.whatsapp, '') pwhatsapp,
        COALESCE(NULLIF(l.email, ''), p.email, '') pemail,
        COALESCE(NULLIF(l.area, ''), p.area, '') area,
        su.username assigned_name, su.full_name assigned_full_name,
        p.id pid, p.serial_no, p.pipeline_stage, p.is_confirmed,
        (SELECT note FROM lead_history WHERE lead_id=l.id ORDER BY id DESC LIMIT 1) last_note,
        (SELECT summary FROM lead_history WHERE lead_id=l.id AND summary<>'' ORDER BY id DESC LIMIT 1) last_summary,
        (SELECT outcome FROM lead_history WHERE lead_id=l.id ORDER BY id DESC LIMIT 1) last_outcome,
        (SELECT interaction_type FROM lead_history WHERE lead_id=l.id ORDER BY id DESC LIMIT 1) last_interaction_type,
        (SELECT interaction_at FROM lead_history WHERE lead_id=l.id ORDER BY id DESC LIMIT 1) last_contact_at,
        COALESCE(l.next_followup, (SELECT due_date FROM lead_history WHERE lead_id=l.id AND due_date IS NOT NULL ORDER BY id DESC LIMIT 1)) last_due_date,
        (SELECT COUNT(*) FROM lead_history WHERE lead_id=l.id) history_count
        FROM leads l LEFT JOIN patients p ON p.id=l.patient_id
        LEFT JOIN users su ON su.id=l.assigned_to"""
    filters = {
        "all": " WHERE 1=1",
        "new": " WHERE l.status='new'",
        "contacted": " WHERE l.status='contacted'",
        "followup": " WHERE (l.status='followup' OR (l.next_followup IS NOT NULL AND l.next_followup <= CURRENT_DATE AND l.status NOT IN ('converted','lost')))",
        "appointment": " WHERE l.status IN ('appointment','appointment_scheduled')",
        "assessment": " WHERE l.status='assessment'",
        "converted": " WHERE l.status='converted'",
        "hold": " WHERE l.status='hold'",
        "lost": " WHERE l.status IN ('lost','not_interested')",
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
        where += """ AND (COALESCE(NULLIF(l.name, ''), p.name, '') ILIKE ?
            OR COALESCE(NULLIF(l.phone, ''), p.phone, '') ILIKE ?
            OR COALESCE(NULLIF(l.area, ''), p.area, '') ILIKE ?
            OR CAST(l.id AS TEXT) ILIKE ?
            OR CAST(p.serial_no AS TEXT) ILIKE ?
            OR l.notes ILIKE ?)"""
        like = f"%{q}%"
        args.extend([like, like, like, like, like, like])
    if section_type == "whatsapp":
        where += " AND (l.platform='whatsapp' OR l.source ILIKE '%whatsapp%')"
    elif section_type == "manual":
        where += " AND NOT (l.platform='whatsapp' OR l.source ILIKE '%whatsapp%')"

    count_sql = f"SELECT COUNT(*) c FROM leads l LEFT JOIN patients p ON p.id=l.patient_id LEFT JOIN users su ON su.id=l.assigned_to{where}"
    total_count = db.q(count_sql, tuple(args), one=True)["c"]
    total_pages = max(1, math.ceil(total_count / limit)) if limit else 1
    if page > total_pages:
        page = total_pages
    offset = (page - 1) * limit

    sql = base + where + f" ORDER BY {order_sql} LIMIT ? OFFSET ?"
    page_args = list(args) + [limit, offset]
    rows = db.q(sql, tuple(page_args))

    cargs = [scoped_uid] if scoped_uid else ([int(staff_filter)] if staff_filter.isdigit() else [])
    c_where = " WHERE assigned_to=?" if cargs else ""
    c_res = db.q(f"""SELECT
        COUNT(*) AS c_all,
        COUNT(*) FILTER (WHERE status='new') AS c_new,
        COUNT(*) FILTER (WHERE status='contacted') AS c_contacted,
        COUNT(*) FILTER (WHERE status='followup' OR (next_followup IS NOT NULL AND next_followup <= CURRENT_DATE AND status NOT IN ('converted','lost'))) AS c_followup,
        COUNT(*) FILTER (WHERE status IN ('appointment','appointment_scheduled')) AS c_appointment,
        COUNT(*) FILTER (WHERE status='assessment') AS c_assessment,
        COUNT(*) FILTER (WHERE status='converted') AS c_converted,
        COUNT(*) FILTER (WHERE status='hold') AS c_hold,
        COUNT(*) FILTER (WHERE status IN ('lost','not_interested')) AS c_lost,
        COUNT(*) FILTER (WHERE platform='whatsapp' OR source ILIKE '%whatsapp%') AS c_whatsapp
        FROM leads{c_where}""", tuple(cargs), one=True)
    counts = {
        "all": c_res["c_all"] if c_res else 0,
        "new": c_res["c_new"] if c_res else 0,
        "contacted": c_res["c_contacted"] if c_res else 0,
        "followup": c_res["c_followup"] if c_res else 0,
        "appointment": c_res["c_appointment"] if c_res else 0,
        "assessment": c_res["c_assessment"] if c_res else 0,
        "converted": c_res["c_converted"] if c_res else 0,
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

    staff = [] if scoped_uid else db.q(
        "SELECT id, username, full_name FROM users WHERE is_active=1 ORDER BY id")

    start_idx = offset + 1 if total_count > 0 else 0
    end_idx = min(offset + limit, total_count)

    return render_template("admin/leads.html", rows=rows, wa_leads=wa_leads, manual_leads=manual_leads,
                           view=view, counts=counts, section_type=section_type,
                           sources=[x["name"] for x in db.q(
                               "SELECT name FROM sources WHERE is_active=1 ORDER BY sort_order")],
                           today=h.today(), section="leads", staff=staff,
                           scoped=bool(scoped_uid), staff_filter=staff_filter,
                           type_f=type_f, src_f=src_f, q=q, lead_types=h.LEAD_TYPES,
                           page=page, limit=limit, limit_arg=limit_arg,
                           total_count=total_count, total_pages=total_pages,
                           start_idx=start_idx, end_idx=end_idx,
                           sort=sort_col, order=sort_order)


@bp.route("/leads/<int:lid>/inline", methods=["POST"])
@login_required
def lead_inline(lid):
    if not has_cap("leads_edit"):
        return jsonify({"ok": False, "error": "Permission denied"}), 403

    lead = db.q("""SELECT l.*, p.id pid, p.name pname FROM leads l
        LEFT JOIN patients p ON p.id=l.patient_id WHERE l.id=?""", (lid,), one=True)
    if not lead:
        return jsonify({"ok": False, "error": "Lead not found"}), 404

    if security.current_role() != "super_admin" and             (lead["assigned_to"] or 0) != session["admin_uid"] and lead["assigned_to"] is not None:
        return jsonify({"ok": False, "error": "You are not assigned to this lead"}), 403

    data = request.get_json(silent=True) or request.form
    field = (data.get("field") or "").strip().lower()
    value = (data.get("value") or "").strip()

    allowed = {
        "name", "phone", "area", "whatsapp", "email",
        "source", "interest", "status", "assigned_to",
        "next_followup", "notes"
    }
    if field not in allowed:
        return jsonify({"ok": False, "error": f"Field '{field}' cannot be edited inline"}), 400

    display_value = value

    if field == "name":
        if not value:
            return jsonify({"ok": False, "error": "Name cannot be empty"}), 400
        db.q("UPDATE leads SET name=? WHERE id=?", (value, lid))
        if lead.get("patient_id"):
            db.q("UPDATE patients SET name=? WHERE id=?", (value, lead["patient_id"]))
    elif field == "phone":
        if not value:
            return jsonify({"ok": False, "error": "Phone number cannot be empty"}), 400
        db.q("UPDATE leads SET phone=? WHERE id=?", (value, lid))
        if lead.get("patient_id"):
            db.q("UPDATE patients SET phone=? WHERE id=?", (value, lead["patient_id"]))
    elif field == "area":
        db.q("UPDATE leads SET area=? WHERE id=?", (value, lid))
        if lead.get("patient_id"):
            db.q("UPDATE patients SET area=? WHERE id=?", (value, lead["patient_id"]))
    elif field == "whatsapp":
        db.q("UPDATE leads SET whatsapp=? WHERE id=?", (value, lid))
        if lead.get("patient_id"):
            db.q("UPDATE patients SET whatsapp=? WHERE id=?", (value, lead["patient_id"]))
    elif field == "email":
        db.q("UPDATE leads SET email=? WHERE id=?", (value, lid))
        if lead.get("patient_id"):
            db.q("UPDATE patients SET email=? WHERE id=?", (value, lead["patient_id"]))
    elif field == "source":
        db.q("UPDATE leads SET source=? WHERE id=?", (value, lid))
    elif field == "interest":
        db.q("UPDATE leads SET interest=? WHERE id=?", (value, lid))
    elif field == "status":
        valid_statuses = ["new", "contacted", "followup", "appointment", "assessment", "converted", "hold", "lost", "not_interested"]
        if value.lower() not in valid_statuses:
            return jsonify({"ok": False, "error": "Invalid status"}), 400
        val = value.lower()
        db.q("UPDATE leads SET status=? WHERE id=?", (val, lid))
        display_value = val.title()
    elif field == "assigned_to":
        val = int(value) if value and value.isdigit() else None
        if val:
            staff_row = db.q("SELECT id, full_name, username FROM users WHERE id=?", (val,), one=True)
            if not staff_row:
                return jsonify({"ok": False, "error": "Staff member not found"}), 400
            display_value = staff_row.get("full_name") or staff_row.get("username")
        else:
            display_value = "Unassigned"
        db.q("UPDATE leads SET assigned_to=? WHERE id=?", (val, lid))
    elif field == "next_followup":
        val = value if value else None
        db.q("UPDATE leads SET next_followup=? WHERE id=?", (val, lid))
    elif field == "notes":
        db.q("UPDATE leads SET notes=? WHERE id=?", (value, lid))

    record("lead_inline_edit", f"id={lid} field={field} val={value[:50]}", entity_type="lead", entity_id=lid)
    return jsonify({"ok": True, "field": field, "value": value, "display_value": display_value})


@bp.route("/leads/bulk-status", methods=["POST"])
@login_required
def leads_bulk_status():
    if not has_cap("leads_edit"):
        abort(403)
    status = request.form.get("status", "").strip().lower()
    valid_statuses = ["new", "contacted", "followup", "appointment", "assessment", "hold", "lost"]
    if status not in valid_statuses:
        flash("Invalid status selected.", "err")
        return redirect(url_for("admin.leads"))
    lead_ids = request.form.getlist("lead_ids")
    updated = 0
    for lid in lead_ids:
        if lid.isdigit():
            db.q("UPDATE leads SET status=? WHERE id=?", (status, int(lid)))
            updated += 1
    record("leads_bulk_status", f"status={status} count={updated}")
    flash(f"Updated status to '{status.title()}' for {updated} lead(s).", "ok")
    return redirect(url_for("admin.leads"))


@bp.route("/leads/<int:lid>/history-json")
@login_required
def lead_history_json(lid):
    if not has_cap("leads"):
        return jsonify({"ok": False, "error": "Unauthorized"}), 403
    lead = db.q("""SELECT l.id,
        COALESCE(NULLIF(l.name, ''), p.name, '') name,
        COALESCE(NULLIF(l.phone, ''), p.phone, '') phone,
        l.status, l.source, l.created_at
        FROM leads l LEFT JOIN patients p ON p.id=l.patient_id WHERE l.id=?""", (lid,), one=True)
    if not lead:
        return jsonify({"ok": False, "error": "Lead not found"}), 404
    history = db.q("""SELECT lh.*, u.full_name staff_name, u.username staff_user
        FROM lead_history lh
        LEFT JOIN users u ON u.id=lh.logged_by
        WHERE lh.lead_id=?
        ORDER BY COALESCE(lh.interaction_at, lh.created_at) DESC, lh.id DESC""", (lid,))
    items = []
    for h_row in history:
        items.append({
            "id": h_row["id"],
            "interaction_type": h_row.get("interaction_type") or "other",
            "summary": h_row.get("summary") or h_row.get("note") or "",
            "outcome": h_row.get("outcome") or "",
            "due_date": str(h_row["due_date"]) if h_row.get("due_date") else None,
            "staff": h_row.get("staff_name") or h_row.get("staff_user") or "Staff",
            "date": str(h_row.get("interaction_at") or h_row.get("created_at") or "")[:16]
        })
    return jsonify({
        "ok": True,
        "lead": {
            "id": lead["id"],
            "name": lead["name"],
            "phone": lead["phone"],
            "status": lead["status"],
            "source": lead["source"]
        },
        "history": items
    })

@bp.route("/leads/new", methods=["POST"])
@login_required
def lead_new():
    if not has_cap("leads_edit"):
        abort(403)
    f = request.form
    name = f.get("name", "").strip()
    if not name:
        flash("Name is required.", "err")
        return redirect(url_for("admin.leads"))
    phone = f.get("phone", "").strip()
    whatsapp = f.get("whatsapp", "").strip() or phone
    email = f.get("email", "").strip()
    area = f.get("area", "").strip()
    source = f.get("source", "").strip() or "Walk-in"
    notes = f.get("notes", "").strip()
    interest = (f.get("interest") or "").strip() or h.detect_lead_type(notes)
    assign_val = f.get("assigned_to", "").strip()
    assigned_to = int(assign_val) if assign_val.isdigit() else None
    next_fu = f.get("next_followup", "").strip() or None

    # Link to existing patient if phone matches; else create unconfirmed internal record
    pid = None
    if phone:
        norm = phone.replace(" ", "").replace("+", "").replace("-", "").strip()
        p = db.q("""SELECT id, is_confirmed FROM patients
            WHERE REPLACE(REPLACE(REPLACE(phone,' ',''),'+',''),'-','')=?""", (norm,), one=True)
        pid = p["id"] if p else None
    if not pid:
        serial = h.next_serial_no()
        pid = db.q("""INSERT INTO patients (name, phone, whatsapp, email, area, source, status,
            profile_status, patient_code, serial_no, pipeline_stage, is_confirmed, created_at)
            VALUES (?,?,?,?,?,?, 'lead', 'incomplete', ?, ?, '', 0, ?) RETURNING id""",
            (name, phone, whatsapp, email, area, source,
             h.next_patient_code(), serial, h.now()))[0]["id"]

    lid = db.q("""INSERT INTO leads (patient_id, name, phone, whatsapp, email, area, source, platform, status, interest, notes, assigned_to, next_followup, created_at)
        VALUES (?,?,?,?,?,?,?, '', 'new', ?, ?, ?, ?, ?) RETURNING id""",
        (pid, name, phone, whatsapp, email, area, source, interest, notes, assigned_to, next_fu, h.now()))[0]["id"]

    # Initial interaction entry in lead_history
    if notes:
        db.q("""INSERT INTO lead_history (lead_id, outcome, note, summary, interaction_type, due_date, logged_by, interaction_at, created_at)
             VALUES (?, 'new', ?, ?, 'note', ?, ?, ?, ?)""",
             (lid, notes, notes, next_fu, session.get("admin_uid"), h.now(), h.now()))

    # Schedule follow-up if date provided
    if next_fu:
        db.q("""INSERT INTO followups (lead_id, patient_id, due_date, note, status, followup_type,
            purpose, assigned_to, created_at) VALUES (?,?,?,?, 'pending', 'lead', ?, ?, ?)""",
            (lid, pid, next_fu, f"Initial lead follow-up: {name}", notes or "Contact new lead", assigned_to, h.now()))

    record("lead_create", f"id={lid} source={source}", entity_type="lead",
           entity_id=lid)
    flash(f"Lead added for {name}.", "ok")
    return redirect(url_for("admin.leads", view="new"))


@bp.route("/leads/<int:lid>")
@login_required
def lead_detail(lid):
    if not has_cap("leads"):
        abort(403)
    scoped_uid = None if security.current_role() == "super_admin" else session["admin_uid"]
    lead = db.q("""SELECT l.*,
        COALESCE(NULLIF(l.name, ''), p.name, '') lead_name,
        COALESCE(NULLIF(l.phone, ''), p.phone, '') lead_phone,
        COALESCE(NULLIF(l.whatsapp, ''), p.whatsapp, '') lead_whatsapp,
        COALESCE(NULLIF(l.email, ''), p.email, '') lead_email,
        COALESCE(NULLIF(l.area, ''), p.area, '') lead_area,
        p.id pid, p.serial_no, p.pipeline_stage, p.is_confirmed, p.patient_code,
        su.username assigned_name, su.full_name assigned_full_name,
        cu.username converted_by_name, cu.full_name converted_by_full_name
        FROM leads l
        LEFT JOIN patients p ON p.id=l.patient_id
        LEFT JOIN users su ON su.id=l.assigned_to
        LEFT JOIN users cu ON cu.id=l.converted_by
        WHERE l.id=?""", (lid,), one=True)
    if not lead:
        abort(404)
    if scoped_uid and lead["assigned_to"] and lead["assigned_to"] != scoped_uid:
        abort(403)

    # Conversation history: chronological order
    history = db.q("""SELECT lh.*, u.username logged_username, u.full_name logged_fullname
        FROM lead_history lh
        LEFT JOIN users u ON u.id=lh.logged_by
        WHERE lh.lead_id=?
        ORDER BY COALESCE(lh.interaction_at, lh.created_at) ASC, lh.id ASC""", (lid,))

    # Follow-ups for this lead
    followups = db.q("""SELECT f.*, u.full_name assigned_fullname, u.username assigned_username
        FROM followups f
        LEFT JOIN users u ON u.id=f.assigned_to
        WHERE f.lead_id=? OR (f.patient_id=? AND f.patient_id IS NOT NULL)
        ORDER BY f.due_date DESC, f.id DESC""", (lid, lead["pid"]))

    staff = [] if scoped_uid else db.q("SELECT id, username, full_name FROM users WHERE is_active=1 ORDER BY id")
    today = h.today()
    return render_template("admin/lead_detail.html", lead=lead, history=history,
                           followups=followups, staff=staff, today=today, section="leads",
                           lead_types=h.LEAD_TYPES)


@bp.route("/leads/<int:lid>/edit", methods=["GET", "POST"])
@login_required
def lead_edit(lid):
    if not has_cap("leads_edit"):
        abort(403)
    lead = db.q("""SELECT l.*, p.id pid, p.serial_no, p.patient_code,
        COALESCE(NULLIF(l.name, ''), p.name, '') lead_name,
        COALESCE(NULLIF(l.phone, ''), p.phone, '') lead_phone,
        COALESCE(NULLIF(l.whatsapp, ''), p.whatsapp, '') lead_whatsapp,
        COALESCE(NULLIF(l.email, ''), p.email, '') lead_email,
        COALESCE(NULLIF(l.area, ''), p.area, '') lead_area
        FROM leads l LEFT JOIN patients p ON p.id=l.patient_id WHERE l.id=?""",
        (lid,), one=True)
    if not lead:
        abort(404)
    if security.current_role() != "super_admin" and \
            (lead["assigned_to"] or 0) != session["admin_uid"] and lead["assigned_to"] is not None:
        abort(403)

    if request.method == "POST":
        f = request.form
        name = f.get("name", "").strip()
        phone = f.get("phone", "").strip()
        if not name:
            flash("Lead name is required.", "err")
            return redirect(url_for("admin.lead_edit", lid=lid))
        whatsapp = f.get("whatsapp", "").strip() or phone
        email = f.get("email", "").strip()
        area = f.get("area", "").strip()
        source = f.get("source", "").strip() or lead["source"] or "Walk-in"
        interest = f.get("interest", "").strip() or lead["interest"]
        status = f.get("status", "").strip() or lead["status"]
        assign_val = f.get("assigned_to", "").strip()
        assigned_to = int(assign_val) if assign_val.isdigit() else None
        next_followup = f.get("next_followup", "").strip() or None
        notes = f.get("notes", "").strip()

        # Update lead record
        db.q("""UPDATE leads SET name=?, phone=?, whatsapp=?, email=?, area=?,
            source=?, interest=?, status=?, assigned_to=?, next_followup=?, notes=?
            WHERE id=?""",
            (name, phone, whatsapp, email, area, source, interest, status,
             assigned_to, next_followup, notes, lid))

        # Synchronize linked internal patient record
        if lead["patient_id"]:
            db.q("""UPDATE patients SET name=?, phone=?, whatsapp=?, email=?, area=?
                WHERE id=?""", (name, phone, whatsapp, email, area, lead["patient_id"]))

        # Update or schedule follow-up if date set
        if next_followup:
            existing_fu = db.q("""SELECT id FROM followups
                WHERE (lead_id=? OR patient_id=?) AND status='pending'
                ORDER BY id DESC LIMIT 1""", (lid, lead["patient_id"]), one=True)
            if existing_fu:
                db.q("UPDATE followups SET due_date=?, assigned_to=? WHERE id=?",
                     (next_followup, assigned_to, existing_fu["id"]))
            else:
                db.q("""INSERT INTO followups (lead_id, patient_id, due_date, note, status,
                    followup_type, purpose, assigned_to, created_at)
                    VALUES (?,?,?,?, 'pending', 'lead', ?, ?, ?)""",
                    (lid, lead["patient_id"], next_followup, f"Follow up with {name}",
                     notes or "Lead follow-up", assigned_to, h.now()))

        record("lead_edit", f"id={lid} name={name} status={status}",
               entity_type="lead", entity_id=lid)
        flash("Lead details updated successfully.", "ok")
        return redirect(url_for("admin.lead_detail", lid=lid))

    # GET
    staff = db.q("SELECT id, username, full_name FROM users WHERE is_active=1 ORDER BY id")
    sources = [x["name"] for x in db.q("SELECT name FROM sources WHERE is_active=1 ORDER BY sort_order")]
    return render_template("admin/lead_edit.html", lead=lead, staff=staff, sources=sources,
                           lead_types=h.LEAD_TYPES, section="leads")


@bp.route("/leads/<int:lid>/interaction", methods=["POST"])
@login_required
def lead_interaction(lid):
    if not has_cap("leads_edit"):
        abort(403)
    lead = db.q("""SELECT l.*, p.id pid, p.name pname, p.serial_no
        FROM leads l LEFT JOIN patients p ON p.id=l.patient_id WHERE l.id=?""",
        (lid,), one=True)
    if not lead:
        abort(404)
    if security.current_role() != "super_admin" and \
            (lead["assigned_to"] or 0) != session["admin_uid"] and lead["assigned_to"] is not None:
        abort(403)

    f = request.form
    comm_type = f.get("interaction_type", "call").strip().lower()
    summary = f.get("summary", "").strip()
    outcome = f.get("outcome", "Interested").strip()
    notes = f.get("notes", "").strip()
    has_next = f.get("next_followup_required", "no").strip().lower() == "yes"
    next_date = f.get("next_followup_date", "").strip() or None

    if not summary:
        if request.is_json or request.headers.get("Accept") == "application/json" or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "error": "Please provide a brief interaction summary."}), 400
        flash("Please provide a brief interaction summary.", "err")
        return redirect(url_for("admin.lead_detail", lid=lid))

    interaction_at = h.now()
    fu_id = None
    if has_next and next_date:
        fu_rows = db.q("""INSERT INTO followups (lead_id, patient_id, due_date, note, status,
            followup_type, purpose, assigned_to, created_at)
            VALUES (?,?,?,?, 'pending', 'lead', ?, ?, ?) RETURNING id""",
            (lid, lead["pid"], next_date, f"{comm_type.title()} follow-up: {summary[:100]}",
             notes or summary, lead["assigned_to"], h.now()))
        if fu_rows:
            fu_id = fu_rows[0]["id"]
        db.q("UPDATE leads SET next_followup=? WHERE id=?", (next_date, lid))

    full_note = summary + (f"\nNotes: {notes}" if notes else "")
    db.q("""INSERT INTO lead_history (lead_id, outcome, note, summary, interaction_type,
        due_date, logged_by, followup_id, interaction_at, created_at)
        VALUES (?,?,?,?, ?, ?, ?, ?, ?, ?)""",
        (lid, outcome, full_note, summary, comm_type, next_date,
         session.get("admin_uid"), fu_id, interaction_at, h.now()))

    outcome_lower = outcome.lower()
    if "appointment" in outcome_lower:
        db.q("UPDATE leads SET status='appointment' WHERE id=?", (lid,))
    elif "not interested" in outcome_lower or "lost" in outcome_lower:
        db.q("UPDATE leads SET status='lost' WHERE id=?", (lid,))
    elif has_next:
        db.q("UPDATE leads SET status='followup' WHERE id=?", (lid,))
    elif lead["status"] == "new":
        db.q("UPDATE leads SET status='contacted' WHERE id=?", (lid,))

    record("lead_interaction", f"lead={lid} type={comm_type} outcome={outcome}",
           entity_type="lead", entity_id=lid)
    if request.is_json or request.headers.get("Accept") == "application/json" or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "message": "Conversation entry recorded."})
    flash("Conversation entry recorded.", "ok")
    return redirect(url_for("admin.lead_detail", lid=lid))


@bp.route("/leads/<int:lid>/convert", methods=["POST"])
@login_required
def lead_convert(lid):
    if not has_cap("leads_edit"):
        abort(403)
    lead = db.q("""SELECT l.*,
        COALESCE(NULLIF(l.name, ''), p.name, '') lead_name,
        COALESCE(NULLIF(l.phone, ''), p.phone, '') lead_phone,
        COALESCE(NULLIF(l.whatsapp, ''), p.whatsapp, '') lead_whatsapp,
        COALESCE(NULLIF(l.email, ''), p.email, '') lead_email,
        COALESCE(NULLIF(l.area, ''), p.area, '') lead_area,
        p.id pid, p.serial_no, p.pipeline_stage, p.is_confirmed, p.patient_code
        FROM leads l LEFT JOIN patients p ON p.id=l.patient_id WHERE l.id=?""",
        (lid,), one=True)
    if not lead:
        abort(404)

    pid = lead["pid"]
    phone = lead["lead_phone"]
    # Check for existing confirmed patient to reuse
    if phone:
        norm = phone.replace(" ", "").replace("+", "").replace("-", "").strip()
        match = db.q("""SELECT id, serial_no, name FROM patients
            WHERE is_confirmed=1 AND REPLACE(REPLACE(REPLACE(phone,' ',''),'+',''),'-','')=?""",
            (norm,), one=True)
        if match:
            pid = match["id"]

    now_ts = h.now()
    if pid:
        # Confirm existing patient record
        db.q("""UPDATE patients SET is_confirmed=1, status='active',
            pipeline_stage=CASE WHEN pipeline_stage='' OR pipeline_stage='completed' THEN 'consultation' ELSE pipeline_stage END,
            stage_updated_at=? WHERE id=?""", (now_ts, pid))
    else:
        # Create Master Patient record
        serial = h.next_serial_no()
        pcode = h.next_patient_code()
        p_rows = db.q("""INSERT INTO patients (name, phone, whatsapp, email, area, source, status,
            profile_status, patient_code, serial_no, pipeline_stage, stage_updated_at, is_confirmed, created_at)
            VALUES (?,?,?,?,?,?, 'active', 'complete', ?, ?, 'consultation', ?, 1, ?) RETURNING id""",
            (lead["lead_name"] or "Patient", lead["lead_phone"], lead["lead_whatsapp"], lead["lead_email"],
             lead["lead_area"], lead["source"] or "Walk-in", pcode, serial, now_ts, now_ts))
        pid = p_rows[0]["id"]

    # Mark lead as converted and link to patient
    db.q("""UPDATE leads SET patient_id=?, status='converted', converted_at=?, converted_by=?
        WHERE id=?""", (pid, now_ts, session.get("admin_uid"), lid))

    # Link followups to patient
    db.q("UPDATE followups SET patient_id=? WHERE lead_id=?", (pid, lid))

    p_info = db.q("SELECT serial_no, name, patient_code FROM patients WHERE id=?", (pid,), one=True)
    db.q("""INSERT INTO patient_stage_log (patient_id, stage, note, created_at)
        VALUES (?, 'consultation', ?, ?)""",
        (pid, f"Converted from Lead #{lid} by {session.get('admin_user')}", now_ts))
    db.q("""INSERT INTO lead_history (lead_id, outcome, note, summary, interaction_type, logged_by, interaction_at, created_at)
        VALUES (?, 'converted', ?, ?, 'status_change', ?, ?, ?)""",
        (lid, f"Lead converted to Confirmed Patient #{p_info['serial_no']}",
         "Converted to Confirmed Master Patient", session.get("admin_uid"), now_ts, now_ts))

    record("lead_convert", f"lead={lid} patient={pid} serial={p_info['serial_no']}",
           entity_type="lead", entity_id=lid)
    flash(f"{p_info['name']} (#{p_info['serial_no']}) converted to Confirmed Master Patient.", "ok")
    return redirect(url_for("admin.patient_detail", pid=pid))


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
            (lead["assigned_to"] or 0) != session["admin_uid"] and lead["assigned_to"] is not None:
        abort(403)  # staff can only work their own leads
    f = request.form
    note = f.get("note", "").strip()
    status = LEAD_OUTCOMES[outcome][0]
    db.q("UPDATE leads SET status=? WHERE id=?", (status, lid))
    due = f.get("due_date") or None
    db.q("""INSERT INTO lead_history (lead_id, outcome, note, summary, interaction_type, due_date, logged_by, interaction_at, created_at)
         VALUES (?,?,?,?, ?, ?, ?, ?, ?)""",
         (lid, outcome, note, note or f"Status changed to {outcome}", "status_change", due,
          session.get("admin_uid"), h.now(), h.now()))

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
        db.q("""INSERT INTO followups (lead_id, patient_id, due_date, note, status, followup_type,
            purpose, created_at) VALUES (?,?,?,?, 'pending', 'Lead follow-up', ?, ?)""",
            (lid, lead["pid"], due or h.today(), note or "Follow up with lead",
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
    ret = f.get("next") or request.referrer or url_for("admin.followups")
    return redirect(ret)


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
    if fu.get("lead_id"):
        db.q("""INSERT INTO lead_history (lead_id, outcome, note, summary, interaction_type,
            logged_by, followup_id, interaction_at, created_at)
            VALUES (?, 'completed', ?, ?, 'call', ?, ?, ?, ?)""",
            (fu["lead_id"], f"Follow-up completed: {note or fu['note'] or 'Done'}",
             note or "Follow-up marked as completed", session.get("admin_uid"), fid, h.now(), h.now()))
        next_pend = db.q("SELECT due_date FROM followups WHERE lead_id=? AND status='pending' ORDER BY due_date ASC LIMIT 1",
                         (fu["lead_id"],), one=True)
        db.q("UPDATE leads SET next_followup=? WHERE id=?", (next_pend["due_date"] if next_pend else None, fu["lead_id"]))
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
    ("leads", "See assigned leads (My Leads)"),
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
