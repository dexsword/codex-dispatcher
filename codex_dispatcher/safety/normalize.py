"""Path normalization and escape detection for SafetyPolicy."""

from __future__ import annotations

from pathlib import PurePosixPath

from codex_dispatcher.validation import ValidationError, require_string, require_strings


def require_path(raw: object) -> str:
    raw = require_string(raw, label="path")
    if "\x00" in raw:
        raise ValidationError("path must not contain NUL characters")
    return raw


def require_paths(raw: object, *, label: str) -> tuple[str, ...]:
    return tuple(require_path(path) for path in require_strings(raw, label=label))


def normalize_path(raw: str) -> tuple[str | None, str | None]:
    """Normalize a relative path for rule matching.

    Returns ``(normalized, None)`` on success, or ``(None, detail)`` when the
    path is absolute or contains a ``..`` segment (``PATH_ESCAPE``).
    Non-string or NUL-containing paths raise ``ValidationError``.
    """
    path = PurePosixPath(require_path(raw))
    if path.is_absolute() or ".." in path.parts:
        return None, f"absolute path or '..' segment rejected: {raw!r}"
    normalized = path.as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized, None


__all__ = ["normalize_path"]
