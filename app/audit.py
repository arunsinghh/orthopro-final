"""Audit logging for sensitive admin actions.

Writes to both the structured application log and the ``audit_log`` table.
Deliberately does NOT record passwords, session cookies, or free-text patient
notes — only identifiers and the nature of the action.
"""
import logging

from flask import session

from . import db

log = logging.getLogger("orthopro.audit")


def _actor():
    uid = session.get("admin_uid")
    uname = session.get("admin_username", "?")
    return f"{uname}(id={uid})" if uid else "anonymous"


def record(action: str, detail: str = "", entity_type: str = "", entity_id=None):
    """Persist an audit event. Never raises — auditing must not break actions."""
    try:
        db.q("INSERT INTO audit_log (ts, actor, action, detail, entity_type, entity_id) "
             "VALUES (CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)",
             (_actor(), action, detail[:500], entity_type, entity_id))
    except Exception:  # pragma: no cover - audit must be best-effort
        log.exception("audit write failed action=%s", action)
    log.info("AUDIT actor=%s action=%s detail=%s", _actor(), action, detail[:200])
