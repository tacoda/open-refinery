"""Test-suite bootstrap.

`SECRET_KEY` encrypts every stored secret (`crypto.py`) and is required by any
code path touching a credential or a setting. Without it 15 tests fail on a
clean clone with `RuntimeError: SECRET_KEY must be set`, which reads as a broken
checkout rather than a missing export.

Fixed, not random: a stable key means a value encrypted in one test reads back
in another, and a rotating key fails with a confusing `InvalidToken` instead of
an obvious message.
"""

from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
