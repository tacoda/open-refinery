"""Encryption for secrets at rest — service credentials, keyed off SECRET_KEY.

Service tokens (GitHub, GitLab, …) must be decryptable to call the service, so
they are symmetrically encrypted with Fernet. The key is derived from the
`SECRET_KEY` environment variable.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet


def _fernet() -> Fernet:
    secret = os.environ.get("SECRET_KEY")
    if not secret:
        raise RuntimeError("SECRET_KEY must be set to store service credentials")
    # ponytail: SECRET_KEY is already a high-entropy secret; sha256 -> 32-byte
    # Fernet key. Swap in a salted KDF if key rotation/derivation needs grow.
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
