"""Database access layer.

Works against PostgreSQL (production) or SQLite (development) through
SQLAlchemy Core. Every query is parameterized; nothing is ever built by
string-concatenating user input.

Design notes
------------
* `q(sql, args, one)` keeps the exact calling convention the original code
  used (positional ``?`` placeholders), so existing query strings did not
  need rewriting. ``?`` placeholders are translated to SQLAlchemy named
  parameters internally.
* Rows are returned as plain ``dict`` objects, matching the original
  ``sqlite3.Row`` key-based access used throughout the app and templates.
* ``date``/``datetime`` values are returned as ISO-8601 strings so the
  existing templates (which slice/compare them as strings) keep working.
* Each call runs inside a transaction (commit on success, rollback on error).
  Use :func:`transaction` to run several statements atomically.
"""
import datetime as _dt
import re
from contextlib import contextmanager

from sqlalchemy import create_engine, text

_engine = None
_is_sqlite = False  # legacy flag kept False; PostgreSQL only


def init_app(app):
    """Create the pooled engine from app config. Called once by the factory."""
    global _engine, _is_sqlite
    url = app.config["DATABASE_URL"]
    kwargs = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        raise RuntimeError("SQLite is not supported — use PostgreSQL (DATABASE_URL).")
        # SQLite needs this for cross-thread use in the dev server.
        if ":memory:" not in url:
            kwargs["connect_args"] = {"check_same_thread": False}
    else:
        _is_sqlite = False  # legacy flag kept False; PostgreSQL only
        kwargs.update({"pool_size": int(app.config.get("DB_POOL_SIZE", 5)),
                       "max_overflow": int(app.config.get("DB_MAX_OVERFLOW", 10))})
    _engine = create_engine(url, **kwargs)
    app.extensions["db_engine"] = _engine


def engine():
    if _engine is None:
        raise RuntimeError("Database not initialised; call db.init_app(app) first")
    return _engine


def is_sqlite():
    return _is_sqlite


_PLACEHOLDER = re.compile(r"\?")


def _translate(sql, args):
    """Convert positional ``?`` placeholders to SQLAlchemy named parameters."""
    names = []

    def repl(_match):
        name = f"p{len(names)}"
        names.append(name)
        return f":{name}"

    new_sql = _PLACEHOLDER.sub(repl, sql)
    if len(names) != len(args):
        raise ValueError(f"SQL placeholder count ({len(names)}) != args ({len(args)}): {sql!r}")
    return new_sql, dict(zip(names, args))


def _norm(value):
    """Normalise driver values for template-friendly consumption."""
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, _dt.time):
        return value.isoformat()
    return value


def _rows_to_dicts(result):
    if not result.returns_rows:
        return []
    return [{k: _norm(v) for k, v in row.items()} for row in result.mappings().all()]


def q(sql, args=(), one=False, conn=None):
    """Run a parameterized query. Commits when ``conn`` is None.

    ``conn`` lets callers group statements into one transaction via
    :func:`transaction`. INSERT/UPDATE/DELETE return an empty result set.
    """
    sql2, params = _translate(sql, args)
    if conn is not None:
        rows = _rows_to_dicts(conn.execute(text(sql2), params))
    else:
        with engine().begin() as c:
            rows = _rows_to_dicts(c.execute(text(sql2), params))
    return (rows[0] if rows else None) if one else rows


@contextmanager
def transaction():
    """Context manager yielding a connection with atomic commit/rollback."""
    with engine().begin() as conn:
        yield conn


def apply_schema(sql_text):
    """Execute a DDL script (used by init_db / tests).

    Full-line '--' comments are removed BEFORE splitting on ';' so semicolons
    inside comments can never break statement boundaries.
    """
    lines = [ln for ln in sql_text.splitlines() if not ln.strip().startswith("--")]
    clean = "\n".join(lines)
    statements = [s.strip() for s in clean.split(";") if s.strip()]
    with engine().begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
