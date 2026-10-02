#!/usr/bin/env python3
"""Local fixture: simulate signed Meta webhook events against the running app.

Uses the SAME normalization/business logic path as production (signed POST to
/webhooks/meta). Development/testing only — never invent real credentials.

Usage:
    python scripts/simulate_meta_webhook.py [--url http://localhost:5000]
        [--secret local-dev-secret] [--kind facebook|instagram|whatsapp]
"""
import argparse
import hashlib
import hmac
import json
import time
import urllib.request

FB = {
    "object": "page",
    "entry": [{"id": "PAGE_ID", "time": int(time.time()), "changes": [{
        "field": "leadgen",
        "value": {"leads": [{
            "leadgen_id": str(int(time.time() * 1000)),
            "created_time": int(time.time()),
            "form_id": "FORM123", "ad_id": "AD456", "adset_id": "ADSET789",
            "campaign_id": "CAMP000",
            "field_data": {"full_name": "Fixture Lead",
                            "phone_number": "+919999988888",
                            "interested_in": "Below Knee Prosthesis"},
        }]}}]}],
}
WA = {
    "object": "whatsapp_business_account",
    "entry": [{"id": "WA_ID", "changes": [{
        "field": "messages",
        "value": {"contacts": [{"profile": {"name": "Fixture WhatsApp Lead"},
                                "wa_id": "919999977777"}],
                  "messages": [{"id": f"wamid.{int(time.time()*1000)}",
                                "timestamp": str(int(time.time())),
                                "type": "text",
                                "text": {"body": "I need an AFO, please call me."}}]},
    }]}],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:5000")
    ap.add_argument("--secret", default="local-dev-secret")
    ap.add_argument("--kind", choices=["facebook", "instagram", "whatsapp"],
                    default="facebook")
    args = ap.parse_args()
    payload = WA if args.kind == "whatsapp" else FB
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(args.secret.encode(), body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        args.url + "/webhooks/meta", data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig})
    try:
        with urllib.request.urlopen(req) as resp:
            print(resp.status, resp.read().decode())
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode())


if __name__ == "__main__":
    main()
