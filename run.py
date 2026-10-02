"""Development entry point.

Production must use Gunicorn (see gunicorn.conf.py / Procfile), not this file.
"""
import os

from app import create_app

app = create_app(os.environ.get("FLASK_ENV", "development"))

if __name__ == "__main__":
    if os.environ.get("FLASK_ENV") == "production":
        raise SystemExit(
            "Do not run the Flask dev server in production. Use: "
            "gunicorn -c gunicorn.conf.py 'app:create_app(\"production\")'"
        )
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=app.debug)
