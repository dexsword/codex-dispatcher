"""Injectable ticket-validation seam (fail closed when absent)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol, runtime_checkable


class TicketValidationError(Exception):
    """Opaque ticket failed an injected validator."""


@runtime_checkable
class TicketValidator(Protocol):
    def validate(self, ticket: Mapping[str, Any]) -> None:
        """Raise TicketValidationError (or ValueError) if invalid."""


class CallableTicketValidator:
    def __init__(self, fn: Callable[[Mapping[str, Any]], None]) -> None:
        self._fn = fn

    def validate(self, ticket: Mapping[str, Any]) -> None:
        self._fn(ticket)
