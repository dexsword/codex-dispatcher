"""Injectable lock-path configuration (no ProcessLock semantics).

Task D supplies path injection + fail-closed validation only.
Task F (Will-gated) may add a separate secure lock type later.
This package must not implement or alter CopyMoney ``ProcessLock``.

**Scotty / ops invariant:** a later CopyMoney facade that wires these
paths must not loosen fail-closed lock-path equality checks (product
defaults stay exact; dispatcher must not silently accept alternate
paths). Never default into ``/run/lock/copymoney-paired-capture/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePath

# PR #20 SecureCaptureLock namespace — dispatcher lock paths must stay disjoint.
PAIRED_CAPTURE_LOCK_ROOT = Path("/run/lock/copymoney-paired-capture")


class LockPathError(ValueError):
    """Lock path missing, invalid, or colliding with paired-capture namespace."""


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve()
    except OSError:
        path = path.absolute()
    try:
        resolved_root = root.resolve()
    except OSError:
        resolved_root = root.absolute()
    # Compare lexical + resolved forms so relative tricks cannot sneak in.
    candidates = {path, Path(path.as_posix()), path.expanduser()}
    try:
        candidates.add(path.resolve())
    except OSError:
        pass
    for candidate in candidates:
        pure = PurePath(candidate.as_posix())
        root_pure = PurePath(resolved_root.as_posix())
        if pure == root_pure:
            return True
        if root_pure in pure.parents:
            return True
        # Also catch string-prefix under /run/lock/copymoney-paired-capture/...
        prefix = root_pure.as_posix().rstrip("/") + "/"
        if pure.as_posix() == root_pure.as_posix() or pure.as_posix().startswith(prefix):
            return True
    return False


def reject_paired_capture_path(path: Path, *, label: str) -> None:
    """Fail closed if *path* is inside the paired-capture lock directory."""
    if _is_under(Path(path), PAIRED_CAPTURE_LOCK_ROOT):
        raise LockPathError(
            f"{label} must not use the paired-capture lock namespace "
            f"({PAIRED_CAPTURE_LOCK_ROOT}): got {path}"
        )


def require_lock_path(path: Path | str | None, *, label: str) -> Path:
    """Require an explicit lock path and reject paired-capture collisions."""
    if path is None or str(path).strip() == "":
        raise LockPathError(f"{label} is required (fail closed); inject an explicit path")
    resolved = Path(path)
    reject_paired_capture_path(resolved, label=label)
    return resolved


@dataclass(frozen=True)
class LockPathConfig:
    """Injectable dispatcher lock paths (no defaults into paired-capture)."""

    global_agent_lock: Path
    implementation_lock: Path

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "global_agent_lock",
            require_lock_path(self.global_agent_lock, label="global_agent_lock"),
        )
        object.__setattr__(
            self,
            "implementation_lock",
            require_lock_path(self.implementation_lock, label="implementation_lock"),
        )
        if self.global_agent_lock == self.implementation_lock:
            raise LockPathError(
                "global_agent_lock and implementation_lock must be distinct paths"
            )


__all__ = [
    "LockPathConfig",
    "LockPathError",
    "PAIRED_CAPTURE_LOCK_ROOT",
    "reject_paired_capture_path",
    "require_lock_path",
]
