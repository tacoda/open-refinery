"""Email — a port with swappable adapters.

Sending email is a connector like any other: a `EmailSender` port with a default
adapter (Linux `mail`). The active sender is swappable (SMTP, SendGrid, … as
adapters) and, in the product, chosen/configured by admin/platform in the UI.
Tests inject `MemorySender`.
"""

from __future__ import annotations

import subprocess
from typing import Protocol


class EmailSender(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class LinuxMailSender:
    """Default adapter — pipe to the local `mail` command."""

    def send(self, to: str, subject: str, body: str) -> None:
        subprocess.run(["mail", "-s", subject, to], input=body.encode(),
                       check=True, timeout=15)


class MemorySender:
    """Test/dev adapter — records instead of sending."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))


_sender: EmailSender = LinuxMailSender()


def set_sender(sender: EmailSender) -> None:
    """Swap the active email adapter (UI config in the product; tests inject one)."""
    global _sender
    _sender = sender


def get_sender() -> EmailSender:
    return _sender


def send_email(to: str, subject: str, body: str) -> None:
    _sender.send(to, subject, body)
