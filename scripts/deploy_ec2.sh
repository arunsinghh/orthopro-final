#!/usr/bin/env bash
# ==============================================================================
# OrthoPro India - AWS EC2 Free Tier Automated Deployment Script
# Compatible with: Amazon Linux 2023, Ubuntu 22.04 / 24.04 LTS, RHEL, Debian
# ==============================================================================
set -euo pipefail

echo "=========================================================="
echo "🚀 Starting OrthoPro AWS EC2 Free Tier Deployment"
echo "=========================================================="

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="$(whoami)"

# ------------------------------------------------------------------------------
# 1. System Swap Configuration (Crucial for 1GB RAM t2.micro / t3.micro)
# ------------------------------------------------------------------------------
if ! grep -q '/swapfile' /etc/fstab; then
    echo "⚙️ Creating 2GB swap space to prevent Out-Of-Memory (OOM) on Free Tier..."
    sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    echo "✅ Swap configured."
else
    echo "✅ Swap already configured."
fi

# ------------------------------------------------------------------------------
# 2. Package Installation (Auto-detect package manager)
# ------------------------------------------------------------------------------
if command -v dnf &>/dev/null; then
    echo "📦 Detected dnf package manager (Amazon Linux / Fedora / RHEL)..."
    sudo dnf update -y
    sudo dnf install -y python3.11 python3.11-pip python3.11-devel \
        postgresql16-server postgresql16 git nginx certbot python3-certbot-nginx

    # Initialize PostgreSQL if not already initialized
    if [ ! -d "/var/lib/pgsql/data/base" ] && [ ! -d "/var/lib/pgsql/16/data/base" ]; then
        echo "🗄️ Initializing PostgreSQL 16 data directory..."
        sudo postgresql-setup --initdb || sudo /usr/bin/postgresql-setup --initdb || true
    fi
    PYTHON_CMD="python3.11"
elif command -v apt-get &>/dev/null; then
    echo "📦 Detected apt package manager (Ubuntu / Debian)..."
    sudo apt update -y
    sudo apt install -y python3-venv python3-pip python3-dev \
        postgresql postgresql-contrib libpq-dev \
        nginx git certbot python3-certbot-nginx curl ufw
    PYTHON_CMD="python3"
else
    echo "❌ Unsupported package manager. Please install dependencies manually."
    exit 1
fi

# ------------------------------------------------------------------------------
# 3. PostgreSQL Database Setup
# ------------------------------------------------------------------------------
echo "🗄️ Setting up PostgreSQL database..."
sudo systemctl enable postgresql
sudo systemctl start postgresql

# On RHEL/AL2023, ensure local md5/scram auth is allowed in pg_hba.conf
PG_HBA=$(sudo find /var/lib/pgsql -name "pg_hba.conf" 2>/dev/null | head -n 1 || true)
if [ -n "$PG_HBA" ] && [ -f "$PG_HBA" ]; then
    if ! sudo grep -q "orthopro_app" "$PG_HBA"; then
        echo "⚙️ Configuring pg_hba.conf for orthopro_app local authentication..."
        sudo sed -i '1i local   orthopro        orthopro_app                            md5\nhost    orthopro        orthopro_app    127.0.0.1/32            md5' "$PG_HBA"
        sudo systemctl restart postgresql
    fi
fi

DB_NAME="orthopro"
DB_USER="orthopro_app"

# Generate random secure database password
DB_PASS="$(openssl rand -base64 18 | tr -dc 'a-zA-Z0-9' | head -c 20)"

sudo -u postgres psql -c "CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}';" 2>/dev/null || \
sudo -u postgres psql -c "ALTER ROLE ${DB_USER} WITH PASSWORD '${DB_PASS}';"

sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};" 2>/dev/null || echo "Database ${DB_NAME} already exists."
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};"

echo "✅ PostgreSQL ready. Database: ${DB_NAME}, User: ${DB_USER}"

# ------------------------------------------------------------------------------
# 4. Application Environment (.env)
# ------------------------------------------------------------------------------
cd "$APP_DIR"
ENV_FILE="${APP_DIR}/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "⚙️ Generating production .env file..."
    SECRET_KEY="$(openssl rand -hex 32)"
    cat <<EOF > "$ENV_FILE"
FLASK_ENV=production
SECRET_KEY=${SECRET_KEY}
DATABASE_URL=postgresql://${DB_USER}:${DB_PASS}@127.0.0.1:5432/${DB_NAME}
PORT=8000
WEB_CONCURRENCY=2
TRUST_PROXY_IPS=127.0.0.1
EOF
    chmod 600 "$ENV_FILE"
    echo "✅ Created production .env file."
else
    echo "ℹ️ Existing .env file found. Keeping current settings."
fi

# ------------------------------------------------------------------------------
# 5. Python Virtual Environment & Dependencies
# ------------------------------------------------------------------------------
echo "🐍 Setting up Python virtual environment with ${PYTHON_CMD}..."
if [ ! -d "${APP_DIR}/.venv" ]; then
    $PYTHON_CMD -m venv "${APP_DIR}/.venv"
fi

"${APP_DIR}/.venv/bin/pip" install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

# ------------------------------------------------------------------------------
# 6. Database Migrations & Initial Setup
# ------------------------------------------------------------------------------
echo "🔄 Applying database schema migrations..."
"${APP_DIR}/.venv/bin/python" "${APP_DIR}/scripts/init_db.py"

echo "🔄 Running backfill..."
"${APP_DIR}/.venv/bin/python" "${APP_DIR}/scripts/backfill_002.py" || true

# ------------------------------------------------------------------------------
# 7. Systemd Service (Gunicorn Process Manager)
# ------------------------------------------------------------------------------
echo "⚙️ Configuring systemd service for OrthoPro..."
SERVICE_FILE="/etc/systemd/system/orthopro.service"

sudo bash -c "cat <<EOF > ${SERVICE_FILE}
[Unit]
Description=OrthoPro Clinic Gunicorn Service
After=network.target postgresql.service

[Service]
Type=notify
User=${USER_NAME}
Group=${USER_NAME}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/gunicorn -c gunicorn.conf.py wsgi:app
ExecReload=/bin/kill -s HUP \\\$MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF"

sudo systemctl daemon-reload
sudo systemctl enable orthopro
sudo systemctl restart orthopro
echo "✅ OrthoPro service started and enabled on boot."

# ------------------------------------------------------------------------------
# 8. Firewall (if UFW exists)
# ------------------------------------------------------------------------------
if command -v ufw &>/dev/null; then
    echo "🛡️ Configuring Firewall..."
    sudo ufw allow OpenSSH || true
    sudo ufw allow 'Nginx Full' || true
    sudo ufw --force enable || true
fi

echo "=========================================================="
echo "🎉 Base Application Deployment Complete!"
echo "=========================================================="
echo "Next step: Configure Nginx & your custom domain with SSL."
echo "Run: sudo bash ${APP_DIR}/scripts/setup_domain.sh yourdomain.com"
echo "Create your super admin account: ${APP_DIR}/.venv/bin/python ${APP_DIR}/scripts/create_admin.py"
echo "=========================================================="
