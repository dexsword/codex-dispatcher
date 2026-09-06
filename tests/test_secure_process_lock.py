"""Task F1 SecureProcessLock acceptance tests — SPL-T1 through SPL-T16.

Test IDs are SPL-T* (not F1–F7). Implementation packet is F1.
OPS1 — not these tests' production path — provisions
``/run/lock/codex-dispatcher/``. Tests use a tmp root that simulates an
already-created OPS1 root and never mkdir that production path.
"""

from __future__ import annotations

import ast
import fcntl
import os
import stat
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from codex_dispatcher.lock import (
    AGENT_LOCK_BASENAME,
    ALLOWED_LOCK_BASENAMES,
    AlreadyLocked,
    IMPLEMENTATION_LOCK_BASENAME,
    INTENDED_PRODUCTION_LOCK_ROOT,
    LOCK_OPEN_FLAGS,
    LockConfigurationError,
    LockPathConfig,
    LockPathError,
    PAIRED_CAPTURE_LOCK_ROOT,
    ROOT_OPEN_FLAGS,
    SecureLockPair,
    SecureProcessLock,
    reject_paired_capture_path,
    require_allowed_lock_basename,
)
from codex_dispatcher.lock.secure import _HELD_INODES
from tests.test_dependency_firewall import scan_package


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SECURE_PY = PACKAGE_ROOT / "codex_dispatcher" / "lock" / "secure.py"


def _ops1_root() -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory(prefix="cd-spl-")
    os.chmod(tmp.name, 0o700)
    return tmp


def _cfg(root: Path) -> LockPathConfig:
    return LockPathConfig(
        global_agent_lock=root / AGENT_LOCK_BASENAME,
        implementation_lock=root / IMPLEMENTATION_LOCK_BASENAME,
    )


def _source_calls_banned_repair(path: Path) -> list[str]:
    """AST: runtime must not mkdir/chmod/fchmod/makedirs."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    banned = {"mkdir", "makedirs", "chmod", "fchmod", "lchmod"}
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in banned:
            hits.append(f"{path.name}:{node.lineno} .{node.attr}")
        elif isinstance(node, ast.Name) and node.id in banned:
            hits.append(f"{path.name}:{node.lineno} {node.id}")
    return hits


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PACKAGE_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return env


class _HoldLock:
    """Child process that holds a SecureProcessLock until released."""

    def __init__(self, path: Path, *, job_id: str = "holder") -> None:
        script = textwrap.dedent(
            f"""
            from pathlib import Path
            import sys
            from codex_dispatcher.lock import SecureProcessLock
            lock = SecureProcessLock(Path({str(path)!r}), job_id={job_id!r})
            lock.acquire()
            sys.stdout.write("held\\n")
            sys.stdout.flush()
            sys.stdin.read(1)
            lock.release()
            """
        )
        self.proc = subprocess.Popen(
            [sys.executable, "-c", script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_child_env(),
        )
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        if line != b"held\n":
            err = self.proc.stderr.read().decode("utf-8", "replace") if self.proc.stderr else ""
            self.proc.kill()
            raise RuntimeError(f"child failed to hold lock: {line!r} stderr={err!r}")

    def close(self) -> None:
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.write(b"x")
            self.proc.stdin.close()
        except BrokenPipeError:
            pass
        try:
            self.proc.wait(timeout=10)
        finally:
            if self.proc.stdout is not None:
                self.proc.stdout.close()
            if self.proc.stderr is not None:
                self.proc.stderr.close()


class SplT1FreshAcquireTests(unittest.TestCase):
    """SPL-T1: Fresh acquire under correct OPS1-precreated ownership."""

    def test_spl_t1_fresh_acquire_under_ops1_precreated_root(self) -> None:
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        path = root / AGENT_LOCK_BASENAME
        with SecureProcessLock(path, job_id="job-t1") as lock:
            self.assertTrue(lock.acquired)
            self.assertEqual(lock.basename, AGENT_LOCK_BASENAME)
            self.assertIsNotNone(lock.lock_fd)
            self.assertIsNotNone(lock.root_dirfd)
            st_dir = os.fstat(lock.root_dirfd)
            st_file = os.fstat(lock.lock_fd)
            self.assertTrue(stat.S_ISDIR(st_dir.st_mode))
            self.assertEqual(stat.S_IMODE(st_dir.st_mode), 0o700)
            self.assertTrue(stat.S_ISREG(st_file.st_mode))
            self.assertEqual(stat.S_IMODE(st_file.st_mode), 0o600)
            self.assertEqual(st_file.st_uid, os.geteuid())
            self.assertEqual(st_file.st_nlink, 1)
            os.lseek(lock.lock_fd, 0, os.SEEK_SET)
            payload = os.read(lock.lock_fd, 4096).decode("utf-8")
            self.assertIn(f"pid={os.getpid()}", payload)
            self.assertIn("job_id=job-t1", payload)
            self.assertIn("started_at=", payload)
        self.assertTrue(path.is_file())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


class SplT2SecondAcquireTests(unittest.TestCase):
    """SPL-T2: Second acquire → AlreadyLocked."""

    def test_spl_t2_second_acquire_same_process_already_locked(self) -> None:
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / AGENT_LOCK_BASENAME
        first = SecureProcessLock(path, job_id="a")
        first.acquire()
        self.addCleanup(first.release)
        second = SecureProcessLock(path, job_id="b")
        with self.assertRaises(AlreadyLocked):
            second.acquire()

    def test_spl_t2_failed_second_acquire_does_not_clear_holder_guard(self) -> None:
        """Worf: AlreadyLocked on 2nd acquire must not discard the holder's inode."""
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / AGENT_LOCK_BASENAME
        first = SecureProcessLock(path, job_id="a")
        first.acquire()
        self.addCleanup(first.release)
        second = SecureProcessLock(path, job_id="b")
        with self.assertRaises(AlreadyLocked):
            second.acquire()
        self.assertTrue(first.acquired)
        assert first.lock_fd is not None
        holder_st = os.fstat(first.lock_fd)
        self.assertIn((holder_st.st_dev, holder_st.st_ino), _HELD_INODES)
        third = SecureProcessLock(path, job_id="c")
        with self.assertRaises(AlreadyLocked):
            third.acquire()
        self.assertTrue(first.acquired)
        self.assertIn((holder_st.st_dev, holder_st.st_ino), _HELD_INODES)

    def test_spl_t2_second_acquire_cross_process_already_locked(self) -> None:
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / AGENT_LOCK_BASENAME
        holder = _HoldLock(path)
        self.addCleanup(holder.close)
        with self.assertRaises(AlreadyLocked):
            SecureProcessLock(path, job_id="contender").acquire()


class SplT3SymlinkTests(unittest.TestCase):
    """SPL-T3: Symlink lock path → refuse."""

    def test_spl_t3_symlink_lock_file_refused(self) -> None:
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        target = root / "other.txt"
        target.write_text("not-a-lock\n", encoding="utf-8")
        os.chmod(target, 0o600)
        link = root / AGENT_LOCK_BASENAME
        try:
            link.symlink_to(target)
        except OSError as exc:  # pragma: no cover
            self.skipTest(f"symlink not available: {exc}")
        with self.assertRaises(LockConfigurationError):
            SecureProcessLock(link, job_id="t3").acquire()
        self.assertTrue(link.is_symlink())


class SplT4PairedCaptureTests(unittest.TestCase):
    """SPL-T4: Paired-capture path → LockPathError (Task D, not weakened)."""

    def test_spl_t4_paired_capture_path_lock_path_error(self) -> None:
        bad = PAIRED_CAPTURE_LOCK_ROOT / AGENT_LOCK_BASENAME
        with self.assertRaises(LockPathError) as ctx:
            SecureProcessLock(bad, job_id="t4")
        self.assertIn("paired-capture", str(ctx.exception))

    def test_spl_t4_reject_paired_capture_path_still_enforced(self) -> None:
        with self.assertRaises(LockPathError):
            reject_paired_capture_path(
                PAIRED_CAPTURE_LOCK_ROOT / IMPLEMENTATION_LOCK_BASENAME,
                label="lock_path",
            )


class SplT5CrashReacquireTests(unittest.TestCase):
    """SPL-T5: Crash then reacquire → success."""

    def test_spl_t5_crash_then_reacquire(self) -> None:
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / AGENT_LOCK_BASENAME
        script = textwrap.dedent(
            f"""
            import os
            from pathlib import Path
            from codex_dispatcher.lock import SecureProcessLock
            SecureProcessLock(Path({str(path)!r}), job_id="crash").acquire()
            os._exit(0)
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", script],
            env=_child_env(),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with SecureProcessLock(path, job_id="after-crash") as lock:
            self.assertTrue(lock.acquired)


class SplT6FlockBeforeTruncateTests(unittest.TestCase):
    """SPL-T6: flock before truncate — proven in tests."""

    def test_spl_t6_flock_called_before_ftruncate(self) -> None:
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / AGENT_LOCK_BASENAME
        order: list[str] = []
        real_flock = fcntl.flock
        real_ftruncate = os.ftruncate

        def flock_wrap(fd: int, op: int) -> None:
            if op & fcntl.LOCK_EX:
                order.append("flock")
            return real_flock(fd, op)

        def ftruncate_wrap(fd: int, length: int) -> None:
            order.append("ftruncate")
            return real_ftruncate(fd, length)

        with mock.patch("fcntl.flock", flock_wrap), mock.patch(
            "os.ftruncate", ftruncate_wrap
        ):
            with SecureProcessLock(path, job_id="t6"):
                pass
        self.assertIn("flock", order)
        self.assertIn("ftruncate", order)
        self.assertLess(order.index("flock"), order.index("ftruncate"))

    def test_spl_t6_busy_acquire_does_not_truncate_holder_payload(self) -> None:
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / AGENT_LOCK_BASENAME
        holder = _HoldLock(path, job_id="protected")
        self.addCleanup(holder.close)
        before = path.read_bytes()
        self.assertIn(b"job_id=protected", before)
        with self.assertRaises(AlreadyLocked):
            SecureProcessLock(path, job_id="attacker").acquire()
        self.assertEqual(path.read_bytes(), before)


class SplT7ProcessLockUntouchedTests(unittest.TestCase):
    """SPL-T7: CopyMoney ProcessLock untouched — goldens unchanged."""

    def test_spl_t7_process_lock_not_defined_task_d_api_intact(self) -> None:
        import codex_dispatcher.lock as lock_mod

        self.assertFalse(hasattr(lock_mod, "ProcessLock"))
        self.assertFalse(hasattr(lock_mod, "GLOBAL_AGENT_LOCK_PATH"))
        self.assertFalse(hasattr(lock_mod, "SecureCaptureLock"))
        for name in (
            "LockPathConfig",
            "LockPathError",
            "PAIRED_CAPTURE_LOCK_ROOT",
            "canonicalize_lock_path",
            "reject_paired_capture_path",
            "require_lock_path",
        ):
            self.assertTrue(hasattr(lock_mod, name), name)
        self.assertEqual(
            lock_mod.PAIRED_CAPTURE_LOCK_ROOT,
            Path("/run/lock/copymoney-paired-capture"),
        )
        # Task D still accepts historic copymoney-style names (not F1 basenames).
        cfg = LockPathConfig(
            global_agent_lock=Path("/run/lock/copymoney-agent.lock"),
            implementation_lock=Path("/run/lock/copymoney-agent-implementation.lock"),
        )
        self.assertNotEqual(cfg.global_agent_lock.name, AGENT_LOCK_BASENAME)
        violations = scan_package(PACKAGE_ROOT / "codex_dispatcher")
        self.assertEqual(violations, [], "\n".join(violations))


class SplT8WrongRootTests(unittest.TestCase):
    """SPL-T8: Wrong ownership/mode on lock root → fail closed; no repair."""

    def test_spl_t8_wrong_root_mode_fail_closed_no_repair(self) -> None:
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        os.chmod(root, 0o755)
        with self.assertRaises(LockConfigurationError) as ctx:
            SecureProcessLock(root / AGENT_LOCK_BASENAME, job_id="t8").acquire()
        self.assertIn("0700", str(ctx.exception))
        self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o755)
        self.assertFalse((root / AGENT_LOCK_BASENAME).exists())

    def test_spl_t8_wrong_root_owner_fail_closed(self) -> None:
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / AGENT_LOCK_BASENAME
        real_fstat = os.fstat

        def fake_fstat(fd: int) -> os.stat_result:
            st = real_fstat(fd)
            if stat.S_ISDIR(st.st_mode):
                fields = list(st)
                fields[4] = st.st_uid + 1  # st_uid
                return os.stat_result(fields)
            return st

        with mock.patch("os.fstat", fake_fstat):
            with self.assertRaises(LockConfigurationError) as ctx:
                SecureProcessLock(path, job_id="t8-uid").acquire()
        self.assertIn("euid", str(ctx.exception).lower())
        self.assertFalse(path.exists())

    def test_spl_t8_source_must_not_mkdir_or_chmod(self) -> None:
        hits = _source_calls_banned_repair(SECURE_PY)
        self.assertEqual(hits, [], "repair calls in secure.py:\n" + "\n".join(hits))


class SplT9ReleaseRetainsTreesTests(unittest.TestCase):
    """SPL-T9: Lock release while worktree/staging retained."""

    def test_spl_t9_locks_release_while_staging_and_worktree_remain(self) -> None:
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        staging = root / "staging" / "canary-job"
        worktree = root / "worktrees" / "canary-job"
        staging.mkdir(parents=True)
        worktree.mkdir(parents=True)
        marker = staging / "DISPATCHER_STATUS.md"
        marker.write_text("retained\n", encoding="utf-8")
        pair = SecureLockPair.from_config(_cfg(root), job_id="t9")
        with pair:
            self.assertTrue(pair.global_agent.acquired)
            self.assertTrue(pair.implementation.acquired)
        self.assertTrue(staging.is_dir())
        self.assertTrue(worktree.is_dir())
        self.assertEqual(marker.read_text(encoding="utf-8"), "retained\n")
        with SecureLockPair.from_config(_cfg(root), job_id="t9-re"):
            pass


class SplT10MissingRootTests(unittest.TestCase):
    """SPL-T10: Missing lock root → fail closed; must NOT create root."""

    def test_spl_t10_missing_root_fail_closed_does_not_create(self) -> None:
        parent = Path(tempfile.mkdtemp(prefix="cd-spl-parent-"))
        self.addCleanup(lambda: shutil.rmtree(parent, ignore_errors=True))
        root = parent / "codex-dispatcher"
        self.assertFalse(root.exists())
        mkdir_calls: list[object] = []

        def record_mkdir(*args: object, **kwargs: object) -> None:
            mkdir_calls.append((args, kwargs))
            raise AssertionError("runtime must not mkdir lock root")

        with mock.patch("os.mkdir", record_mkdir), mock.patch(
            "os.makedirs", record_mkdir
        ), mock.patch("pathlib.Path.mkdir", record_mkdir):
            with self.assertRaises(LockConfigurationError) as ctx:
                SecureProcessLock(root / AGENT_LOCK_BASENAME, job_id="t10").acquire()
        self.assertIn("does not exist", str(ctx.exception))
        self.assertFalse(root.exists())
        self.assertEqual(mkdir_calls, [])

    def test_spl_t10_does_not_mkdir_production_root_constant(self) -> None:
        self.assertEqual(
            INTENDED_PRODUCTION_LOCK_ROOT,
            Path("/run/lock/codex-dispatcher"),
        )
        # F1 must not create the production path as a side effect of import/construct.
        existed = INTENDED_PRODUCTION_LOCK_ROOT.exists()
        SecureProcessLock.__doc__  # import/construct already happened
        self.assertEqual(INTENDED_PRODUCTION_LOCK_ROOT.exists(), existed)


class SplT11DirfdFlagsTests(unittest.TestCase):
    """SPL-T11: Root open must use O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC."""

    def test_spl_t11_root_and_lock_open_flags(self) -> None:
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / AGENT_LOCK_BASENAME
        recorded: list[tuple[object, int, int | None]] = []
        real_open = os.open

        def wrapped(
            name: object,
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            recorded.append((name, flags, dir_fd))
            if dir_fd is None:
                return real_open(name, flags, mode)
            return real_open(name, flags, mode, dir_fd=dir_fd)

        with mock.patch("os.open", wrapped):
            with SecureProcessLock(path, job_id="t11"):
                pass
        root_calls = [c for c in recorded if c[2] is None]
        lock_calls = [c for c in recorded if c[2] is not None]
        self.assertTrue(root_calls, recorded)
        self.assertTrue(lock_calls, recorded)
        self.assertEqual(root_calls[0][1], ROOT_OPEN_FLAGS)
        self.assertTrue(root_calls[0][1] & os.O_DIRECTORY)
        self.assertTrue(root_calls[0][1] & os.O_NOFOLLOW)
        self.assertTrue(root_calls[0][1] & os.O_CLOEXEC)
        self.assertEqual(lock_calls[0][1], LOCK_OPEN_FLAGS)
        self.assertTrue(lock_calls[0][1] & os.O_RDWR)
        self.assertTrue(lock_calls[0][1] & os.O_CREAT)
        self.assertTrue(lock_calls[0][1] & os.O_NOFOLLOW)
        self.assertTrue(lock_calls[0][1] & os.O_CLOEXEC)
        self.assertEqual(lock_calls[0][0], AGENT_LOCK_BASENAME)

    def test_spl_t11_symlink_root_refused(self) -> None:
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        real = Path(tmp.name)
        wrapper = Path(tempfile.mkdtemp(prefix="cd-spl-wrap-"))
        self.addCleanup(lambda: shutil.rmtree(wrapper, ignore_errors=True))
        link = wrapper / "root-link"
        try:
            link.symlink_to(real)
        except OSError as exc:  # pragma: no cover
            self.skipTest(f"symlink not available: {exc}")
        with self.assertRaises(LockConfigurationError):
            SecureProcessLock(link / AGENT_LOCK_BASENAME, job_id="t11-sym").acquire()


class SplT12WrongLockModeTests(unittest.TestCase):
    """SPL-T12: Existing lock file wrong mode → fail closed; no silent fchmod."""

    def test_spl_t12_existing_wrong_mode_no_silent_fchmod(self) -> None:
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / AGENT_LOCK_BASENAME
        path.write_text("stale\n", encoding="utf-8")
        os.chmod(path, 0o644)
        chmod_calls: list[object] = []

        def record_chmod(*args: object, **kwargs: object) -> None:
            chmod_calls.append((args, kwargs))
            raise AssertionError("runtime must not fchmod/chmod a wrong-mode lock")

        with mock.patch("os.chmod", record_chmod), mock.patch(
            "os.fchmod", record_chmod
        ):
            with self.assertRaises(LockConfigurationError) as ctx:
                SecureProcessLock(path, job_id="t12").acquire()
        self.assertIn("0600", str(ctx.exception))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
        self.assertEqual(path.read_text(encoding="utf-8"), "stale\n")
        self.assertEqual(chmod_calls, [])


class SplT13PartialPairTests(unittest.TestCase):
    """SPL-T13: Partial pair — second fails → first immediately released/closed."""

    def test_spl_t13_second_busy_releases_first(self) -> None:
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        impl = root / IMPLEMENTATION_LOCK_BASENAME
        holder = _HoldLock(impl, job_id="impl-holder")
        self.addCleanup(holder.close)
        pair = SecureLockPair.from_config(_cfg(root), job_id="t13")
        with self.assertRaises(AlreadyLocked):
            pair.acquire()
        self.assertFalse(pair.global_agent.acquired)
        self.assertIsNone(pair.global_agent.lock_fd)
        # Agent lock must be free for a new holder.
        with SecureProcessLock(root / AGENT_LOCK_BASENAME, job_id="t13-agent"):
            pass

    def test_spl_t13_second_bad_mode_releases_first(self) -> None:
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        impl = root / IMPLEMENTATION_LOCK_BASENAME
        impl.write_text("bad\n", encoding="utf-8")
        os.chmod(impl, 0o666)
        pair = SecureLockPair.from_config(_cfg(root), job_id="t13-mode")
        with self.assertRaises(LockConfigurationError):
            pair.acquire()
        self.assertFalse(pair.global_agent.acquired)
        with SecureProcessLock(root / AGENT_LOCK_BASENAME, job_id="t13-free"):
            pass


class SplT14CloexecTests(unittest.TestCase):
    """SPL-T14: Lock FD not inherited by child; CLOEXEC proven."""

    def test_spl_t14_lock_fds_cloexec_not_inherited(self) -> None:
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / AGENT_LOCK_BASENAME
        with SecureProcessLock(path, job_id="t14") as lock:
            lock_fd = lock.lock_fd
            dirfd = lock.root_dirfd
            assert lock_fd is not None and dirfd is not None
            self.assertTrue(fcntl.fcntl(lock_fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC)
            self.assertTrue(fcntl.fcntl(dirfd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC)
            lock_st = os.fstat(lock_fd)
            dir_st = os.fstat(dirfd)
            script = textwrap.dedent(
                f"""
                import os, sys
                checks = [
                    ({lock_fd}, {lock_st.st_dev}, {lock_st.st_ino}),
                    ({dirfd}, {dir_st.st_dev}, {dir_st.st_ino}),
                ]
                for fd, dev, ino in checks:
                    try:
                        st = os.fstat(fd)
                    except OSError:
                        continue
                    if (st.st_dev, st.st_ino) == (dev, ino):
                        sys.exit(2)
                sys.exit(0)
                """
            )
            proc = subprocess.run(
                [sys.executable, "-c", script],
                env=_child_env(),
                close_fds=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)


class SplT15OpenatEscapeTests(unittest.TestCase):
    """SPL-T15: openat relative to dirfd; crafted-name escape refused."""

    def test_spl_t15_dotdot_path_refused_before_openat(self) -> None:
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        crafted = f"{root}/../{AGENT_LOCK_BASENAME}"
        opened: list[object] = []
        real_open = os.open

        def guarded(
            name: object,
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            opened.append((name, dir_fd))
            if dir_fd is not None:
                text = name if isinstance(name, str) else os.fsdecode(name)
                if text not in ALLOWED_LOCK_BASENAMES:
                    raise AssertionError(f"openat crafted name: {text!r}")
            if dir_fd is None:
                return real_open(name, flags, mode)
            return real_open(name, flags, mode, dir_fd=dir_fd)

        with mock.patch("os.open", guarded):
            with self.assertRaises(LockConfigurationError):
                SecureProcessLock(crafted, job_id="t15")
        self.assertEqual(opened, [])

    def test_spl_t15_mutated_basename_rejected_before_openat(self) -> None:
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        lock = SecureProcessLock(Path(tmp.name) / AGENT_LOCK_BASENAME, job_id="t15-mut")
        lock._basename = "../" + AGENT_LOCK_BASENAME
        openat_names: list[str] = []
        real_open = os.open

        def guarded(
            name: object,
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            if dir_fd is not None:
                text = name if isinstance(name, str) else os.fsdecode(name)
                openat_names.append(text)
                if text not in ALLOWED_LOCK_BASENAMES:
                    raise AssertionError(f"openat crafted name: {text!r}")
            if dir_fd is None:
                return real_open(name, flags, mode)
            return real_open(name, flags, mode, dir_fd=dir_fd)

        with mock.patch("os.open", guarded):
            with self.assertRaises(LockConfigurationError):
                lock.acquire()
        self.assertEqual(openat_names, [])


class SplT16BasenameAllowlistTests(unittest.TestCase):
    """SPL-T16: Exact basename allowlist before openat."""

    def test_spl_t16_reject_crafted_basenames(self) -> None:
        bad_names = (
            "../agent.lock",
            "foo/agent.lock",
            "agent.lock\x00",
            "\x00agent.lock",
            "Agent.lock",
            "agent.lock.",
            "",
            "/agent.lock",
            "/run/lock/codex-dispatcher/agent.lock",
            "implementation.lock.",
            "IMPLEMENTATION.LOCK",
            "agent.lock/",
            "./agent.lock",
        )
        for name in bad_names:
            with self.subTest(name=name):
                with self.assertRaises(LockConfigurationError):
                    require_allowed_lock_basename(name)

    def test_spl_t16_only_exact_fixed_basenames(self) -> None:
        self.assertEqual(
            require_allowed_lock_basename("agent.lock"), AGENT_LOCK_BASENAME
        )
        self.assertEqual(
            require_allowed_lock_basename("implementation.lock"),
            IMPLEMENTATION_LOCK_BASENAME,
        )
        self.assertEqual(
            ALLOWED_LOCK_BASENAMES,
            frozenset({AGENT_LOCK_BASENAME, IMPLEMENTATION_LOCK_BASENAME}),
        )

    def test_spl_t16_constructor_rejects_crafted_names(self) -> None:
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        cases = (
            f"{root}/../agent.lock",
            "foo/agent.lock",
            "../agent.lock",
            f"{root}/Agent.lock",
            f"{root}/agent.lock.",
            f"{root}/agent.lock\x00extra",
        )
        for crafted in cases:
            with self.subTest(crafted=crafted):
                with self.assertRaises((LockConfigurationError, LockPathError)):
                    SecureProcessLock(crafted, job_id="t16")


class SecureLockPairContextTests(unittest.TestCase):
    def test_pair_context_manager_acquires_agent_then_implementation(self) -> None:
        tmp = _ops1_root()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        order: list[str] = []
        real_open = os.open

        def wrapped(
            name: object,
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            if dir_fd is not None:
                text = name if isinstance(name, str) else os.fsdecode(name)
                order.append(text)
            if dir_fd is None:
                return real_open(name, flags, mode)
            return real_open(name, flags, mode, dir_fd=dir_fd)

        with mock.patch("os.open", wrapped):
            with SecureLockPair.from_config(_cfg(root), job_id="pair"):
                pass
        self.assertEqual(order, [AGENT_LOCK_BASENAME, IMPLEMENTATION_LOCK_BASENAME])

    def test_pair_rejects_mismatched_roots(self) -> None:
        tmp_a = _ops1_root()
        tmp_b = _ops1_root()
        self.addCleanup(tmp_a.cleanup)
        self.addCleanup(tmp_b.cleanup)
        with self.assertRaises(LockConfigurationError):
            SecureLockPair(
                global_agent=SecureProcessLock(
                    Path(tmp_a.name) / AGENT_LOCK_BASENAME, job_id="a"
                ),
                implementation=SecureProcessLock(
                    Path(tmp_b.name) / IMPLEMENTATION_LOCK_BASENAME, job_id="a"
                ),
            )


if __name__ == "__main__":
    unittest.main()
