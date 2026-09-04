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


def canonicalize_lock_path(path: Path | str, *, label: str) -> Path:
    """Expand ``~``, require absolute, then ``resolve(strict=False)`` once."""
    if path is None or str(path).strip() == "":
        raise LockPathError(f"{label} is required (fail closed); inject an explicit path")
    expanded = Path(path).expanduser()
    if not expanded.is_absolute():
        raise LockPathError(f"{label} must be an absolute path: got {path!s}")
    return expanded.resolve(strict=False)


def _is_under(path: Path, root: Path) -> bool:
    """True if *path* is *root* or a descendant. Both args must already be canonical."""
    path_pure = PurePath(path.as_posix())
    root_pure = PurePath(root.as_posix())
    if path_pure == root_pure:
        return True
    return root_pure in path_pure.parents


def reject_paired_capture_path(path: Path, *, label: str) -> None:
    """Fail closed if canonical *path* is inside the paired-capture lock directory."""
    root = canonicalize_lock_path(PAIRED_CAPTURE_LOCK_ROOT, label="paired_capture_root")
    if _is_under(path, root):
        raise LockPathError(
            f"{label} must not use the paired-capture lock namespace "
            f"({PAIRED_CAPTURE_LOCK_ROOT}): got {path}"
        )


def require_lock_path(path: Path | str | None, *, label: str) -> Path:
    """Canonicalize an explicit lock path and reject paired-capture collisions."""
    if path is None or str(path).strip() == "":
        raise LockPathError(f"{label} is required (fail closed); inject an explicit path")
    canonical = canonicalize_lock_path(path, label=label)
    reject_paired_capture_path(canonical, label=label)
    return canonical


@dataclass(frozen=True)
class LockPathConfig:
    """Injectable dispatcher lock paths (no defaults into paired-capture)."""

    global_agent_lock: Path
    implementation_lock: Path

    def __post_init__(self) -> None:
        global_agent_lock = require_lock_path(
            self.global_agent_lock, label="global_agent_lock"
        )
        implementation_lock = require_lock_path(
            self.implementation_lock, label="implementation_lock"
        )
        if global_agent_lock == implementation_lock:
            raise LockPathError(
                "global_agent_lock and implementation_lock must be distinct paths"
            )
        object.__setattr__(self, "global_agent_lock", global_agent_lock)
        object.__setattr__(self, "implementation_lock", implementation_lock)


__all__ = [
    "LockPathConfig",
    "LockPathError",
    "PAIRED_CAPTURE_LOCK_ROOT",
    "canonicalize_lock_path",
    "reject_paired_capture_path",
    "require_lock_path",
]
