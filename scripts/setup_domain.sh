#!/usr/bin/env bash
# ==============================================================================
# OrthoPro India - Nginx & Custom Domain Setup with Let's Encrypt SSL
# Usage:
#   sudo bash scripts/setup_domain.sh yourdomain.com [www.yourdomain.com]
# ==============================================================================
set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Usage: sudo bash $0 <primary-domain> [additional-domain...]"
    echo "Example: sudo bash $0 orthoproindia.com www.orthoproindia.com"
    exit 1
fi

DOMAIN="$1"
DOMAINS_FLAG="-d $1"
SERVER_NAMES="$1"

shift
while [ "$#" -gt 0 ]; do
    DOMAINS_FLAG="${DOMAINS_FLAG} -d $1"
    SERVER_NAMES="${SERVER_NAMES} $1"
    shift
done

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "🌐 Setting up Nginx for domain: ${SERVER_NAMES}"

# Choose Nginx config directory based on OS
if [ -d "/etc/nginx/conf.d" ]; then
    NGINX_CONF="/etc/nginx/conf.d/orthopro.conf"
else
    sudo mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled
    NGINX_CONF="/etc/nginx/sites-available/orthopro"
    sudo ln -sf "${NGINX_CONF}" /etc/nginx/sites-enabled/orthopro
    sudo rm -f /etc/nginx/sites-enabled/default
fi

cat <<EOF | sudo tee "${NGINX_CONF}" > /dev/null
upstream orthopro_server {
    server 127.0.0.1:8000 fail_timeout=0;
}

server {
    listen 80;
    listen [::]:80;
    server_name ${SERVER_NAMES};

    client_max_body_size 16M;

    # Static assets served directly by Nginx with cache headers
    location /static/ {
        alias ${APP_DIR}/app/static/;
        expires 30d;
        add_header Cache-Control "public, no-transform";
        access_log off;
    }

    # Uploads (if stored locally)
    location /uploads/ {
        alias ${APP_DIR}/uploads/;
        expires 7d;
        add_header Cache-Control "private";
    }

    # Proxy to Flask / Gunicorn
    location / {
        proxy_pass http://orthopro_server;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_redirect off;
        proxy_read_timeout 90;
        proxy_connect_timeout 90;
    }
}
EOF

# Ensure permissions allow nginx to read static files
sudo chmod -R o+rx "${APP_DIR}/app/static" 2>/dev/null || true

# Test Nginx syntax and reload
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl reload nginx || sudo systemctl restart nginx

echo "✅ Nginx configured and active."
echo ""
echo "🔒 Requesting Free SSL Certificate from Let's Encrypt (Certbot)..."
echo "Make sure your domain's DNS A Record points to this server's public IP!"
read -p "Do you want to proceed with Certbot SSL installation now? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo certbot --nginx ${DOMAINS_FLAG} --redirect --non-interactive --agree-tos --register-unsafely-without-email || \
    sudo certbot --nginx ${DOMAINS_FLAG}
    sudo systemctl reload nginx
    echo "🎉 SSL Certificate installed! HTTPS is now active for ${DOMAIN}"
else
    echo "⚠️ Skipped Certbot. You can run it anytime with:"
    echo "   sudo certbot --nginx ${DOMAINS_FLAG}"
fi
