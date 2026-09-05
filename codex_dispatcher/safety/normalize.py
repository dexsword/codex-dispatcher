"""Path normalization and escape detection for SafetyPolicy."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePosixPath

from codex_dispatcher.safety.codes import PATH_ESCAPE


def normalize_path(raw: str) -> tuple[str | None, str | None]:
    """Normalize a relative path for rule matching.

    Returns ``(normalized, None)`` on success, or ``(None, detail)`` when the
    path is absolute, contains a ``..`` segment, or embeds a NUL byte
    (``PATH_ESCAPE``). Embedded NUL is rejected before any policy matching.
    """
    text = str(raw)
    if "\x00" in text:
        return None, f"embedded NUL rejected: {text!r}"

    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts:
        return None, f"absolute path or '..' segment rejected: {text!r}"
    normalized = path.as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if "\x00" in normalized:
        return None, f"embedded NUL rejected: {text!r}"
    return normalized, None


def structural_path_errors(paths: Sequence[str]) -> list[tuple[str, str]]:
    """Return ``(raw, message)`` for every path that fails structural normalize."""
    errors: list[tuple[str, str]] = []
    for raw in paths:
        _normalized, err = normalize_path(raw)
        if err is not None:
            errors.append((str(raw), err))
    return errors


__all__ = ["PATH_ESCAPE", "normalize_path", "structural_path_errors"]
