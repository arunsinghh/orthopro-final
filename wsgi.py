"""WSGI entry point for Gunicorn.

    gunicorn -c gunicorn.conf.py wsgi:app
"""
import os

from app import create_app

app = create_app(os.environ.get("FLASK_ENV", "production"))
