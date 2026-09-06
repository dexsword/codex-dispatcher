"""SecureProcessLock — dirfd/openat pair locks (Task F1 / Astra A4).

OPS1 — not this module — provisions the production root
``/run/lock/codex-dispatcher/``. Runtime verifies an injected, already-created
root and fails closed. This module must not mkdir/chmod/fchmod the root, must
not silently fchmod a wrong-mode lock file, and must not fall back to ``/tmp``
or the repository.

CopyMoney ``ProcessLock`` and PR #20 ``SecureCaptureLock`` are not implemented
here and must stay untouched.
"""

from __future__ import annotations

import errno
import fcntl
import os
import stat
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from codex_dispatcher.lock.paths import (
    LockPathConfig,
    LockPathError,
    canonicalize_lock_path,
    reject_paired_capture_path,
    require_lock_path,
)

# Intended production root. F1 never creates this path; OPS1 does.
INTENDED_PRODUCTION_LOCK_ROOT = Path("/run/lock/codex-dispatcher")

AGENT_LOCK_BASENAME = "agent.lock"
IMPLEMENTATION_LOCK_BASENAME = "implementation.lock"
ALLOWED_LOCK_BASENAMES = frozenset({AGENT_LOCK_BASENAME, IMPLEMENTATION_LOCK_BASENAME})

ROOT_DIR_MODE = 0o700
LOCK_FILE_MODE = 0o600

ROOT_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
LOCK_OPEN_FLAGS = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC

# Same-process double-acquire guard. Cross-process exclusion is flock.
_HELD_INODES: set[tuple[int, int]] = set()
_HELD_GUARD = threading.Lock()


class AlreadyLocked(RuntimeError):
    """Non-blocking exclusive flock would block (busy lock)."""


class LockConfigurationError(RuntimeError):
    """Wrong mode/owner/symlink/basename, or missing OPS1-precreated root."""


def require_allowed_lock_basename(basename: str) -> str:
    """Reject crafted/escaped names *before* ``openat``.

    The openat name must be exactly ``agent.lock`` or ``implementation.lock``.
    ``../agent.lock``, ``foo/agent.lock``, NUL, case variants, trailing dots,
    empty strings, and absolute-looking names are rejected.
    """
    if not isinstance(basename, str):
        raise LockConfigurationError(
            f"lock basename must be a str, got {type(basename).__name__}"
        )
    if "\x00" in basename:
        raise LockConfigurationError("lock basename must not contain NUL")
    if basename not in ALLOWED_LOCK_BASENAMES:
        allowed = ", ".join(sorted(ALLOWED_LOCK_BASENAMES))
        raise LockConfigurationError(
            f"lock basename must be exactly one of: {allowed}; got {basename!r}"
        )
    return basename


def _lexical_root_and_basename(path: Path | str) -> tuple[Path, str]:
    """Split an injected lock-file path without resolving or following links."""
    if isinstance(path, bytes):
        raise LockConfigurationError("lock path must be str or Path, not bytes")
    if path is None or str(path).strip() == "":
        raise LockPathError("lock path is required (fail closed); inject an explicit path")
    raw = os.fspath(path)
    if "\x00" in raw:
        raise LockConfigurationError("lock path must not contain NUL")
    lexical = Path(raw)
    if not lexical.is_absolute():
        raise LockPathError(f"lock path must be an absolute path: got {path!s}")
    parts = lexical.parts
    if any(part in (".", "..") for part in parts):
        raise LockConfigurationError(
            f"lock path must not contain '.' or '..' components: got {raw!r}"
        )
    if len(parts) < 2:
        raise LockConfigurationError(f"lock path must include a directory root: got {raw!r}")
    basename = require_allowed_lock_basename(parts[-1])
    return lexical.parent, basename


def _mode_of(st: os.stat_result) -> int:
    return stat.S_IMODE(st.st_mode)


class SecureProcessLock:
    """Exclusive process lock opened via dirfd + ``openat`` (A4).

    ``path`` is the injected lock file (``<root>/agent.lock`` or
    ``<root>/implementation.lock``). The parent directory is the lock root and
    must already exist with mode ``0700`` and owner ``euid``.
    """

    def __init__(self, path: Path | str, *, job_id: str) -> None:
        if not isinstance(job_id, str) or not job_id.strip():
            raise LockConfigurationError("job_id is required (nonempty str)")
        self._job_id = job_id
        self._root, self._basename = _lexical_root_and_basename(path)
        declared = self._root / self._basename
        require_lock_path(declared, label="lock_path")
        reject_paired_capture_path(
            canonicalize_lock_path(self._root, label="lock_root"),
            label="lock_root",
        )
        self._fd: int | None = None
        self._dirfd: int | None = None
        self._held_key: tuple[int, int] | None = None
        self._acquired = False

    @property
    def root(self) -> Path:
        return self._root

    @property
    def basename(self) -> str:
        return self._basename

    @property
    def path(self) -> Path:
        return self._root / self._basename

    @property
    def lock_fd(self) -> int | None:
        return self._fd

    @property
    def root_dirfd(self) -> int | None:
        return self._dirfd

    @property
    def acquired(self) -> bool:
        return self._acquired

    def acquire(self) -> SecureProcessLock:
        if self._acquired:
            raise AlreadyLocked("this SecureProcessLock instance already holds the lock")
        dirfd = self._open_root_dirfd()
        fd: int | None = None
        held_key: tuple[int, int] | None = None
        flocked = False
        registered = False
        try:
            fd = self._open_lock_fd(dirfd)
            st = os.fstat(fd)
            held_key = (st.st_dev, st.st_ino)
            with _HELD_GUARD:
                if held_key in _HELD_INODES:
                    raise AlreadyLocked(f"lock is busy (same process): {self._basename}")
                self._flock_exclusive_nonblocking(fd)
                flocked = True
                _HELD_INODES.add(held_key)
                registered = True
            self._write_payload_after_flock(fd)
            self._dirfd = dirfd
            self._fd = fd
            self._held_key = held_key
            self._acquired = True
            return self
        except Exception:
            if registered and held_key is not None:
                with _HELD_GUARD:
                    _HELD_INODES.discard(held_key)
            if fd is not None:
                if flocked:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    except OSError:
                        pass
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                os.close(dirfd)
            except OSError:
                pass
            raise

    def release(self) -> None:
        fd = self._fd
        dirfd = self._dirfd
        key = self._held_key
        self._fd = None
        self._dirfd = None
        self._held_key = None
        self._acquired = False
        try:
            if fd is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
                try:
                    os.close(fd)
                except OSError:
                    pass
        finally:
            if dirfd is not None:
                try:
                    os.close(dirfd)
                except OSError:
                    pass
            if key is not None:
                with _HELD_GUARD:
                    _HELD_INODES.discard(key)

    def __enter__(self) -> SecureProcessLock:
        return self.acquire()

    def __exit__(self, *exc: object) -> None:
        self.release()

    def _open_root_dirfd(self) -> int:
        """Open the injected root. Never mkdir/chmod/repair on failure."""
        try:
            dirfd = os.open(os.fspath(self._root), ROOT_OPEN_FLAGS)
        except FileNotFoundError as exc:
            raise LockConfigurationError(
                f"lock root does not exist (OPS1 must pre-create it; "
                f"runtime will not create it): {self._root}"
            ) from exc
        except OSError as exc:
            raise LockConfigurationError(
                f"failed to open lock root {self._root}: {exc}"
            ) from exc
        try:
            self._check_root_stat(os.fstat(dirfd))
        except Exception:
            try:
                os.close(dirfd)
            except OSError:
                pass
            raise
        return dirfd

    def _check_root_stat(self, st: os.stat_result) -> None:
        if not stat.S_ISDIR(st.st_mode):
            raise LockConfigurationError(f"lock root is not a directory: {self._root}")
        mode = _mode_of(st)
        if mode != ROOT_DIR_MODE:
            raise LockConfigurationError(
                f"lock root mode must be exactly 0700, got {mode:04o} "
                f"(fail closed; runtime will not chmod/repair): {self._root}"
            )
        if st.st_uid != os.geteuid():
            raise LockConfigurationError(
                f"lock root owner {st.st_uid} must match euid {os.geteuid()} "
                f"(fail closed; no fallback): {self._root}"
            )

    def _open_lock_fd(self, dirfd: int) -> int:
        # Re-validate immediately before openat — never pass a crafted name.
        name = require_allowed_lock_basename(self._basename)
        try:
            fd = os.open(name, LOCK_OPEN_FLAGS, LOCK_FILE_MODE, dir_fd=dirfd)
        except OSError as exc:
            raise LockConfigurationError(
                f"failed to open lock file {name!r} via openat: {exc}"
            ) from exc
        try:
            self._check_lock_stat(os.fstat(fd))
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        return fd

    def _check_lock_stat(self, st: os.stat_result) -> None:
        if not stat.S_ISREG(st.st_mode):
            raise LockConfigurationError(
                f"lock must be a regular file (fail closed): {self._basename}"
            )
        if st.st_uid != os.geteuid():
            raise LockConfigurationError(
                f"lock file owner {st.st_uid} must match euid {os.geteuid()} "
                f"(fail closed; no silent fchmod): {self._basename}"
            )
        if st.st_nlink != 1:
            raise LockConfigurationError(
                f"lock file nlink must be 1, got {st.st_nlink} "
                f"(fail closed): {self._basename}"
            )
        mode = _mode_of(st)
        if mode != LOCK_FILE_MODE:
            raise LockConfigurationError(
                f"lock file mode must be exactly 0600, got {mode:04o} "
                f"(fail closed; no silent fchmod): {self._basename}"
            )

    def _flock_exclusive_nonblocking(self, fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AlreadyLocked(f"lock is busy: {self._basename}") from exc
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                raise AlreadyLocked(f"lock is busy: {self._basename}") from exc
            raise LockConfigurationError(
                f"flock failed on {self._basename}: {exc}"
            ) from exc

    def _write_payload_after_flock(self, fd: int) -> None:
        """Informational pid/job_id/started_at. Not used for steal. After flock."""
        started = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        payload = (
            f"pid={os.getpid()}\n"
            f"job_id={self._job_id}\n"
            f"started_at={started}\n"
        ).encode("utf-8")
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, payload)


@dataclass(frozen=True)
class SecureLockPair:
    """Global agent lock then implementation lock; reverse release.

    If the second acquire fails, the first is released and closed immediately.
    """

    global_agent: SecureProcessLock
    implementation: SecureProcessLock

    def __post_init__(self) -> None:
        if self.global_agent.basename != AGENT_LOCK_BASENAME:
            raise LockConfigurationError(
                "SecureLockPair.global_agent basename must be exactly "
                f"{AGENT_LOCK_BASENAME!r}"
            )
        if self.implementation.basename != IMPLEMENTATION_LOCK_BASENAME:
            raise LockConfigurationError(
                "SecureLockPair.implementation basename must be exactly "
                f"{IMPLEMENTATION_LOCK_BASENAME!r}"
            )
        if self.global_agent.root != self.implementation.root:
            raise LockConfigurationError(
                "SecureLockPair locks must share the same injected root"
            )

    @classmethod
    def from_config(cls, config: LockPathConfig, *, job_id: str) -> SecureLockPair:
        if not isinstance(config, LockPathConfig):
            raise LockPathError("config must be a LockPathConfig instance")
        return cls(
            global_agent=SecureProcessLock(config.global_agent_lock, job_id=job_id),
            implementation=SecureProcessLock(config.implementation_lock, job_id=job_id),
        )

    def acquire(self) -> SecureLockPair:
        self.global_agent.acquire()
        try:
            self.implementation.acquire()
        except BaseException:
            self.global_agent.release()
            raise
        return self

    def release(self) -> None:
        try:
            self.implementation.release()
        finally:
            self.global_agent.release()

    def __enter__(self) -> SecureLockPair:
        return self.acquire()

    def __exit__(self, *exc: object) -> None:
        self.release()


__all__ = [
    "AGENT_LOCK_BASENAME",
    "ALLOWED_LOCK_BASENAMES",
    "AlreadyLocked",
    "IMPLEMENTATION_LOCK_BASENAME",
    "INTENDED_PRODUCTION_LOCK_ROOT",
    "LOCK_FILE_MODE",
    "LOCK_OPEN_FLAGS",
    "LockConfigurationError",
    "ROOT_DIR_MODE",
    "ROOT_OPEN_FLAGS",
    "SecureLockPair",
    "SecureProcessLock",
    "require_allowed_lock_basename",
]
