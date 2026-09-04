"""Injectable nonempty repository allowlist helpers (fail closed)."""

from __future__ import annotations

from collections.abc import Iterable, Set


class AllowlistError(ValueError):
    """Allowlist missing, empty, or does not admit the target repository."""


def require_nonempty_allowlist(allowed_repositories: Set[str] | None) -> frozenset[str]:
    """Return a frozenset allowlist or raise AllowlistError (fail closed)."""
    if allowed_repositories is None:
        raise AllowlistError(
            "repository allowlist is required (fail closed); pass allowed_repositories explicitly"
        )
    frozen = frozenset(allowed_repositories)
    if not frozen:
        raise AllowlistError("repository allowlist is empty")
    return frozen


def require_repository_allowed(repository: str, allowed_repositories: Set[str]) -> None:
    """Raise AllowlistError unless *repository* is in the nonempty allowlist."""
    allowlist = require_nonempty_allowlist(allowed_repositories)
    if repository not in allowlist:
        raise AllowlistError(f"repository is not in the supplied allowlist: {repository}")


def normalize_allowlist(entries: Iterable[str]) -> frozenset[str]:
    """Build a frozenset allowlist from entries; empty input fails closed."""
    return require_nonempty_allowlist(frozenset(str(e).strip() for e in entries if str(e).strip()))
