# database/__init__.py

"""Data persistence layer."""

try:
    from database.connection import db
except Exception:
    db = None

__all__ = ["db"]
