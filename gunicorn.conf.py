"""Gunicorn production configuration.

Run with:  gunicorn -c gunicorn.conf.py wsgi:app
"""
import multiprocessing
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", min(4, (multiprocessing.cpu_count() or 1) * 2 + 1)))
worker_class = "sync"
threads = 2
timeout = 60
graceful_timeout = 30
keepalive = 5

# Hard cap on request bodies (mirrors app MAX_CONTENT_LENGTH); gunicorn will
# reject larger uploads before they reach Flask.
max_requests = 1000
max_requests_jitter = 100

# Do not leak server internals in errors.
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")

# Forwarded headers when behind a reverse proxy / load balancer.
forwarded_allow_ips = os.environ.get("TRUST_PROXY_IPS", "127.0.0.1")
