# Meta WhatsApp Leads — local webhook setup (ngrok / cloudflared)

Your app endpoint (already built, tested & signature-verified):

    GET/POST  https://<YOUR-TUNNEL-URL>/webhooks/meta

Current local dev secrets (in `.env` — replace with real ones on AWS):

    META_APP_SECRET=local-dev-secret      # in Meta console this is the "App Secret"
    META_VERIFY_TOKEN=local-dev-verify    # any secret string YOU choose

## 1. Start a public tunnel to localhost:5000

### Option A — ngrok (your choice; needs a free account)
1. Sign up free at https://dashboard.ngrok.com/signup
2. Copy your authtoken from https://dashboard.ngrok.com/get-started/your-authtoken
3. Run:
       ngrok config add-authtoken <YOUR_TOKEN>
       ngrok http 5000
4. Copy the `https://xxxx.ngrok-free.app` URL it prints.

### Option B — cloudflared (no account, what we used for testing)
       cloudflared tunnel --url http://localhost:5000
   It prints a `https://….trycloudflare.com` URL (example from our test run:
   https://extra-communities-utah-sweet.trycloudflare.com).

## 2. Configure the Meta app (developers.facebook.com)
1. Open your WhatsApp Business app → **WhatsApp → API Setup** (or create a new app
   with the WhatsApp product).
2. **Webhook → Edit callback URL**
   - Callback URL:  `https://<YOUR-TUNNEL-URL>/webhooks/meta`
   - Verify token:  `local-dev-verify`   (must equal META_VERIFY_TOKEN in .env)
   - Press **Verify and save** — Meta calls GET with hub.challenge; the app echoes it.
3. **Webhook → Subscription fields** for `whatsapp_business_account`:
   tick **messages**.
4. Security: the app signs every POST with your **App Secret**. For local testing we
   set META_APP_SECRET=local-dev-secret and sign test events with the same value via
   `scripts/simulate_meta_webhook.py`. When you connect the REAL app, put the real
   App Secret from Meta's *App Settings → Basic* into `.env` and restart the server.
   Unsigned / badly signed posts are always rejected (403).

## 3. Test locally (no Meta account needed)
    python3 scripts/simulate_meta_webhook.py --kind whatsapp
    python3 scripts/simulate_meta_webhook.py --kind facebook
Each run posts a correctly-signed event to /webhooks/meta; open
**Admin → Leads** and the new WhatsApp/Facebook lead appears with its auto-detected
type (e.g. “Lower Limb (Leg)”) ready to assign.

## 4. Go-live on AWS
- Use the real HTTPS domain (https://www.orthoproindia.com/webhooks/meta) — no tunnel.
- Set real META_APP_SECRET / META_VERIFY_TOKEN as environment variables (never in code).
- Add the WhatsApp phone number in Meta console and subscribe the `messages` field.

Notes: duplicate events are ignored (idempotent by Meta message id). WhatsApp text is
auto-classified into lead types (leg / hand / braces / diabetic / wheelchair / repair)
so you can assign to the right staff immediately.
