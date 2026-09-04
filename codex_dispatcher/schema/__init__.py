"""Minimal opaque-ticket helpers (no product schemas)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class TicketShapeError(ValueError):
    """Ticket is not an opaque JSON object mapping."""


def require_ticket_object(value: Any) -> dict[str, Any]:
    """Accept only a JSON object; contents stay opaque to the dispatcher."""
    if not isinstance(value, dict):
        raise TicketShapeError("ticket must be a JSON object")
    # Shallow copy so callers cannot mutate the extracted mapping in-place
    # through shared identity without going through their own policy.
    return dict(value)


def is_mapping(value: Any) -> bool:
    return isinstance(value, Mapping)
