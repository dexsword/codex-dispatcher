"""Lock path injection (Task D) + SecureProcessLock (Task F1).

Task D: injectable paths + paired-capture rejection. No CopyMoney
``ProcessLock`` semantics and no defaults into
``/run/lock/copymoney-paired-capture/``.

Task F1: ``SecureProcessLock`` / ``SecureLockPair`` under an injected
OPS1-precreated root. Runtime never mkdir/chmod/repairs
``/run/lock/codex-dispatcher/``. CopyMoney ``ProcessLock`` and PR #20
``SecureCaptureLock`` stay unimplemented here.
"""

from __future__ import annotations

from codex_dispatcher.lock.paths import (
    PAIRED_CAPTURE_LOCK_ROOT,
    LockPathConfig,
    LockPathError,
    canonicalize_lock_path,
    reject_paired_capture_path,
    require_lock_path,
)
from codex_dispatcher.lock.secure import (
    AGENT_LOCK_BASENAME,
    ALLOWED_LOCK_BASENAMES,
    AlreadyLocked,
    IMPLEMENTATION_LOCK_BASENAME,
    INTENDED_PRODUCTION_LOCK_ROOT,
    LOCK_FILE_MODE,
    LOCK_OPEN_FLAGS,
    LockConfigurationError,
    ROOT_DIR_MODE,
    ROOT_OPEN_FLAGS,
    SecureLockPair,
    SecureProcessLock,
    require_allowed_lock_basename,
)

__all__ = [
    "AGENT_LOCK_BASENAME",
    "ALLOWED_LOCK_BASENAMES",
    "AlreadyLocked",
    "IMPLEMENTATION_LOCK_BASENAME",
    "INTENDED_PRODUCTION_LOCK_ROOT",
    "LOCK_FILE_MODE",
    "LOCK_OPEN_FLAGS",
    "LockConfigurationError",
    "LockPathConfig",
    "LockPathError",
    "PAIRED_CAPTURE_LOCK_ROOT",
    "ROOT_DIR_MODE",
    "ROOT_OPEN_FLAGS",
    "SecureLockPair",
    "SecureProcessLock",
    "canonicalize_lock_path",
    "reject_paired_capture_path",
    "require_allowed_lock_basename",
    "require_lock_path",
]
