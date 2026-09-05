"""Shared runtime checks for generic public input and collaborator contracts."""

from collections.abc import Mapping, Sequence
from typing import Any


class ValidationError(ValueError):
    """Malformed public input or an invalid injected-component result."""


def require_string(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be a string")
    return value


def require_strings(value: object, *, label: str) -> tuple[str, ...]:
    """Snapshot a sequence of strings without scalar iteration or coercion."""
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValidationError(f"{label} must be a sequence of strings")
    return tuple(require_string(item, label=f"{label}[{i}]") for i, item in enumerate(value))


def require_mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{label} must be a mapping")
    return value


def require_boolean(value: object, *, label: str) -> bool:
    if type(value) is not bool:
        raise ValidationError(f"{label} must return a boolean")
    return value


def require_none(value: object, *, label: str) -> None:
    if value is not None:
        raise ValidationError(f"{label} must return None on success or raise on rejection")
