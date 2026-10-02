"""Secure file-upload handling.

Defences implemented:
* extension whitelist AND magic-byte (content) sniffing — the extension alone
  is never trusted;
* randomized storage filenames (user-supplied names are never used on disk,
  eliminating path traversal and overwrite attacks);
* hard size cap via MAX_CONTENT_LENGTH;
* dangerous types (html, svg, js, php, py, sh, …) are rejected outright;
* files are served with an explicitly-forced Content-Type and
  ``X-Content-Type-Options: nosniff`` so a stored file can never be
  interpreted as HTML/script;
* media can be flagged private; private files are only served to an
  authenticated admin via a dedicated route.
"""
import os
import re
import secrets

from flask import abort, current_app, send_from_directory

from . import db

# extension -> (forced content type, kind)
ALLOWED = {
    "jpg": ("image/jpeg", "image"), "jpeg": ("image/jpeg", "image"),
    "png": ("image/png", "image"), "webp": ("image/webp", "image"),
    "gif": ("image/gif", "image"),
    "mp4": ("video/mp4", "video"), "webm": ("video/webm", "video"),
    "mov": ("video/quicktime", "video"), "m4v": ("video/x-m4v", "video"),
    "pdf": ("application/pdf", "document"),
}

_MAGIC = [
    (b"\xff\xd8\xff", {"jpg", "jpeg"}),
    (b"\x89PNG\r\n\x1a\n", {"png"}),
    (b"GIF87a", {"gif"}), (b"GIF89a", {"gif"}),
    (b"RIFF", {"webp"}),            # RIFF....WEBP (second check below)
    (b"\x1aE\xdf\xa3", {"webm"}),
    (b"%PDF-", {"pdf"}),
]


def sniff_matches(data: bytes, ext: str) -> bool:
    """Verify leading bytes are consistent with the claimed extension."""
    if ext in {"mp4", "m4v", "mov"}:
        # ISO base media: 'ftyp' box at offset 4
        return len(data) > 12 and data[4:8] == b"ftyp"
    for magic, exts in _MAGIC:
        if data.startswith(magic):
            if ext == "webp" and magic == b"RIFF":
                return data[8:12] == b"WEBP"
            return ext in exts
    return False


def extension_of(filename: str):
    if not filename or "." not in filename:
        return None
    ext = filename.rsplit(".", 1)[1].lower()
    return ext if re.fullmatch(r"[a-z0-9]{2,5}", ext) else None


def validate_upload(file) -> tuple[bool, str]:
    """Return (ok, error_message). Reads only the header bytes."""
    ext = extension_of(file.filename or "")
    if ext not in ALLOWED:
        return False, f"File type not allowed. Allowed: {', '.join(sorted(ALLOWED))}"
    header = file.stream.read(64)
    file.stream.seek(0)
    if not header:
        return False, "Empty file"
    if not sniff_matches(header, ext):
        return False, "File content does not match its extension (possible disguised file)"
    return True, ""


def save_upload(file) -> str:
    """Persist an already-validated upload under a random name. Returns filename."""
    ext = extension_of(file.filename)
    upload_dir = current_app.config["UPLOAD_DIR"]
    os.makedirs(upload_dir, exist_ok=True)
    fname = f"{secrets.token_hex(16)}.{ext}"
    file.save(os.path.join(upload_dir, fname))
    return fname


def register_media(fname: str, orig_name: str, kind: str, created_at: str,
                   is_private: int = 0):
    db.q("INSERT INTO media (filename, orig_name, kind, uploaded_at, is_private) "
         "VALUES (?,?,?,?,?)", (fname, orig_name or fname, kind, created_at, is_private))


def storage_path(fname: str) -> str:
    """Safe join that cannot escape the upload directory."""
    if not re.fullmatch(r"[a-f0-9]{32}\.[a-z0-9]{2,5}", fname or ""):
        abort(404)
    path = os.path.realpath(os.path.join(current_app.config["UPLOAD_DIR"], fname))
    root = os.path.realpath(current_app.config["UPLOAD_DIR"])
    if not path.startswith(root + os.sep):
        abort(404)
    return path


def serve_file(fname: str, require_auth: bool = False):
    """Serve a stored file with forced content-type; never executes."""
    from flask import session
    if require_auth and not session.get("admin_uid"):
        abort(403)
    row = db.q("SELECT * FROM media WHERE filename=?", (fname,), one=True)
    ext = extension_of(fname)
    ctype = ALLOWED.get(ext, ("application/octet-stream",))[0]
    # Private AND patient-scoped files are always auth-gated — they may only
    # ever be reached through the authenticated /uploads/private/ route.
    if row and (row.get("is_private") or row.get("scope") == "patient") \
            and not session.get("admin_uid"):
        abort(403)
    path = storage_path(fname)  # raises 404 on anything suspicious
    resp = send_from_directory(os.path.dirname(path), os.path.basename(path),
                               mimetype=ctype)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    if ctype == "application/pdf":
        # PDFs render with scripts/plugins disabled context
        resp.headers["Content-Security-Policy"] = "sandbox"
    return resp
