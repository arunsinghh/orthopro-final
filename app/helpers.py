"""Shared helpers: settings lookup, counters, SEO meta, template filters.

These were module-level functions in the original ``app.py``; they are kept
behavior-compatible so templates and SEO output are unchanged.
"""
import datetime as dt
import html as _html
import re

from . import db


def now():
    """Timezone-aware UTC timestamp for inserts (TIMESTAMPTZ / DATETIME)."""
    return dt.datetime.now(dt.timezone.utc)


def today():
    return dt.date.today().isoformat()


def setting(key, default=""):
    r = db.q("SELECT value FROM settings WHERE key=?", (key,), one=True)
    return r["value"] if r else default


def due_followups_count():
    r = db.q("SELECT COUNT(*) c FROM followups WHERE status='pending' AND due_date <= ?",
             (today(),), one=True)
    return r["c"] if r else 0


def new_appointments_count():
    r = db.q("SELECT COUNT(*) c FROM appointments WHERE status='new'", one=True)
    return r["c"] if r else 0


def page_meta(title, desc, path, keywords="", jsonld_list=None, image=None):
    domain = setting("domain", "https://www.orthoproindia.com")
    return dict(
        title=f"{title} | OrthoPro Artificial Limbs Center",
        desc=desc, keywords=keywords,
        canonical=f"{domain}{path}",
        # Every page gets a share image; pages with their own image override it.
        og_image=domain + (image or "/static/img/clinic.jpg"),
        jsonld_list=jsonld_list or [],
    )


def clinic_jsonld():
    return {
        "@context": "https://schema.org", "@type": "MedicalClinic",
        "name": "OrthoPro Artificial Limbs Center",
        "description": "Advanced prosthetic & orthotic rehabilitation center in Delhi. "
                       "Artificial legs, bionic hands, orthotic braces, diabetic foot care.",
        "telephone": setting("phone", "+91 81305 46090"),
        "url": setting("domain", "https://www.orthoproindia.com"),
        "address": {"@type": "PostalAddress",
                    "streetAddress": setting("address", "Khirki Extension, Malviya Nagar, New Delhi"),
                    "addressLocality": "New Delhi", "addressRegion": "Delhi",
                    "addressCountry": "IN"},
        "medicalSpecialty": ["Prosthetics", "Orthotics", "Rehabilitation"],
        "priceRange": "\u20b9\u20b9",
        "openingHours": "Mo-Sa 09:00-19:00",
    }


# ------------------------------------------------------------------ filters
def inr(v):
    try:
        v = int(float(v))
        return f"\u20b9{v:,}"
    except (TypeError, ValueError):
        return v


def dshort(v):
    if not v:
        return "\u2014"
    try:
        return dt.date.fromisoformat(str(v)[:10]).strftime("%d %b %Y")
    except ValueError:
        return v


def md(text):
    """Tiny markdown subset: headings, bold, italic, lists, tables, links.

    HTML in the source is escaped first, so rendered blog bodies cannot inject
    markup (the template marks the *result* safe, not the input).
    """
    lines, out = (text or "").split("\n"), []
    in_ul = in_ol = in_tbl = False

    def close():
        nonlocal in_ul, in_ol, in_tbl
        if in_ul:
            out.append("</ul>"); in_ul = False
        if in_ol:
            out.append("</ol>"); in_ol = False
        if in_tbl:
            out.append("</table></div>"); in_tbl = False

    def inline(s):
        s = _html.escape(s, quote=False)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"\*(.+?)\*", r"<i>\1</i>", s)
        s = re.sub(r"\[(.+?)\]\((https?://[^\s)]+)\)",
                   r'<a href="\2" rel="noopener">\1</a>', s)
        return s

    for ln in lines:
        s = ln.rstrip()
        if not s.strip():
            close(); continue
        if s.startswith("|") and set(s.replace("|", "").strip()) <= set("- :"):
            continue
        if s.startswith("|"):
            cells = [x.strip() for x in s.strip("|").split("|")]
            if not in_tbl:
                close(); out.append('<div class="tbl-wrap"><table>'); in_tbl = True
                out.append("<tr>" + "".join(f"<th>{inline(c)}</th>" for c in cells) + "</tr>")
            else:
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
            continue
        close()
        if s.startswith("### "):
            out.append(f"<h3>{inline(s[4:])}</h3>")
        elif s.startswith("## "):
            out.append(f"<h2>{inline(s[3:])}</h2>")
        elif s.startswith("# "):
            out.append(f"<h2>{inline(s[2:])}</h2>")
        elif s.startswith(("- ", "* ")):
            if not in_ul:
                out.append("<ul>"); in_ul = True
            out.append(f"<li>{inline(s[2:])}</li>")
        elif re.match(r"^\d+\. ", s):
            if not in_ol:
                out.append("<ol>"); in_ol = True
            out.append(f"<li>{inline(re.sub(r'^[0-9]+\\. ', '', s))}</li>")
        elif s.startswith("> "):
            out.append(f"<blockquote><p>{inline(s[2:])}</p></blockquote>")
        else:
            out.append(f"<p>{inline(s)}</p>")
    close()
    return "\n".join(out)


# ============================================================ clinical CRM helpers
def norm_phone(s):
    """Normalize a phone/WhatsApp number to its last 10 digits (or '' if too short)."""
    digits = re.sub(r"\D", "", s or "")
    return digits[-10:] if len(digits) >= 10 else ""


def next_patient_code():
    """Next permanent Master Patient code (OP-xxxxxx). Independent of row ids."""
    r = db.q("SELECT COALESCE(MAX(CAST(SUBSTRING(patient_code FROM 4) AS INTEGER)),0)+1 AS n "
             "FROM patients WHERE patient_code IS NOT NULL", one=True)
    return f"OP-{r['n']:06d}"


def find_patient_matches(name="", phone="", whatsapp="", email="", area="", exclude_id=None):
    """Duplicate detection (spec Part 64): match on phone/WhatsApp/email exactly,
    or on exact name + area. Never merges — callers show a warning only."""
    pn = norm_phone(phone) or norm_phone(whatsapp)
    em = (email or "").strip().lower()
    nm = (name or "").strip().lower()
    ar = (area or "").strip().lower()
    out = []
    rows = db.q("SELECT id, patient_code, name, phone, whatsapp, email, area, status "
                "FROM patients ORDER BY id")
    for r in rows:
        if exclude_id is not None and r["id"] == exclude_id:
            continue
        why = []
        if pn and (norm_phone(r.get("phone")) == pn or norm_phone(r.get("whatsapp")) == pn):
            why.append("phone match")
        if em and (r.get("email") or "").strip().lower() == em:
            why.append("email match")
        if nm and (r.get("name") or "").strip().lower() == nm:
            if ar and (r.get("area") or "").strip().lower() == ar:
                why.append("name + area match")
            elif not pn and not em:
                why.append("name match")
        if why:
            r["match_reason"] = ", ".join(why)
            out.append(r)
    return out


def profile_missing(p):
    """Fields still missing on a master patient record (drives progressive completion)."""
    missing = []
    if not (p.get("phone") or "").strip():
        missing.append("phone")
    if not ((p.get("age") or "").strip() or p.get("dob")):
        missing.append("age / DOB")
    if not (p.get("gender") or "").strip():
        missing.append("gender")
    if not ((p.get("address") or "").strip() or (p.get("area") or "").strip()):
        missing.append("address")
    if not ((p.get("service") or "").strip() or (p.get("primary_condition") or "").strip()):
        missing.append("service / condition")
    return missing


def sync_profile_status(pid):
    """Keep patients.profile_status in sync with filled fields."""
    p = db.q("SELECT * FROM patients WHERE id=?", (pid,), one=True)
    if not p:
        return
    status = "incomplete" if profile_missing(p) else "complete"
    if p.get("profile_status") != status:
        db.q("UPDATE patients SET profile_status=? WHERE id=?", (status, pid))


def tomorrow():
    return (dt.date.today() + dt.timedelta(days=1)).isoformat()


def next_device_code():
    """Next device code (DEV-xxxxxx), independent of row ids."""
    r = db.q("SELECT COALESCE(MAX(CAST(SUBSTRING(device_code FROM 5) AS INTEGER)),0)+1 AS n "
             "FROM devices WHERE device_code IS NOT NULL", one=True)
    return f"DEV-{r['n']:06d}"


def next_repair_code():
    r = db.q("SELECT COALESCE(MAX(CAST(SUBSTRING(repair_code FROM 4) AS INTEGER)),0)+1 AS n "
             "FROM repairs WHERE repair_code IS NOT NULL", one=True)
    return f"RP-{r['n']:05d}"


def next_invoice_no(kind):
    """QT-00001 for quotations, INV-00001 for invoices."""
    prefix = "QT" if kind == "quotation" else "INV"
    r = db.q("SELECT COALESCE(MAX(CAST(SUBSTRING(invoice_no FROM LENGTH(?)+2) AS INTEGER)),0)+1 AS n "
             "FROM invoices WHERE invoice_no LIKE ?", (prefix, f"{prefix}-%"), one=True)
    return f"{prefix}-{r['n']:05d}"



def next_serial_no(when=None):
    """Patient serial: YYMM + running number, no padding (26091, 26092, ...,
    260910, ...). The number counts patients registered in that month."""
    d = when or dt.date.today()
    yymm = f"{d.year % 100:02d}{d.month:02d}"
    r = db.q("SELECT COALESCE(MAX(CAST(SUBSTRING(serial_no FROM 5) AS INTEGER)),0)+1 AS n "
             "FROM patients WHERE serial_no LIKE ?", (yymm + "%",), one=True)
    return f"{yymm}{r['n']}"


# --------------------------------------------------------------- product photos
PRODUCT_IMAGES = {
    "Below-Knee (Transtibial) Basic Prosthetic Leg": "/static/img/services/lower-limb-prosthetics.jpg",
    "Below-Knee Modular Leg with Dynamic Foot": "/static/img/products/bk-modular.jpg",
    "Sports / Carbon-Fibre Running Foot": "/static/img/gallery/carbon-feet.jpg",
    "Above-Knee (Transfemoral) Prosthesis – Mechanical Knee": "/static/img/gallery/ak-prosthesis.jpg",
    "Above-Knee Prosthesis – Hydraulic Knee": "/static/img/gallery/ak-prosthesis.jpg",
    "Microprocessor Knee (C-Leg / Genium class)": "/static/img/gallery/microprocessor-knee.jpg",
    "Partial Foot / Toe Prosthesis": "/static/img/products/partial-foot.jpg",
    "Below-Elbow Body-Powered Prosthetic Hand": "/static/img/products/hook-arm.jpg",
    "Myoelectric (Bionic) Hand – Single Grip": "/static/img/gallery/bionic-hand.jpg",
    "Multi-Grip Bionic Hand with App Control": "/static/img/gallery/bionic-hand.jpg",
    "Cosmetic Silicone Hand / Arm": "/static/img/gallery/silicone-hand.jpg",
    "AFO Foot-Drop Splint": "/static/img/gallery/afo-brace.jpg",
    "Ground-Reaction AFO (GRAFO)": "/static/img/services/orthotics-braces.jpg",
    "KAFO Calipers with Locking Knee Joints": "/static/img/gallery/kafo-brace.jpg",
    "TLSO Spinal Brace (Boston / Milwaukee type)": "/static/img/products/tlso-brace.jpg",
    "Cervical Collar / Lumbar Sacral Belt": "/static/img/products/cervical-collar.jpg",
    "Upper-Limb Splints (Wrist, Cock-up, Thumb)": "/static/img/products/wrist-splint.jpg",
    "Custom Foot Insoles (Biomechanical)": "/static/img/products/custom-insoles.jpg",
    "Diabetic MCR Footwear (Custom)": "/static/img/gallery/diabetic-footwear.jpg",
    "Silicone Prosthetic Socks & Liners": "/static/img/gallery/liners-socks.jpg",
    "Wheelchair / Walker / Crutches": "/static/img/gallery/mobility-aids.jpg",
}


def product_image(name):
    """Real photo for a product name — never an emoji."""
    return PRODUCT_IMAGES.get(name or "", "")


# --------------------------------------------------------------- lead types
LEAD_TYPES = ["Lower Limb (Leg)", "Upper Limb (Hand/Arm)", "Braces & Orthotics",
              "Diabetic Foot Care", "Wheelchair & Mobility", "Repair / Service",
              "Other"]

_TYPE_KEYWORDS = [
    ("Upper Limb (Hand/Arm)", ["hand", "arm", "finger", "bionic", "myoelectric"]),
    ("Braces & Orthotics", ["brace", "afo", "kafo", "caliper", "splint", "collar",
                            "orthotic", "foot drop"]),
    ("Diabetic Foot Care", ["diabet", "ulcer", "mcr", "footwear", "shoe", "insole"]),
    ("Wheelchair & Mobility", ["wheelchair", "walker", "crutch", "stick", "mobility"]),
    ("Repair / Service", ["repair", "fix", "service", "broken"]),
    ("Lower Limb (Leg)", ["leg", "knee", "amput", "jaipur", "prosthe", "foot"]),
]


def detect_lead_type(text):
    """Plain-language guess of what the enquiry is about (for assignment)."""
    t = (text or "").lower()
    for label, keys in _TYPE_KEYWORDS:
        if any(k in t for k in keys):
            return label
    return "Other"
