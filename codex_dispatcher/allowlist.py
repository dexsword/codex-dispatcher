"""Injectable nonempty repository allowlist helpers (fail closed)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Set


class AllowlistError(ValueError):
    """Allowlist missing, empty, or does not admit the target repository."""


def require_repository_name(repository: object) -> str:
    """Validate an exact, nonblank identifier without rewriting its spelling."""
    if not isinstance(repository, str) or not repository:
        raise AllowlistError("repository must be a nonempty string")
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in repository):
        raise AllowlistError("repository must not contain whitespace or control characters")
    return repository


def require_nonempty_allowlist(allowed_repositories: Set[str] | None) -> frozenset[str]:
    """Return a frozenset allowlist or raise AllowlistError (fail closed)."""
    if allowed_repositories is None:
        raise AllowlistError(
            "repository allowlist is required (fail closed); pass allowed_repositories explicitly"
        )
    if not isinstance(allowed_repositories, Set):
        raise AllowlistError("repository allowlist must be a set of repository strings")
    frozen = frozenset(allowed_repositories)
    if not frozen:
        raise AllowlistError("repository allowlist is empty")
    for repository in frozen:
        require_repository_name(repository)
    return frozen


def require_repository_allowed(repository: str, allowed_repositories: Set[str]) -> None:
    """Raise AllowlistError unless *repository* is in the nonempty allowlist."""
    allowlist = require_nonempty_allowlist(allowed_repositories)
    require_repository_name(repository)
    if repository not in allowlist:
        raise AllowlistError(f"repository is not in the supplied allowlist: {repository}")


def normalize_allowlist(entries: Iterable[str]) -> frozenset[str]:
    """Explicitly trim string entries and drop blanks; never coerce other types."""
    if isinstance(entries, (str, bytes, bytearray, Mapping)) or not isinstance(entries, Iterable):
        raise AllowlistError("allowlist entries must be a non-scalar iterable of strings")
    normalized: set[str] = set()
    for entry in entries:
        if not isinstance(entry, str):
            raise AllowlistError("allowlist entries must be strings")
        if entry.strip():
            normalized.add(entry.strip())
    return require_nonempty_allowlist(frozenset(normalized))
