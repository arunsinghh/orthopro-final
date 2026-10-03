"""Authentication, password hashing, login throttling, security headers.

Passwords are hashed with Argon2id (via argon2-cffi). Werkzeug PBKDF2
hashes are still *verified* (never created) so accounts migrated from the
old SQLite database keep working until the admin resets the password with
``scripts/create_admin.py``.
"""
import logging
import threading
import time
from functools import wraps

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from flask import current_app, redirect, request, session, url_for
from werkzeug.security import check_password_hash as _werkzeug_check

from . import db

log = logging.getLogger("orthopro.security")

_ph = PasswordHasher(
    time_cost=3, memory_cost=64 * 1024, parallelism=2,
    hash_len=32, salt_len=16,
)

# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    if not stored_hash:
        return False
    if stored_hash.startswith("$argon2"):
        try:
            return _ph.verify(stored_hash, password)
        except VerifyMismatchError:
            return False
        except InvalidHashError:
            return False
    # Legacy werkzeug pbkdf2 hashes (migrated SQLite data).
    if stored_hash.startswith(("pbkdf2:", "scrypt:")):
        try:
            return _werkzeug_check(stored_hash, password)
        except Exception:
            return False
    return False


def password_strength_ok(password: str):
    """Return (ok, message) for admin password policy."""
    problems = []
    if len(password) < 12:
        problems.append("at least 12 characters")
    if not any(c.islower() for c in password):
        problems.append("a lowercase letter")
    if not any(c.isupper() for c in password):
        problems.append("an uppercase letter")
    if not any(c.isdigit() for c in password):
        problems.append("a digit")
    if not any(not c.isalnum() for c in password):
        problems.append("a symbol")
    if password.lower() in {"admin123", "password", "orthopro", "admin@123", "welcome123"}:
        problems.append("not a common/default password")
    if problems:
        return False, "Password must contain " + ", ".join(problems) + "."
    return True, ""


# ---------------------------------------------------------------- throttling
_attempts_lock = threading.Lock()
_attempts = {}  # key -> [count, first_ts, locked_until]


def _remote_ip():
    # Honor a single proxy hop when TRUST_PROXY is set (e.g. behind nginx/CDN)
    if current_app.config.get("TRUST_PROXY") and request.headers.get("X-Forwarded-For"):
        return request.headers["X-Forwarded-For"].split(",")[0].strip()
    return request.remote_addr or "?"


def login_is_locked(username: str):
    key = f"{_remote_ip()}|{username.lower()}"
    now = time.time()
    with _attempts_lock:
        rec = _attempts.get(key)
        if rec and rec[2] > now:
            return True, int(rec[2] - now)
        if rec and rec[2] and rec[2] <= now:
            _attempts.pop(key, None)
    return False, 0


def login_failed(username: str):
    key = f"{_remote_ip()}|{username.lower()}"
    now = time.time()
    max_att = current_app.config["LOGIN_MAX_ATTEMPTS"]
    lock_s = current_app.config["LOGIN_LOCKOUT_SECONDS"]
    with _attempts_lock:
        rec = _attempts.get(key)
        if not rec or now - rec[1] > lock_s:
            rec = [0, now, 0]
        rec[0] += 1
        if rec[0] >= max_att:
            rec[2] = now + lock_s
            log.warning("login lockout triggered ip=%s user=%s attempts=%s",
                        _remote_ip(), username, rec[0])
        _attempts[key] = rec


def login_succeeded(username: str):
    key = f"{_remote_ip()}|{username.lower()}"
    with _attempts_lock:
        _attempts.pop(key, None)


# ---------------------------------------------------------------- auth guard
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin_uid"):
            log.info("unauthenticated admin access attempt path=%s ip=%s",
                     request.path, _remote_ip())
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


# --------------------------------------------------------------- roles
# Role capability map. A role may do everything in its set; "clinic" covers the
# day-to-day modules. Website/Management areas are super_admin only. Keep it a
# simple map — do not over-engineer RBAC (spec: simple clinic app).
ROLES = ("super_admin", "receptionist", "prosthetist", "physiotherapist")
ROLE_CAPS = {
    # capability areas used by role_required / sidebar
    "super_admin": {"patients", "leads", "visits", "followups", "payments", "devices",
                    "reports", "website", "staff", "settings", "activity",
                    "clinical", "documents", "media"},
    "receptionist": {"patients", "leads", "visits", "followups", "payments"},
    "prosthetist": {"patients", "leads", "followups", "devices", "clinical",
                    "documents"},
    "physiotherapist": {"patients", "followups"},
}
ROLE_LABELS = {"super_admin": "Super Admin", "receptionist": "Receptionist",
               "prosthetist": "Prosthetist / Orthotist",
               "physiotherapist": "Physiotherapist"}


def current_role():
    return session.get("admin_role") or "super_admin"


ALL_CAPS = set().union(*ROLE_CAPS.values()) | {"leads_edit"}


def current_caps():
    """super_admin can do everything; staff get their personal cap list."""
    if current_role() == "super_admin":
        return ALL_CAPS
    return set(c for c in (session.get("admin_caps") or "").split(",") if c)


def has_cap(cap):
    return cap in current_caps()


def role_required(*caps):
    """Backend authorization. Hiding a menu is NOT security (spec rule 8)."""
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get("admin_uid"):
                return redirect(url_for("auth.login", next=request.path))
            if not any(has_cap(c) for c in caps):
                log.warning("forbidden path=%s role=%s ip=%s",
                            request.path, current_role(), _remote_ip())
                from flask import abort
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return deco


def get_current_admin():
    uid = session.get("admin_uid")
    if not uid:
        return None
    return db.q("SELECT id, username FROM users WHERE id=?", (uid,), one=True)


def get_admin_user(username: str):
    return db.q("SELECT * FROM users WHERE username=?", (username,), one=True)


# ---------------------------------------------------------------- headers
def apply_security_headers(response):
    """Attach security headers to every response."""
    h = response.headers
    h["X-Content-Type-Options"] = "nosniff"
    h["Referrer-Policy"] = "strict-origin-when-cross-origin"
    h["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    prod = current_app.config.get("ENV_NAME") == "production"
    if prod:
        h["X-Frame-Options"] = "SAMEORIGIN"
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        h["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: https:; media-src 'self'; "
            "frame-src https://www.youtube.com; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'self'; form-action 'self'"
        )
    return response


# ---------------------------------------------------------------- misc helpers
def client_ip():
    return _remote_ip()
