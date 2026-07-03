"""Authorization — the gate checked before a recipe runs."""

from __future__ import annotations

from typing import Protocol


class Unauthorized(Exception):
    """Raised when an actor may not run a recipe."""


class Authorizer(Protocol):
    def allows(self, actor: str, recipe: str) -> bool: ...


class AllowAll:
    """Default authorizer — permits every actor. Replace in production."""

    def allows(self, actor: str, recipe: str) -> bool:
        return True


class AllowList:
    """Permit only (actor, recipe) pairs present in the grant set."""

    def __init__(self, grants: set[tuple[str, str]]) -> None:
        self._grants = grants

    def allows(self, actor: str, recipe: str) -> bool:
        return (actor, recipe) in self._grants
