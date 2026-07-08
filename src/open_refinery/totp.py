"""TOTP (RFC 6238) — time-based one-time passwords, stdlib only.

Used for MFA on local password logins (SSO logins inherit MFA from the IdP). No
third-party dependency: HMAC-SHA1 over the 30-second counter, truncated to 6
digits, verified with a ±1 step window for clock skew and constant-time compare.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

STEP = 30
DIGITS = 6


def generate_secret() -> str:
    """A fresh base32 TOTP secret (160-bit, the RFC-recommended size)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code_at(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10 ** DIGITS)).zfill(DIGITS)


def verify(secret: str, code: str, now: float | None = None, window: int = 1) -> bool:
    """True if `code` is valid for `secret` now (±`window` steps of skew)."""
    if not secret:
        return False
    if not code:
        return False
    if not code.isdigit():
        return False
    counter = int((time.time() if now is None else now) // STEP)
    return any(hmac.compare_digest(_code_at(secret, counter + d), code)
               for d in range(-window, window + 1))


def provisioning_uri(secret: str, account: str, issuer: str = "open-refinery") -> str:
    """otpauth:// URI for an authenticator app (QR / manual entry)."""
    params = urllib.parse.urlencode({"secret": secret, "issuer": issuer,
                                     "digits": DIGITS, "period": STEP})
    return f"otpauth://totp/{urllib.parse.quote(f'{issuer}:{account}')}?{params}"
