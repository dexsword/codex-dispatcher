"""Path normalization and escape detection for SafetyPolicy."""

from __future__ import annotations

from pathlib import PurePosixPath


def normalize_path(raw: str) -> tuple[str | None, str | None]:
    """Normalize a relative path for rule matching.

    Returns ``(normalized, None)`` on success, or ``(None, detail)`` when the
    path is absolute or contains a ``..`` segment (``PATH_ESCAPE``).
    """
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        return None, f"absolute path or '..' segment rejected: {raw!r}"
    normalized = path.as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized, None


__all__ = ["normalize_path"]
