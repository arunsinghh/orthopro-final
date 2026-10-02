"""Admin authentication: username + password -> secure session.

The previous permanent "access key / magic link" mechanism was removed because
a secret in a URL leaks through browser history, server/proxy logs, referrer
headers and screenshots.
"""
import logging

from flask import (Blueprint, flash, redirect, render_template, request,
                   session, url_for)

from .. import security
from ..audit import record

bp = Blueprint("auth", __name__)
log = logging.getLogger("orthopro.auth")


def _safe_next(target):
    """Only allow redirects back into the admin area (no open redirects)."""
    if target and target.startswith("/admin") and "//" not in target:
        return target
    return url_for("admin.dashboard")


@bp.route("/admin/login", methods=["GET", "POST"])
def login():
    if session.get("admin_uid"):
        return redirect(url_for("admin.dashboard"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        locked, wait = security.login_is_locked(username)
        if locked:
            log.warning("login attempt while locked out user=%s ip=%s wait=%ss",
                        username, security.client_ip(), wait)
            flash(f"Too many failed attempts. Try again in {wait // 60 + 1} minute(s).", "err")
            return render_template("admin/login.html"), 429

        user = security.get_admin_user(username)
        if user and security.verify_password(user["password_hash"], password) \
                and not user.get("is_active", 1):
            log.warning("login attempt on disabled account user=%s ip=%s",
                        username, security.client_ip())
            security.login_failed(username)
            flash("This account has been disabled. Contact your admin.", "err")
            return render_template("admin/login.html"), 403
        if user and security.verify_password(user["password_hash"], password):
            # Session fixation defence: start a fresh session on login.
            session.clear()
            session["admin_uid"] = user["id"]
            session["admin_username"] = user["username"]
            session["admin_role"] = user.get("role") or "super_admin"
            session["admin_caps"] = user.get("caps") or ""
            session["admin_name"] = (user.get("full_name") or "").strip() or user["username"]
            session.permanent = True
            security.login_succeeded(username)
            record("login", f"user={username}")
            log.info("admin login success user=%s ip=%s", username, security.client_ip())
            return redirect(_safe_next(request.args.get("next")))

        security.login_failed(username)
        record("login_failed", f"user={username or '(blank)'}")
        log.warning("admin login failure user=%s ip=%s", username, security.client_ip())
        flash("Invalid username or password", "err")

    return render_template("admin/login.html")


@bp.route("/admin/logout")
def logout():
    uname = session.get("admin_username")
    session.clear()
    if uname:
        record("logout", f"user={uname}")
        log.info("admin logout user=%s", uname)
    flash("You have been logged out.", "ok")
    return redirect(url_for("auth.login"))
