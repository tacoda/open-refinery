"""Factory — produces artifacts, wrapping each output in governance."""

from __future__ import annotations

import logging
from typing import Callable

from .audit import AuditSink, MemorySink
from .authz import AllowAll, Authorizer, Unauthorized
from .provenance import Record

log = logging.getLogger("open_refinery")

Recipe = Callable[..., object]


class UnknownRecipe(KeyError):
    """Raised when producing from an unregistered recipe."""


class Factory:
    """Registers recipes and produces artifacts under governance.

    Every ``produce`` call is authorized, run, recorded with provenance and
    ownership, and appended to the audit trail — in that order.
    """

    def __init__(
        self,
        authorizer: Authorizer | None = None,
        audit: AuditSink | None = None,
    ) -> None:
        self._recipes: dict[str, Recipe] = {}
        self._authorizer = authorizer or AllowAll()
        self._audit = audit or MemorySink()

    def register(self, name: str, recipe: Recipe) -> None:
        self._recipes[name] = recipe

    def recipe(self, name: str) -> Callable[[Recipe], Recipe]:
        """Decorator form of :meth:`register`."""

        def decorate(fn: Recipe) -> Recipe:
            self.register(name, fn)
            return fn

        return decorate

    def produce(
        self,
        name: str,
        *,
        actor: str,
        owner: str | None = None,
        **inputs: object,
    ) -> tuple[object, Record]:
        if name not in self._recipes:
            raise UnknownRecipe(name)
        if not self._authorizer.allows(actor, name):
            raise Unauthorized(f"{actor} may not run {name}")

        owner = owner or actor
        artifact = self._recipes[name](**inputs)
        record = Record.of(name, actor, owner, inputs, artifact)
        self._audit.write(record)
        log.info(
            "produced recipe=%s artifact=%s actor=%s owner=%s",
            name,
            record.artifact_id,
            actor,
            owner,
        )
        return artifact, record
