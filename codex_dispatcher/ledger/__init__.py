"""Read-only duplicate-check seam (no append, no filesystem mutation)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DuplicateChecker(Protocol):
    def is_duplicate(self, ticket: Mapping[str, Any]) -> bool:
        """Return True when the opaque ticket is already known."""


class CallableDuplicateChecker:
    """Adapt a plain callable into a DuplicateChecker."""

    def __init__(self, fn: Callable[[Mapping[str, Any]], bool]) -> None:
        self._fn = fn

    def is_duplicate(self, ticket: Mapping[str, Any]) -> bool:
        return bool(self._fn(ticket))


class MemoryDuplicateChecker:
    """In-memory duplicate set for tests / offline demos (read-only interface)."""

    def __init__(self, known_keys: set[str] | None = None, *, key_field: str = "id") -> None:
        self._known = set(known_keys or ())
        self._key_field = key_field

    def is_duplicate(self, ticket: Mapping[str, Any]) -> bool:
        key = ticket.get(self._key_field)
        if key is None:
            return False
        return str(key) in self._known
