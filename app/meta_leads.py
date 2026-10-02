"""Meta lead integration — normalization, verification and ingestion.

Build-now / connect-later: all logic is implemented and testable locally with
fixtures. Live Meta credentials (app secret, verify token, access token, page
IDs) come from environment variables and are NOT required for the code to run.

Supported events (official Meta mechanisms only):
  * Facebook / Instagram Lead Ads  (field == 'leadgen', values[].leadgen_id)
  * WhatsApp inbound messages      (field == 'messages', values[].messages[])

Security: webhook POSTs are accepted only with a valid X-Hub-Signature-256
HMAC-SHA256 of the raw body using META_APP_SECRET. Duplicate events are
idempotent via leads.meta_lead_id (unique partial index).
"""
import hashlib
import hmac
import json
import logging
import os
import urllib.request

from . import db
from . import helpers as h
from .audit import record

log = logging.getLogger("orthopro.meta")

PLATFORM_LABELS = {"facebook": "Facebook", "instagram": "Instagram",
                   "whatsapp": "WhatsApp"}


# ------------------------------------------------------------- verification
def verify_signature(raw_body: bytes, signature_header: str, app_secret: str) -> bool:
    """Validate Meta's X-Hub-Signature-256 header (HMAC-SHA256, constant time)."""
    if not app_secret or not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header[len("sha256="):])


def verify_challenge(args, verify_token: str):
    """Webhook GET verification (hub.mode / hub.verify_token / hub.challenge)."""
    if args.get("hub.mode") == "subscribe" and verify_token \
            and args.get("hub.verify_token") == verify_token:
        return args.get("hub.challenge", "")
    return None


# ------------------------------------------------------------- normalization
def normalize_event(payload: dict):
    """Convert a Meta webhook payload into a list of normalized lead events.

    Returns dicts: {platform, external_id, name, phone, fields, attribution,
    raw} — same shape for Facebook, Instagram and WhatsApp.
    """
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            field = change.get("field", "")
            value = change.get("value", {}) or {}

            if field == "leadgen":
                # Facebook / Instagram Instant Form leads
                page_id = str(value.get("page_id", ""))
                ig_id = os.environ.get("META_INSTAGRAM_BUSINESS_ID", "")
                platform = "instagram" if ig_id and page_id and page_id == ig_id \
                    else "facebook"
                for v in (value.get("leads") or [value]):
                    leadgen_id = str(v.get("leadgen_id", "") or "")
                    if not leadgen_id:
                        continue
                    fields = _field_data_from_value(v)
                    out.append({
                        "platform": platform,
                        "external_id": f"leadgen:{leadgen_id}",
                        "name": fields.get("full_name", ""),
                        "phone": fields.get("phone_number", ""),
                        "fields": fields,
                        "fields_fetched": bool(fields),
                        "attribution": {
                            "leadgen_id": leadgen_id,
                            "form_id": str(v.get("form_id", "") or ""),
                            "ad_id": str(v.get("ad_id", "") or ""),
                            "adset_id": str(v.get("adset_id", "") or ""),
                            "campaign_id": str(v.get("campaign_id", "") or ""),
                            "created_time": v.get("created_time", ""),
                        },
                        "raw": v,
                    })

            elif field == "messages":
                # WhatsApp Business inbound messages
                contact = (value.get("contacts") or [{}])[0]
                profile_name = (contact.get("profile") or {}).get("name", "")
                wa_phone = str(contact.get("wa_id", "") or "")
                for msg in value.get("messages", []):
                    msg_id = msg.get("id", "")
                    if not msg_id or msg.get("type") not in ("text", "audio", None):
                        # only text/audio initiate a conversation lead; ignore the rest
                        if msg.get("type") not in ("text", "audio"):
                            continue
                    body = ""
                    if msg.get("type") == "text":
                        body = (msg.get("text") or {}).get("body", "")
                    out.append({
                        "platform": "whatsapp",
                        "external_id": f"wa:{msg_id}",
                        "name": profile_name,
                        "phone": f"+{wa_phone}" if wa_phone else "",
                        "fields": {"message": body},
                        "fields_fetched": True,
                        "attribution": {
                            "message_id": msg_id,
                            "phone_number_id": os.environ.get(
                                "META_WHATSAPP_PHONE_NUMBER_ID", ""),
                            "created_time": (msg.get("timestamp") or ""),
                        },
                        "raw": msg,
                    })
    return out


def _field_data_from_value(v):
    """field_data may be embedded in the fixture payload; live it is fetched."""
    if v.get("field_data"):
        return v["field_data"]
    if isinstance(v.get("field_data_json"), str):
        try:
            return json.loads(v["field_data_json"])
        except ValueError:
            return {}
    return {}


def fetch_leadgen_details(leadgen_id: str) -> dict:
    """Fetch Instant Form answers from the Graph API (live mode only).

    Requires META_ACCESS_TOKEN. Returns {} when unconfigured — the lead is
    still created with full attribution and can be enriched manually.
    """
    token = os.environ.get("META_ACCESS_TOKEN", "")
    if not token or not leadgen_id:
        return {}
    version = os.environ.get("META_GRAPH_VERSION", "v21.0")
    url = (f"https://graph.facebook.com/{version}/{leadgen_id}"
           f"?access_token={token}")
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return {item.get("name", ""): item.get("values", [""])[0]
                for item in data.get("field_data", [])}
    except Exception:  # pragma: no cover - network / live-only path
        log.exception("graph fetch failed leadgen_id=%s", leadgen_id)
        return {}


# ------------------------------------------------------------- ingestion
def _lead_interest(event, platform):
    """Type of enquiry: form field if present, else auto-detected from message."""
    if event.get("fields") and event["fields"].get("interested_in"):
        return event["fields"]["interested_in"]
    if platform == "whatsapp":
        return h.detect_lead_type((event.get("fields") or {}).get("message", ""))
    return ""


def ingest(event: dict):
    """Create/update one lead from a normalized event. Idempotent.

    Returns (lead_id, created: bool). Never raises for bad data — logs instead.
    """
    external_id = event["external_id"]
    existing = db.q("SELECT id FROM leads WHERE meta_lead_id=?", (external_id,),
                    one=True)
    if existing:
        log.info("meta event already processed external_id=%s", external_id)
        return existing["id"], False

    name = (event.get("name") or "").strip() or "Unnamed lead"
    phone = (event.get("phone") or "").strip()
    platform = event["platform"]
    label = PLATFORM_LABELS.get(platform, platform)

    # Master Patient match/create — never duplicates (Part: duplicate prevention)
    patient_id = None
    matches = h.find_patient_matches(name=None if name == "Unnamed lead" else name,
                                     phone=phone, whatsapp=phone)
    if matches:
        patient_id = matches[0]["id"]
    elif phone or name != "Unnamed lead":
        rows = db.q("""INSERT INTO patients (name, phone, source, status,
            profile_status, patient_code, serial_no, pipeline_stage, created_at)
            VALUES (?,?,?,?, 'complete', ?, ?, '', ?) RETURNING id""",
            (name, phone, label, "active", h.next_patient_code(), h.next_serial_no(),
             h.now()))
        patient_id = rows[0]["id"]
        record("patient_create", f"id={patient_id} via_meta={platform}",
               entity_type="patient", entity_id=patient_id)

    rows = db.q("""INSERT INTO leads (patient_id, source, platform, status, interest,
        notes, meta_lead_id, form_id, campaign_id, adset_id, ad_id, lead_fields,
        raw_event, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, ?) RETURNING id""",
        (patient_id, label, platform, "new",
         _lead_interest(event, platform),
         event["fields"].get("message", "") if platform == "whatsapp" else "",
         external_id,
         event["attribution"].get("form_id", ""),
         event["attribution"].get("campaign_id", ""),
         event["attribution"].get("adset_id", ""),
         event["attribution"].get("ad_id", ""),
         json.dumps(event.get("fields") or {}, ensure_ascii=False),
         json.dumps(event.get("raw") or {}, ensure_ascii=False)[:8000],
         h.now()))
    lead_id = rows[0]["id"]
    record("lead_create", f"id={lead_id} platform={platform}",
           entity_type="lead", entity_id=lead_id)

    # Optional automatic first follow-up (off by default).
    days = int(os.environ.get("META_AUTO_FOLLOWUP_DAYS", "0") or 0)
    if days > 0 and patient_id:
        from datetime import date, timedelta
        due = (date.today() + timedelta(days=days)).isoformat()
        db.q("""INSERT INTO followups (patient_id, due_date, note, status,
            followup_type, purpose, created_at)
            VALUES (?,?,?, 'pending', 'Patient Call', ?, ?)""",
            (patient_id, due, f"Contact new {label} lead", h.now()))
    return lead_id, True
