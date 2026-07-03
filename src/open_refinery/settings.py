"""Settings — encrypted key/value config in the database.

Configuration that used to require environment variables (OAuth client id/secret,
email provider creds, …) lives here instead: values are encrypted with
`SECRET_KEY` and edited in the UI by admin/platform. Only `SECRET_KEY` remains an
environment variable. Values are never returned by the API — only the keys, so
the UI can show what's configured without exposing secrets.
"""

from __future__ import annotations

from sqlmodel import Session, select

from .crypto import decrypt, encrypt
from .models import Setting, now_iso


def set_setting(session: Session, key: str, value: str, actor_id: str) -> None:
    row = session.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=encrypt(value), updated_by=actor_id)
    else:
        row.value = encrypt(value)
        row.updated_by = actor_id
        row.updated_at = now_iso()
    session.add(row)
    session.commit()


def get_setting(session: Session, key: str) -> str | None:
    row = session.get(Setting, key)
    return decrypt(row.value) if row else None


def list_setting_keys(session: Session) -> list[str]:
    """Configured keys only — values (secrets) are never listed."""
    return list(session.exec(select(Setting.key).order_by(Setting.key)))


def delete_setting(session: Session, key: str) -> None:
    row = session.get(Setting, key)
    if row is not None:
        session.delete(row)
        session.commit()
