"""Injectable safety policy seam (fail closed when absent)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol, runtime_checkable


class SafetyViolation(Exception):
    """Ticket failed an injected safety policy."""


@runtime_checkable
class SafetyPolicy(Protocol):
    def require_safe(self, ticket: Mapping[str, Any]) -> None:
        """Raise SafetyViolation (or ValueError) if the opaque ticket is unsafe."""


class CallableSafetyPolicy:
    """Adapt a plain callable into a SafetyPolicy."""

    def __init__(self, fn: Callable[[Mapping[str, Any]], None]) -> None:
        self._fn = fn

    def require_safe(self, ticket: Mapping[str, Any]) -> None:
        self._fn(ticket)
