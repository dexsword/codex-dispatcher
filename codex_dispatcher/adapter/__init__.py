"""Coding agent adapter config seams (disabled by default; Task D paths/allowlist).

No agent invocation here. ``verified_noninteractive`` stays false unless a
future approved task flips it. Lock paths are injectable and must not default
into the paired-capture namespace.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codex_dispatcher.allowlist import AllowlistError, require_nonempty_allowlist
from codex_dispatcher.lock import LockPathConfig, LockPathError


class AdapterDisabled(RuntimeError):
    """Adapter invocation refused (not enabled / dry-run posture)."""


@dataclass(frozen=True)
class AdapterConfig:
    """Injectable adapter configuration.

    Fail closed: nonempty allowlist + explicit ``LockPathConfig`` required.
    There are **no** built-in lock path defaults (especially not under
    ``/run/lock/copymoney-paired-capture/``).
    """

    allowed_repositories: frozenset[str]
    lock_paths: LockPathConfig
    verified_noninteractive: bool = False
    output_directory: Path = Path(".codex-dispatcher-output")

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "allowed_repositories",
            require_nonempty_allowlist(self.allowed_repositories),
        )
        if not isinstance(self.lock_paths, LockPathConfig):
            raise LockPathError("lock_paths must be a LockPathConfig instance")


class CodingAgentAdapter:
    """Stub adapter that refuses invocation until a later enablement task."""

    def __init__(self, config: AdapterConfig) -> None:
        self.config = config

    def run(self, *args: object, **kwargs: object) -> None:
        if not self.config.verified_noninteractive:
            raise AdapterDisabled(
                "coding agent adapter is disabled "
                "(verified_noninteractive=False); no invocation performed"
            )
        raise AdapterDisabled(
            "coding agent adapter invocation is not implemented; no invoke performed"
        )


__all__ = [
    "AdapterConfig",
    "AdapterDisabled",
    "AllowlistError",
    "CodingAgentAdapter",
]
