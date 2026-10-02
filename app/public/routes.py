"""Public website routes. URLs, titles, meta and structured data are
deliberately unchanged from the original site to preserve SEO."""
from flask import Blueprint, Response, flash, redirect, render_template, request, url_for

from .. import db
from .. import helpers as h

bp = Blueprint("public", __name__)


@bp.route("/sitemap.xml")
def sitemap():
    domain = h.setting("domain", "https://www.orthoproindia.com")
    urls = ["", "/services", "/gallery", "/products", "/prices", "/journeys",
            "/about", "/faq", "/blog", "/contact"]
    for s in db.q("SELECT slug FROM services"):
        urls.append(f"/services/{s['slug']}")
    for j in db.q("SELECT id FROM journeys"):
        urls.append(f"/journey/{j['id']}")
    for p in db.q("SELECT slug FROM posts WHERE status='published'"):
        urls.append(f"/blog/{p['slug']}")
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        xml.append(f"<url><loc>{domain}{u}</loc><changefreq>weekly</changefreq></url>")
    xml.append("</urlset>")
    return Response("\n".join(xml), mimetype="text/xml")


@bp.route("/robots.txt")
def robots():
    domain = h.setting("domain", "https://www.orthoproindia.com")
    return Response(f"User-agent: *\nAllow: /\nSitemap: {domain}/sitemap.xml\n",
                    mimetype="text/plain")


@bp.route("/")
def home():
    services = db.q("SELECT * FROM services ORDER BY sort LIMIT 8")
    journeys = db.q("SELECT * FROM journeys WHERE featured=1 ORDER BY id DESC LIMIT 3")
    reviews = db.q("SELECT * FROM testimonials WHERE approved=1 ORDER BY id DESC LIMIT 6")
    rstat = db.q("SELECT COALESCE(AVG(rating), 0) a, COUNT(*) c FROM testimonials WHERE approved=1", one=True)
    products = db.q("SELECT * FROM products WHERE featured=1 ORDER BY sort LIMIT 6")
    meta = h.page_meta(
        "Best Artificial Limb, Prosthetic & Orthotic Clinic in Delhi",
        "OrthoPro Artificial Limbs Center: certified prosthetics & orthotics clinic in Delhi. Artificial legs "
        "from \u20b925,000, bionic hands, AFO splints, diabetic footwear, custom insoles. Free "
        "consultation, 3D scanning & gait training. Book now \u260e +91 81305 46090.",
        "/",
        "artificial limb center delhi, prosthetic leg price india, best prosthetic clinic delhi, "
        "orthotic devices, below knee prosthesis, myoelectric hand india, jaipur foot delhi",
        [h.clinic_jsonld(),
         {"@context": "https://schema.org", "@type": "FAQPage",
          "mainEntity": [
              {"@type": "Question", "name": "What is the price of an artificial leg in India?",
               "acceptedAnswer": {"@type": "Answer", "text": "A basic below-knee artificial leg starts at \u20b925,000\u2013\u20b950,000 in India. Advanced modular legs cost \u20b950,000\u2013\u20b92,00,000 and microprocessor knees range from \u20b95 lakh to \u20b925 lakh depending on brand and technology."}},
              {"@type": "Question", "name": "How long does prosthetic fitting take?",
               "acceptedAnswer": {"@type": "Answer", "text": "Most below-knee prosthetic fittings take 5\u201310 days including casting, socket fabrication, trial fitting, alignment and gait training."}},
              {"@type": "Question", "name": "Do you provide home visits for prosthetic patients?",
               "acceptedAnswer": {"@type": "Answer", "text": "Yes, we provide home visits across Delhi NCR for patients who cannot travel to the clinic."}},
          ]}])
    return render_template("home.html", m=meta, services=services, journeys=journeys,
                           reviews=reviews, products=products, rstat=rstat)


@bp.route("/services")
def services():
    items = db.q("SELECT * FROM services ORDER BY sort")
    meta = h.page_meta(
        "Prosthetic & Orthotic Services \u2013 Artificial Limbs, Braces, Diabetic Care",
        "Complete prosthetics & orthotics services: artificial legs & arms, bionic hands, "
        "AFO/KAFO braces, spinal orthosis, diabetic foot care, pediatric rehab & gait "
        "training in Delhi. Detailed process & pricing.",
        "/services", "prosthetic services, orthotic services, artificial limb fitting, rehabilitation",
        [h.clinic_jsonld()])
    return render_template("services.html", m=meta, services=items)


@bp.route("/services/<slug>")
def service_detail(slug):
    s = db.q("SELECT * FROM services WHERE slug=?", (slug,), one=True)
    if not s:
        from flask import abort
        abort(404)
    prods = db.q("SELECT name, brand, price_min, price_max FROM products "
                 "WHERE category=? ORDER BY price_min", (s["category"],))
    rel_journeys = db.q("SELECT * FROM journeys WHERE service=? LIMIT 2", (s["name"],))
    meta = h.page_meta(
        f"{s['name']} in Delhi \u2013 {s['short']}",
        s["meta_desc"] or s["short"], f"/services/{slug}",
        s["keywords"],
        [h.clinic_jsonld(),
         {"@context": "https://schema.org", "@type": "Service",
          "name": s["name"], "description": s["short"],
          "provider": {"@type": "MedicalClinic", "name": "OrthoPro Artificial Limbs Center"},
          "areaServed": "Delhi NCR"}])
    return render_template("service_detail.html", m=meta, s=s, prods=prods, journeys=rel_journeys)


@bp.route("/gallery")
def gallery():
    items = db.q("""SELECT * FROM media WHERE scope='public' AND category='gallery'
        ORDER BY id DESC""")
    images = [m for m in items if m["kind"] == "image"]
    videos = [m for m in items if m["kind"] == "video"]
    meta = h.page_meta(
        "Gallery – Prosthetic & Orthotic Products, Clinic Photos & Videos",
        "Photo & video gallery of our artificial legs, bionic hands, braces, diabetic "
        "footwear, wheelchairs and clinic care at OrthoPro Artificial Limbs Center, Delhi.",
        "/gallery", "prosthetics gallery, artificial limb photos, orthotics videos",
        [h.clinic_jsonld()])
    return render_template("gallery.html", m=meta, images=images, videos=videos)


@bp.route("/products")
@bp.route("/prices")
def products():
    cat = request.args.get("category", "")
    cats = [r["category"] for r in db.q(
        "SELECT DISTINCT category FROM products ORDER BY category")]
    if cat:
        items = db.q("SELECT * FROM products WHERE category=? ORDER BY price_min", (cat,))
    else:
        items = db.q("SELECT * FROM products ORDER BY category, price_min")
    meta = h.page_meta(
        "Prosthetic & Orthotic Products Price List 2026 \u2013 Artificial Leg \u20b925,000",
        "Transparent price list: below-knee artificial leg \u20b925,000\u2013\u20b92,00,000, above-knee "
        "\u20b960,000+, microprocessor knee \u20b95\u201325 lakh, myoelectric hand \u20b92\u201315 lakh, AFO splints, "
        "custom insoles & diabetic footwear. Ottobock, Ossur, Endolite brands.",
        "/prices",
        "artificial leg price india, prosthetic leg price, bionic hand price india, "
        "above knee prosthesis cost, below knee artificial limb price, AFO splint price",
        [h.clinic_jsonld(),
         {"@context": "https://schema.org", "@type": "ItemList",
          "name": "Prosthetic & Orthotic Products Price List",
          "itemListElement": [
              {"@type": "ListItem", "position": i + 1, "name": p["name"],
               "description": f"Price: \u20b9{int(p['price_min']):,} \u2013 \u20b9{int(p['price_max']):,}"}
              for i, p in enumerate(items[:10])]}])
    return render_template("products.html", m=meta, products=items, cats=cats, cat=cat)


@bp.route("/journeys")
def journeys():
    items = db.q("SELECT * FROM journeys ORDER BY featured DESC, id DESC")
    meta = h.page_meta(
        "Patient Success Stories \u2013 Real Prosthetic & Orthotic Recoveries",
        "Read real patient journeys at OrthoPro Artificial Limbs Center: before & after stories of amputees "
        "walking again with artificial legs, stroke patients recovering with AFO splints and "
        "children fitted with pediatric orthotics.",
        "/journeys", "prosthetic patient stories, artificial leg success stories india",
        [h.clinic_jsonld()])
    return render_template("journeys.html", m=meta, journeys=items)


@bp.route("/journey/<int:jid>")
def journey_detail(jid):
    j = db.q("SELECT * FROM journeys WHERE id=?", (jid,), one=True)
    if not j:
        from flask import abort
        abort(404)
    meta = h.page_meta(j["title"], j["story"][:155], f"/journey/{jid}", "",
                       [h.clinic_jsonld()], j["before_image"])
    return render_template("journey_detail.html", m=meta, j=j)


@bp.route("/about")
def about():
    meta = h.page_meta(
        "About OrthoPro Artificial Limbs Center \u2013 Certified Prosthetists & Orthotists in Delhi",
        "OrthoPro Artificial Limbs Center is a certified prosthetics & orthotics rehabilitation center in "
        "Delhi with 3D scanning, gait lab and internationally trained clinicians. "
        "2,000+ successful patient cases.",
        "/about", "prosthetic clinic delhi about, certified orthotist prosthetist india",
        [h.clinic_jsonld()])
    return render_template("about.html", m=meta)


@bp.route("/faq")
def faq():
    faqs = [
        ("What is the cost of an artificial leg in India?",
         "A basic below-knee (transtibial) artificial leg starts at \u20b925,000\u2013\u20b950,000. Modular "
         "legs with dynamic-response feet cost \u20b950,000\u2013\u20b92,00,000. Above-knee prostheses with "
         "mechanical knees start around \u20b960,000, while microprocessor-controlled knees "
         "(C-Leg, Genium class) range from \u20b95 lakh to \u20b925 lakh. Final price depends on socket "
         "type, foot/knee components, liner and cosmetic finishing."),
        ("What is the cost of a bionic / myoelectric hand?",
         "Entry-level single-grip myoelectric hands start around \u20b92\u20135 lakh. Multi-grip "
         "bionic hands with Bluetooth app control range \u20b95\u201315 lakh, and premium imported "
         "multi-articulating hands can exceed \u20b915 lakh."),
        ("How many visits does prosthetic fitting take?",
         "Typically 5\u20138 visits over 1\u20133 weeks: consultation \u2192 stump assessment \u2192 "
         "casting/3D scan \u2192 test socket trial \u2192 final socket + alignment \u2192 gait training \u2192 "
         "follow-up reviews."),
        ("Do you accept government schemes / ADIP / insurance?",
         "Yes. We assist with ADIP scheme documentation, AYUSH/CGHS reimbursement paperwork "
         "and private insurance pre-authorisation where applicable. Bring any sanction letters "
         "to your first visit."),
        ("Can I get a home visit?",
         "Yes, we offer home visits across Delhi NCR for assessment, casting and follow-up "
         "for patients who cannot travel."),
        ("What is the difference between an orthosis and a prosthesis?",
         "A prosthesis replaces a missing body part (e.g. artificial leg). An orthosis "
         "supports or corrects an existing body part (e.g. AFO splint for foot drop, spinal "
         "brace, insoles)."),
        ("Do you repair old prosthetics?",
         "Yes \u2014 socket refitting, component replacement, liner changes, foot/footshell "
         "renewal and alignment correction for any brand."),
        ("How long does an artificial leg last?",
         "Components typically last 3\u20135 years depending on activity level. Sockets may need "
         "adjustment sooner if stump volume changes. We include free alignment reviews for "
         "the first year."),
    ]
    meta = h.page_meta(
        "FAQ \u2013 Artificial Leg Price, Fitting Time, Insurance & More",
        "Answers to common questions about prosthetic & orthotic treatment in India: prices, "
        "fitting process, insurance, ADIP scheme, home visits and maintenance.",
        "/faq", "artificial leg price faq, prosthetic fitting process",
        [{"@context": "https://schema.org", "@type": "FAQPage",
          "mainEntity": [{"@type": "Question", "name": a,
                          "acceptedAnswer": {"@type": "Answer", "text": b}} for a, b in faqs]}])
    return render_template("faq.html", m=meta, faqs=faqs)


@bp.route("/blog")
def blog():
    posts = db.q("SELECT * FROM posts WHERE status='published' ORDER BY created_at DESC")
    meta = h.page_meta(
        "Prosthetics & Orthotics Guides \u2013 Prices, Care & Recovery",
        "Expert guides on artificial limbs, prosthetic prices in India, orthotic care, "
        "diabetic foot protection and rehabilitation tips from OrthoPro Artificial Limbs Center clinicians.",
        "/blog", "prosthetic blog india, artificial limb guides", [h.clinic_jsonld()])
    return render_template("blog.html", m=meta, posts=posts)


@bp.route("/blog/<slug>")
def post_detail(slug):
    p = db.q("SELECT * FROM posts WHERE slug=? AND status='published'", (slug,), one=True)
    if not p:
        from flask import abort
        abort(404)
    meta = h.page_meta(p["title"], p["excerpt"] or p["body"][:155], f"/blog/{slug}", p["keywords"],
                       [{"@context": "https://schema.org", "@type": "Article",
                         "headline": p["title"], "datePublished": str(p["created_at"])[:10],
                         "author": {"@type": "Organization", "name": "OrthoPro Artificial Limbs Center"},
                         "description": p["excerpt"] or ""}], p["image"])
    return render_template("post_detail.html", m=meta, p=p)


@bp.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        if not name or not phone:
            flash("Please enter your name and phone number.", "err")
        else:
            db.q("""INSERT INTO appointments (name, phone, email, area, service, preferred_date,
                 message, status, created_at) VALUES (?,?,?,?,?,?,?, 'new', ?)""",
                 (name, phone, request.form.get("email", ""), request.form.get("area", ""),
                  request.form.get("service", ""),
                  (request.form.get("preferred_date") or None),
                  request.form.get("message", ""), h.now()))
            flash("Thank you! Your appointment request has been received. "
                  "Our team will call you shortly to confirm.", "ok")
            return redirect(url_for("public.contact"))
    services = db.q("SELECT name FROM services ORDER BY sort")
    meta = h.page_meta(
        "Book Appointment \u2013 Free Prosthetic & Orthotic Consultation Delhi",
        "Book a free consultation at OrthoPro Artificial Limbs Center, Delhi. Call +91 81305 46090 or request "
        "an appointment online for artificial limbs, braces, insoles & diabetic foot care.",
        "/contact", "book prosthetic consultation delhi, artificial limb appointment",
        [h.clinic_jsonld()])
    return render_template("contact.html", m=meta, services=services)


@bp.route("/review", methods=["POST"])
def submit_review():
    name = request.form.get("name", "").strip()
    text = request.form.get("text", "").strip()
    try:
        rating = max(1, min(5, int(request.form.get("rating", 5))))
    except (TypeError, ValueError):
        rating = 5
    if name and text:
        db.q("INSERT INTO testimonials (name, rating, text, approved) VALUES (?,?,?,0)",
             (name[:120], rating, text[:2000]))
        flash("Thank you! Your review will appear once approved.", "ok")
    return redirect(url_for("public.home") + "#reviews")
