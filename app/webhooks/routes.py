"""Meta webhook endpoint — build now, connect later.

GET  /webhooks/meta  : Meta webhook verification (hub.challenge echo).
POST /webhooks/meta  : signed events only (X-Hub-Signature-256 HMAC-SHA256).

This is a machine-to-machine API: CSRF does not apply (no browser session);
authenticity is enforced by the Meta app secret signature check instead.
The webhook stays disabled (503) until META_APP_SECRET / META_VERIFY_TOKEN
are configured — it never accepts unsigned traffic.
"""
import json
import logging
import os

from flask import Blueprint, Response, request

from .. import meta_leads
from ..audit import record

bp = Blueprint("webhooks", __name__, url_prefix="/webhooks")
log = logging.getLogger("orthopro.meta")


@bp.route("/meta", methods=["GET"])
def meta_verify():
    token = os.environ.get("META_VERIFY_TOKEN", "")
    challenge = meta_leads.verify_challenge(request.args, token)
    if challenge is None:
        log.warning("webhook verification rejected ip=%s", request.remote_addr)
        return Response("verification failed", status=403, mimetype="text/plain")
    return Response(challenge, status=200, mimetype="text/plain")


@bp.route("/meta", methods=["POST"])
def meta_event():
    secret = os.environ.get("META_APP_SECRET", "")
    if not secret:
        return Response("webhook not configured", status=503, mimetype="text/plain")

    raw = request.get_data() or b""
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not meta_leads.verify_signature(raw, signature, secret):
        record("webhook_rejected", "invalid signature path=/webhooks/meta")
        log.warning("webhook signature FAILED ip=%s", request.remote_addr)
        return Response("invalid signature", status=403, mimetype="text/plain")

    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        return Response("bad payload", status=400, mimetype="text/plain")

    processed = 0
    for event in meta_leads.normalize_event(payload):
        try:
            _, created = meta_leads.ingest(event)
            processed += 1 if created else 0
        except Exception:
            log.exception("meta ingest failed external_id=%s",
                          event.get("external_id"))
    log.info("webhook processed new_leads=%s", processed)
    # 200 tells Meta we received it; idempotency makes retries safe.
    return Response("EVENT_RECEIVED", status=200, mimetype="text/plain")
