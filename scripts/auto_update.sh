#!/usr/bin/env bash
# ==============================================================================
# OrthoPro India - EC2 GitHub Auto-Update Script
# Runs periodically (via systemd timer) to automatically pull latest commits
# pushed to GitHub, apply migrations, and restart the Gunicorn service.
# ==============================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

# Ensure git remote is using the public https repository
git remote set-url origin https://github.com/arunsinghh/orthopro-final.git 2>/dev/null || true

# Fetch latest branch info
git fetch origin main --quiet || exit 0

LOCAL_HASH="$(git rev-parse HEAD 2>/dev/null || echo '')"
REMOTE_HASH="$(git rev-parse origin/main 2>/dev/null || echo '')"

if [ -n "$REMOTE_HASH" ] && [ "$LOCAL_HASH" != "$REMOTE_HASH" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🔄 New commit detected: ${REMOTE_HASH} (was ${LOCAL_HASH})"

    # Update working copy cleanly to match remote
    git reset --hard origin/main

    # Make sure scripts remain executable
    chmod +x "${APP_DIR}/scripts/"*.sh 2>/dev/null || true

    # Install/update dependencies if requirements changed
    if [ -f "${APP_DIR}/requirements.txt" ]; then
        "${APP_DIR}/.venv/bin/pip" install -q -r "${APP_DIR}/requirements.txt" || true
    fi

    # Run database schema migrations & reference data seeding
    "${APP_DIR}/.venv/bin/python" "${APP_DIR}/scripts/init_db.py" || true
    "${APP_DIR}/.venv/bin/python" "${APP_DIR}/scripts/seed_dev.py" || true
    "${APP_DIR}/.venv/bin/python" "${APP_DIR}/scripts/seed_gallery.py" || true

    # Reload Gunicorn service
    sudo systemctl restart orthopro

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ Application successfully auto-updated to commit: ${REMOTE_HASH}"
fi
