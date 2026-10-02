"""Application factory for OrthoPro Artificial Limbs Center."""
import logging
import logging.handlers
import os

from flask import Flask, render_template
from flask_wtf import CSRFProtect
from markupsafe import Markup
from flask_wtf.csrf import generate_csrf

from . import db
from . import helpers
from . import uploads as uploads_mod
from .config import get_config
from .security import apply_security_headers

csrf = CSRFProtect()


def _configure_logging(app):
    level = logging.DEBUG if app.debug else logging.INFO
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s")
    root = logging.getLogger("orthopro")
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(fmt)
        root.addHandler(handler)
    if not app.debug and os.environ.get("LOG_FILE"):
        fh = logging.handlers.RotatingFileHandler(
            os.environ["LOG_FILE"], maxBytes=2_000_000, backupCount=5)
        fh.setFormatter(fmt)
        root.addHandler(fh)


def create_app(config_name=None):
    app = Flask(__name__)
    cfg = get_config(config_name)
    app.config.from_object(cfg)
    app.config["ENV_NAME"] = config_name or os.environ.get("FLASK_ENV", "development")

    _configure_logging(app)
    db.init_app(app)
    csrf.init_app(app)

    # ------------------------------------------------ template filters
    app.jinja_env.filters["inr"] = helpers.inr
    app.jinja_env.filters["md"] = helpers.md
    app.jinja_env.filters["dshort"] = helpers.dshort
    app.jinja_env.globals["product_image"] = helpers.product_image

    # ------------------------------------------------ context processors
    @app.context_processor
    def inject_globals():
        from flask import session as _s
        return dict(
            site={"name": "OrthoPro Artificial Limbs Center",
                  "tagline": "Advanced Prosthetic & Orthotic Rehabilitation Center"},
            settings={k: helpers.setting(k) for k in (
                "phone", "phone2", "whatsapp", "email", "address", "hours",
                "map_url", "gmb_url", "facebook", "instagram", "youtube")},
            notif_count=helpers.due_followups_count(),
            appt_count=helpers.new_appointments_count(),
            today=helpers.today(),
            admin_name=_s.get("admin_name") or _s.get("admin_username") or "",
            admin_role=_s.get("admin_role") or "",
        )

    @app.context_processor
    def inject_perms():
        from .security import has_cap, ROLE_LABELS, current_role
        return dict(can=has_cap, role_label=ROLE_LABELS.get(current_role(), ""),
                    current_role=current_role())

    @app.context_processor
    def inject_csrf():
        def csrf_field():
            return Markup(
                f'<input type="hidden" name="csrf_token" value="{generate_csrf()}"/>')
        return dict(csrf_field=csrf_field)

    # ------------------------------------------------ blueprints
    # Gallery self-seeds from bundled assets (idempotent; never blocks startup)
    try:
        from .gallery_seed import sync_gallery
        sync_gallery(app.config["UPLOAD_DIR"])
    except Exception:                      # pragma: no cover
        app.logger.exception("gallery seed skipped")

    from .auth.routes import bp as auth_bp
    from .public.routes import bp as public_bp
    from .admin.routes import bp as admin_bp
    from .webhooks.routes import bp as webhooks_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)
    # Machine-to-machine webhook: authenticity is enforced by Meta's HMAC
    # signature check, not browser CSRF tokens.
    csrf.exempt(webhooks_bp)
    app.register_blueprint(webhooks_bp)

    # ------------------------------------------------ uploads + SEO files
    @app.route("/uploads/<fname>")
    def uploaded_file(fname):
        return uploads_mod.serve_file(fname)

    @app.route("/uploads/private/<fname>")
    def private_file(fname):
        return uploads_mod.serve_file(fname, require_auth=True)

    # ------------------------------------------------ headers & errors
    @app.after_request
    def _headers(response):
        return apply_security_headers(response)

    @app.errorhandler(404)
    def not_found(e):
        if request_wants_admin():
            return render_template("404.html",
                                   m=helpers.page_meta("Page Not Found", "Page not found", "/404")), 404
        return render_template("404.html",
                               m=helpers.page_meta("Page Not Found", "Page not found", "/404")), 404

    @app.errorhandler(500)
    def server_error(e):
        logging.getLogger("orthopro").exception("Unhandled server error")
        return ("<h1>500 - Something went wrong</h1>"
                "<p>Please try again later.</p>"), 500

    @app.errorhandler(413)
    def too_large(e):
        return ("<h1>File too large</h1>"
                "<p>The uploaded file exceeds the allowed size.</p>"), 413

    from flask import request
    from flask_wtf.csrf import CSRFError

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        logging.getLogger("orthopro").warning(
            "CSRF rejected path=%s reason=%s ip=%s",
            request.path, e.description,
            request.headers.get("X-Forwarded-For", request.remote_addr))
        return (
            "<!doctype html><meta charset=utf-8>"
            "<title>Session cookies required</title>"
            "<style>body{font-family:system-ui,sans-serif;max-width:560px;margin:8vh auto;"
            "padding:0 20px;color:#1e293b;line-height:1.6}"
            "h1{color:#0e7490;font-size:1.3em}code{background:#f1f5f9;padding:2px 6px;"
            "border-radius:4px}a{color:#0e7490;font-weight:600}</style>"
            "<h1>&#128274; Session cookies are required</h1>"
            f"<p><b>Reason:</b> {e.description}</p>"
            "<p>This site uses secure session cookies for login and form protection. "
            "They cannot be stored when the site is embedded inside another page "
            "(for example a preview pane), because browsers block cookies in that context.</p>"
            "<p><b>Fix:</b> open the site directly in its own browser tab &mdash; click the "
            "&ldquo;open in new tab&rdquo; button of the preview, or visit the preview URL "
            "directly. Login and all forms will then work normally.</p>"
            "<p><a href='/admin/login'>Go to the admin login</a></p>"), 400

    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    return app


def request_wants_admin():
    from flask import request
    return request.path.startswith("/admin")
