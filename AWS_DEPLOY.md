# Deploying OrthoPro India to AWS

The app is deliberately deployment-agnostic: one Flask app + **one PostgreSQL
database**, configured entirely through environment variables. No local files,
no SQLite, no in-process state. At your scale (~10 patients/day) the simplest
and cheapest AWS setup is **one EC2 instance + one RDS PostgreSQL**.

## Recommended layout

```
[Internet] → [EC2 t3.small: Nginx (TLS) → Gunicorn (Flask)]
                     │
                     └─ TLS (443) → [RDS PostgreSQL db.t4g.micro, Multi-AZ off is fine]
```

Total ≈ $10–20/month with the free-tier-friendly instance sizes.

## 1. Database (RDS)

1. RDS console → Create database → **PostgreSQL 16**, engine default,
   instance `db.t4g.micro`, 20 GB gp3, no read replica.
2. Note the **endpoint**, e.g. `ortho.abc123.us-east-1.rds.amazonaws.com`.
3. Create the databases and role (from any machine that can reach RDS):

   ```sql
   CREATE ROLE orthopro_app LOGIN PASSWORD '<strong-random-password>';
   CREATE DATABASE orthopro OWNER orthopro_app;
   ```
4. Security group: allow TCP 5432 **from the EC2 security group only**.

`DATABASE_URL=postgresql://orthopro_app:<password>@ortho.abc123...:5432/orthopro`

## 2. EC2 (app server)

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip nginx git
git clone <your-repo> orthopro && cd orthopro
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt gunicorn
cp .env.example .env   # fill in: SECRET_KEY, DATABASE_URL, FLASK_ENV=production
python3 scripts/init_db.py              # applies migrations 001–004 (idempotent)
python3 scripts/backfill_002.py         # sources / templates / serials / roles
printf 'admin\n<YOUR PASSWORD>\n<YOUR PASSWORD>\n' | python3 scripts/create_admin.py
```

Systemd unit `/etc/systemd/system/orthopro.service`:

```ini
[Unit]
After=network.target
[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/orthopro
EnvironmentFile=/home/ubuntu/orthopro/.env
ExecStart=/home/ubuntu/orthopro/.venv/bin/gunicorn -c gunicorn.conf.py wsgi:app
Restart=always
[Install]
WantedBy=multi-user.target
```

(`wsgi.py` also works: `gunicorn wsgi:app`.)

Nginx: `proxy_pass http://127.0.0.1:8000;` with Certbot TLS for your domain
(`sudo apt install certbot python3-certbot-nginx && sudo certbot --nginx`).
Serve `/static/` directly from Nginx for speed.

## 3. Meta (Facebook/Instagram/WhatsApp) webhook — later

When you have the Meta app ready, set in `.env` only (no code change):
`META_APP_SECRET`, `META_VERIFY_TOKEN`, and add the callback URL
`https://yourdomain.com/webhooks/meta` in Meta's dashboard.

## 4. Backups

* RDS: enable automated backups (7 days) — free.
* Extra safety: nightly `pg_dump` from EC2 to an S3 bucket via cron.
* Uploaded media lives in `uploads/` on the EC2 volume — include it in the
  nightly S3 sync if you store patient photos there.

## 5. Going live checklist

- [ ] `FLASK_ENV=production` (enables HSTS, secure cookies, strict CSP)
- [ ] Strong `SECRET_KEY`, real `META_*` values added later
- [ ] Domain DNS → EC2 elastic IP, TLS issued
- [ ] `create_admin.py` run with **your** password (default password refused)
- [ ] Old website domain 301-redirects to the new domain (SEO)
