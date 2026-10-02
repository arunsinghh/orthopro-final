"""Application configuration.

Secrets come ONLY from environment variables (see .env / .env.example).
Production refuses to start without required secrets — it never falls back
to insecure development defaults.

Environment-derived values are read at *instantiation* time (not import time)
so configuration is reliable and unit-testable.
"""
import os

try:  # python-dotenv is a hard dependency
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Config:
    """Shared base configuration."""

    # Per-environment static flags (overridden by subclasses)
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = False
    PREFERRED_URL_SCHEME = "http"
    WTF_CSRF_SSL_SECURE = False

    # Constant security/behaviour flags
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    WTF_CSRF_TIME_LIMIT = None      # tokens valid for the session lifetime
    WTF_CSRF_CHECK_DEFAULT = True

    def __init__(self):
        self.SECRET_KEY = os.environ.get("SECRET_KEY")
        self.DATABASE_URL = os.environ.get("DATABASE_URL")
        self.UPLOAD_DIR = os.environ.get("UPLOAD_DIR", os.path.join(BASE_DIR, "uploads"))
        self.MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", "50")) * 1024 * 1024
        self.PERMANENT_SESSION_LIFETIME = int(
            os.environ.get("SESSION_LIFETIME_SECONDS", str(8 * 3600)))
        self.LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5"))
        self.LOGIN_LOCKOUT_SECONDS = int(os.environ.get("LOGIN_LOCKOUT_SECONDS", "900"))

    def validate(self):
        return True


class DevelopmentConfig(Config):
    DEBUG = True

    def __init__(self):
        super().__init__()
        if not self.SECRET_KEY:
            self.SECRET_KEY = "dev-only-insecure-secret-do-not-use-in-prod"
        if not self.DATABASE_URL:
            self.DATABASE_URL = "postgresql://orthopro_app:orthopro_app@127.0.0.1:5432/orthopro"


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False  # Flask-WTF reads this; tests post programmatically

    def __init__(self):
        super().__init__()
        if not self.SECRET_KEY:
            self.SECRET_KEY = "test-secret"
        if not self.DATABASE_URL:
            self.DATABASE_URL = "postgresql://orthopro_app:orthopro_app@127.0.0.1:5432/orthopro_test"
        self.LOGIN_MAX_ATTEMPTS = 100


class ProductionConfig(Config):
    SESSION_COOKIE_SECURE = True          # cookies only over HTTPS
    PREFERRED_URL_SCHEME = "https"
    WTF_CSRF_SSL_SECURE = True

    def validate(self):
        """Fail fast if required production secrets are missing or weak."""
        problems = []
        if not self.SECRET_KEY:
            problems.append("SECRET_KEY is not set")
        elif (self.SECRET_KEY in {"dev-only-insecure-secret-do-not-use-in-prod",
                                  "test-secret", "orthopro-super-secret-change-me"}
              or len(self.SECRET_KEY) < 32):
            problems.append("SECRET_KEY is a known-weak/development value or too short (<32 chars)")
        if not self.DATABASE_URL:
            problems.append("DATABASE_URL is not set")
        elif not self.DATABASE_URL.startswith("postgres"):
            problems.append("DATABASE_URL must be PostgreSQL (SQLite is not supported anywhere)")
        if problems:
            raise RuntimeError("Refusing to start in production:\n  - "
                               + "\n  - ".join(problems))
        return True


def get_config(name=None):
    name = name or os.environ.get("FLASK_ENV", "development")
    mapping = {
        "development": DevelopmentConfig,
        "testing": TestingConfig,
        "production": ProductionConfig,
    }
    if name not in mapping:
        raise RuntimeError(f"Unknown FLASK_ENV: {name!r}")
    cfg = mapping[name]()
    cfg.validate()
    return cfg
