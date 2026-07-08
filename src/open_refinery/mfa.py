"""MFA lifecycle for local accounts — enroll, confirm, disable, and the login
check. The TOTP secret is encrypted at rest (`crypto`) and only ever returned in
the clear once, at enrollment, so an authenticator app can be set up.
"""

from __future__ import annotations

from sqlmodel import Session

from . import totp
from .crypto import decrypt, encrypt
from .models import User


def begin_enroll(session: Session, user: User) -> dict:
    """Generate a secret, store it (encrypted, not yet active), and return it once."""
    secret = totp.generate_secret()
    user.totp_secret = encrypt(secret)
    user.mfa_enabled = False
    session.add(user)
    session.commit()
    return {"secret": secret, "otpauth_uri": totp.provisioning_uri(secret, user.email)}


def confirm_enroll(session: Session, user: User, code: str) -> bool:
    """Activate MFA once the user proves they can produce a current code."""
    if not user.totp_secret or not totp.verify(decrypt(user.totp_secret), code):
        return False
    user.mfa_enabled = True
    session.add(user)
    session.commit()
    return True


def disable(session: Session, user: User, code: str) -> bool:
    """Turn MFA off — requires a valid current code while it's enabled."""
    if user.mfa_enabled and not totp.verify(decrypt(user.totp_secret), code):
        return False
    user.mfa_enabled = False
    user.totp_secret = ""
    session.add(user)
    session.commit()
    return True


def check(user: User, code: str | None) -> bool:
    """The login gate: passes when MFA is off, or a valid code is supplied."""
    if not user.mfa_enabled:
        return True
    return bool(user.totp_secret) and totp.verify(decrypt(user.totp_secret), code or "")
