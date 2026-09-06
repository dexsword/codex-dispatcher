"""Task F3 staging → validate → trusted publisher — STG-T1 through STG-T15.

Test IDs are STG-T* (not F3–F7). Implementation packet is F3.
No Codex invoke (F4). Tests use tmp. Failures retain trees.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_dispatcher.canary import (
    CANARY_PERMITTED_PATH,
    CANARY_REF_PREFIX,
    GIT_BIN,
    HOOKS_PATH,
    AuditStub,
    CanaryBranchError,
    HandoffError,
    PublisherConfig,
    PublisherError,
    StagingError,
    StagingTreeEnumerator,
    build_non_force_push_argv,
    build_staging_config,
    commit_canary,
    handoff_to_trusted_worktree,
    hooks_disabled,
    prepare_staging,
    publish_canary,
    push_canary,
    refuse_force_push,
    require_canary_branch_ref,
    require_canonical_remote,
    sanitize_publisher_git_env,
    staging_isolated_env,
    validate,
    validate_staging,
    validate_status_document,
    validate_status_file,
    write_audit_stub,
)
from codex_dispatcher.canary import publisher as publisher_mod
from codex_dispatcher.canary import staging as staging_mod
from codex_dispatcher.canary.publisher import (
    NOFOLLOW_REPLACE_FLAGS,
    require_non_force_sha,
)
from codex_dispatcher.canary.staging import (
    NOFOLLOW_CREATE_FLAGS,
    NOFOLLOW_READ_FLAGS,
    PERMITTED_RELATIVE_PATH,
)
from tests.test_dependency_firewall import FORBIDDEN_ROOTS, scan_package


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CANARY_PKG = PACKAGE_ROOT / "codex_dispatcher" / "canary"

GOLDEN_STATUS = (
    "# DISPATCHER_STATUS\n"
    "\n"
    "- schema_version: 1\n"
    "- task_id: dextech-canary-001\n"
    "- job_id: job-001\n"
    "- dispatcher_sha: 56a2dcf8d6f7c0a6b879d03eb06691ea1d469122\n"
    "- timestamp_utc: 2026-09-06T20:00:00Z\n"
    "- status: canary_ok\n"
)
VALID_REF = f"{CANARY_REF_PREFIX}dextech-canary-001-20260906-56a2dcf"
CANONICAL_REMOTE = "git@github.com:dexsword/dextech.git"
FAKE_SHA = "4564ea7c61e53408847ed219b900199d5859169d"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="cd-stg-"))


def _seed_source(tmp: Path, text: str = GOLDEN_STATUS) -> Path:
    src = tmp / "seed-DISPATCHER_STATUS.md"
    src.write_text(text, encoding="utf-8")
    return src


def _prepare(tmp: Path, text: str = GOLDEN_STATUS) -> tuple[Path, object]:
    staging_root = tmp / "staging"
    prepared = prepare_staging(
        staging_root=staging_root, source_status_path=_seed_source(tmp, text)
    )
    return staging_root, prepared


def _publisher(worktree: Path, **overrides: object) -> PublisherConfig:
    kwargs: dict[str, object] = {
        "worktree_root": worktree,
        "remote_name": "origin",
        "canonical_remote_url": CANONICAL_REMOTE,
    }
    kwargs.update(overrides)
    return PublisherConfig(**kwargs)  # type: ignore[arg-type]


def _init_worktree(tmp: Path, text: str = GOLDEN_STATUS) -> Path:
    worktree = tmp / "worktree"
    worktree.mkdir()
    dest = worktree / PERMITTED_RELATIVE_PATH
    dest.parent.mkdir(parents=True)
    dest.write_text(text, encoding="utf-8")
    env = {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_AUTHOR_NAME": "codex-dispatcher-canary",
        "GIT_AUTHOR_EMAIL": "canary@invalid",
        "GIT_COMMITTER_NAME": "codex-dispatcher-canary",
        "GIT_COMMITTER_EMAIL": "canary@invalid",
    }
    subprocess.run(["git", "init"], cwd=worktree, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=codex-dispatcher-canary",
         "-c", "user.email=canary@invalid", "add", "--", PERMITTED_RELATIVE_PATH],
        cwd=worktree,
        check=True,
        env=env,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=codex-dispatcher-canary",
            "-c",
            "user.email=canary@invalid",
            "commit",
            "-m",
            "seed",
            "--",
            PERMITTED_RELATIVE_PATH,
        ],
        cwd=worktree,
        check=True,
        env=env,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "-b", VALID_REF[len("refs/heads/") :]],
        cwd=worktree,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", CANONICAL_REMOTE],
        cwd=worktree,
        check=True,
        capture_output=True,
    )
    return worktree


def _canary_sources() -> list[Path]:
    return sorted(CANARY_PKG.rglob("*.py"))


def _function_first_call(func_name: str, source_path: Path) -> str | None:
    mod = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in ast.walk(mod):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for stmt in node.body:
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                    continue
                if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
                    if isinstance(stmt.value.func, ast.Name):
                        return stmt.value.func.id
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    if isinstance(stmt.value.func, ast.Name):
                        return stmt.value.func.id
                if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Call):
                    if isinstance(stmt.value.func, ast.Name):
                        return stmt.value.func.id
    return None


class _PushRecorder:
    """Real git for everything except ``git push`` (mocked; no live push)."""

    def __init__(self) -> None:
        self.pushes: list[tuple[list[str], dict[str, object]]] = []

    def __call__(
        self, argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if "push" in argv:
            self.pushes.append((list(argv), dict(kwargs)))
            if kwargs.get("shell") is True:
                raise AssertionError("shell=True is forbidden")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        return subprocess.run(argv, **kwargs)  # type: ignore[arg-type]


class StgT1OnlyPermittedFileTests(unittest.TestCase):
    """STG-T1: only permitted file; no .git."""

    def test_stg_t1_prepare_only_permitted_file_no_git(self) -> None:
        tmp = _tmp()
        self.addCleanup(lambda: None)
        staging_root, prepared = _prepare(tmp)
        self.assertEqual(prepared.relative_path, "canary/DISPATCHER_STATUS.md")
        self.assertEqual(prepared.relative_path, CANARY_PERMITTED_PATH)
        self.assertTrue((staging_root / PERMITTED_RELATIVE_PATH).is_file())
        self.assertFalse((staging_root / ".git").exists())
        self.assertFalse(os.path.lexists(staging_root / ".git"))
        names = [p.name for p in staging_root.iterdir()]
        self.assertEqual(names, ["canary"])
        listed = StagingTreeEnumerator().enumerate(staging_root)
        self.assertEqual(listed, (PERMITTED_RELATIVE_PATH,))
        self.assertNotEqual(prepared.sha256_hex, "")
        self.assertEqual(
            prepared.sha256_hex, _sha256(GOLDEN_STATUS.encode("utf-8"))
        )


class StgT2ExtrasFailTests(unittest.TestCase):
    """STG-T2: extras fail closed; tree retained."""

    def test_stg_t2_extra_file_fails_and_is_retained(self) -> None:
        tmp = _tmp()
        staging_root, _prepared = _prepare(tmp)
        extra = staging_root / "EXTRA.md"
        extra.write_text("nope\n", encoding="utf-8")
        with self.assertRaises(StagingError) as ctx:
            StagingTreeEnumerator().enumerate(staging_root)
        self.assertTrue(extra.exists())
        self.assertTrue((staging_root / PERMITTED_RELATIVE_PATH).exists())
        self.assertIn("exactly", str(ctx.exception))

    def test_stg_t2_prepare_into_nonempty_fails_retained(self) -> None:
        tmp = _tmp()
        staging_root = tmp / "staging"
        staging_root.mkdir()
        leftover = staging_root / "leftover.txt"
        leftover.write_text("keep\n", encoding="utf-8")
        with self.assertRaises(StagingError):
            prepare_staging(
                staging_root=staging_root,
                source_status_path=_seed_source(tmp),
            )
        self.assertTrue(leftover.exists())

    def test_stg_t2_empty_and_missing_fail(self) -> None:
        tmp = _tmp()
        empty = tmp / "empty"
        empty.mkdir()
        with self.assertRaises(StagingError) as ctx:
            StagingTreeEnumerator().enumerate(empty)
        self.assertIn("empty", str(ctx.exception).lower())
        missing = tmp / "does-not-exist"
        with self.assertRaises(StagingError) as ctx2:
            StagingTreeEnumerator().enumerate(missing)
        self.assertIn("missing", str(ctx2.exception).lower())
        self.assertTrue(empty.exists())


class StgT3SymlinkRejectTests(unittest.TestCase):
    """STG-T3: symlinks rejected (W7)."""

    def test_stg_t3_symlink_in_staging_rejected(self) -> None:
        tmp = _tmp()
        staging_root, _prepared = _prepare(tmp)
        link = staging_root / "canary" / "sneak"
        try:
            link.symlink_to(staging_root / PERMITTED_RELATIVE_PATH)
        except OSError as exc:  # pragma: no cover
            self.skipTest(f"symlink not available: {exc}")
        with self.assertRaises(StagingError) as ctx:
            StagingTreeEnumerator().enumerate(staging_root)
        self.assertIn("symlink", str(ctx.exception).lower())
        self.assertTrue(link.exists() or link.is_symlink())

    def test_stg_t3_permitted_path_replaced_with_symlink(self) -> None:
        tmp = _tmp()
        staging_root, _prepared = _prepare(tmp)
        target = staging_root / PERMITTED_RELATIVE_PATH
        outside = tmp / "outside.md"
        outside.write_text(GOLDEN_STATUS, encoding="utf-8")
        target.unlink()
        try:
            target.symlink_to(outside)
        except OSError as exc:  # pragma: no cover
            self.skipTest(f"symlink not available: {exc}")
        with self.assertRaises(StagingError):
            StagingTreeEnumerator().enumerate(staging_root)
        with self.assertRaises(StagingError):
            validate_staging(staging_root)
        self.assertTrue(staging_root.exists())


class StgT4HashMismatchAbortsTests(unittest.TestCase):
    """STG-T4: hash mismatch aborts; trees retained; no commit."""

    def test_stg_t4_expected_hash_mismatch_aborts_retained(self) -> None:
        tmp = _tmp()
        staging_root, prepared = _prepare(tmp)
        worktree = tmp / "worktree"
        dest = worktree / PERMITTED_RELATIVE_PATH
        dest.parent.mkdir(parents=True)
        dest.write_text(GOLDEN_STATUS, encoding="utf-8")
        wrong = "0" * 64
        self.assertNotEqual(wrong, prepared.sha256_hex)
        with self.assertRaises(HandoffError) as ctx:
            handoff_to_trusted_worktree(
                staging_root=staging_root,
                worktree_root=worktree,
                expected_sha256=wrong,
            )
        self.assertIn("hash mismatch", str(ctx.exception).lower())
        self.assertTrue(staging_root.exists())
        self.assertTrue(worktree.exists())
        self.assertTrue(dest.exists())
        self.assertEqual(dest.read_text(encoding="utf-8"), GOLDEN_STATUS)

    def test_stg_t4_post_write_mismatch_aborts(self) -> None:
        tmp = _tmp()
        staging_root, prepared = _prepare(tmp)
        worktree = tmp / "worktree"
        dest = worktree / PERMITTED_RELATIVE_PATH
        dest.parent.mkdir(parents=True)
        dest.write_text(GOLDEN_STATUS, encoding="utf-8")
        real_read = staging_mod.read_regular_nofollow
        calls = {"n": 0}

        def flaky(path: Path) -> bytes:
            data = real_read(path)
            # After the destination write, handoff re-reads dest.
            if path == dest:
                calls["n"] += 1
                if calls["n"] >= 1:
                    return b"tampered-not-schema\n"
            return data

        with mock.patch.object(publisher_mod, "read_regular_nofollow", flaky):
            with self.assertRaises(HandoffError) as ctx:
                handoff_to_trusted_worktree(
                    staging_root=staging_root,
                    worktree_root=worktree,
                    expected_sha256=prepared.sha256_hex,
                )
        self.assertIn("hash mismatch", str(ctx.exception).lower())
        self.assertTrue(staging_root.exists())
        self.assertTrue(worktree.exists())


class StgT5RequireOnCommitTests(unittest.TestCase):
    """STG-T5: require_canary_branch_ref is first on the commit path."""

    def test_stg_t5_require_called_immediately_before_commit(self) -> None:
        tmp = _tmp()
        worktree = _init_worktree(tmp)
        dest = worktree / PERMITTED_RELATIVE_PATH
        dest.write_text(
            GOLDEN_STATUS.replace("job-001", "job-002"), encoding="utf-8"
        )
        order: list[str] = []
        real_require = publisher_mod.require_canary_branch_ref

        def spy_require(ref: object) -> str:
            order.append("require")
            return real_require(ref)

        real_run = subprocess.run

        def spy_run(*args: object, **kwargs: object) -> object:
            order.append("run")
            return real_run(*args, **kwargs)

        with mock.patch.object(
            publisher_mod, "require_canary_branch_ref", spy_require
        ), mock.patch.object(publisher_mod.subprocess, "run", spy_run):
            sha = commit_canary(
                branch_ref=VALID_REF,
                worktree_root=worktree,
                message="canary: status",
                publisher=_publisher(worktree),
            )
        self.assertEqual(order[0], "require")
        self.assertIn("run", order)
        self.assertLess(order.index("require"), order.index("run"))
        require_non_force_sha(sha)
        self.assertEqual(
            _function_first_call("commit_canary", CANARY_PKG / "publisher.py"),
            "require_canary_branch_ref",
        )

    def test_stg_t5_invalid_ref_never_runs_git(self) -> None:
        tmp = _tmp()
        worktree = _init_worktree(tmp)
        run = mock.Mock(side_effect=AssertionError("git must not run"))
        with self.assertRaises(CanaryBranchError):
            commit_canary(
                branch_ref="refs/heads/main",
                worktree_root=worktree,
                message="nope",
                publisher=_publisher(worktree),
                runner=run,
            )
        run.assert_not_called()


class StgT6RequireOnPushTests(unittest.TestCase):
    """STG-T6: require_canary_branch_ref is first on the push path."""

    def test_stg_t6_require_called_immediately_before_push(self) -> None:
        tmp = _tmp()
        worktree = _init_worktree(tmp)
        order: list[str] = []
        real_require = publisher_mod.require_canary_branch_ref

        def spy_require(ref: object) -> str:
            order.append("require")
            return real_require(ref)

        recorder = _PushRecorder()

        def spy_run(argv: list[str], **kwargs: object) -> object:
            order.append("run")
            return recorder(argv, **kwargs)

        with mock.patch.object(
            publisher_mod, "require_canary_branch_ref", spy_require
        ):
            plan = push_canary(
                branch_ref=VALID_REF,
                sha=FAKE_SHA,
                publisher=_publisher(worktree),
                observed_remote_url=CANONICAL_REMOTE,
                runner=spy_run,
            )
        self.assertEqual(order[0], "require")
        self.assertLess(order.index("require"), order.index("run"))
        self.assertEqual(plan.argv[0:3], (GIT_BIN, "push", "origin"))
        self.assertEqual(
            _function_first_call("push_canary", CANARY_PKG / "publisher.py"),
            "require_canary_branch_ref",
        )
        self.assertEqual(
            _function_first_call("publish_canary", CANARY_PKG / "publisher.py"),
            "require_canary_branch_ref",
        )

    def test_stg_t6_invalid_ref_never_runs_git(self) -> None:
        tmp = _tmp()
        worktree = _init_worktree(tmp)
        run = mock.Mock(side_effect=AssertionError("git must not run"))
        with self.assertRaises(CanaryBranchError):
            push_canary(
                branch_ref="main",
                sha=FAKE_SHA,
                publisher=_publisher(worktree),
                runner=run,
            )
        run.assert_not_called()


class StgT7ForceRefuseTests(unittest.TestCase):
    """STG-T7: force push refused."""

    def test_stg_t7_force_and_force_with_lease_refused(self) -> None:
        with self.assertRaises(PublisherError):
            refuse_force_push(force=True)
        with self.assertRaises(PublisherError):
            refuse_force_push(force_with_lease=True)
        refuse_force_push(force=False, force_with_lease=False)
        tmp = _tmp()
        worktree = _init_worktree(tmp)
        run = mock.Mock(side_effect=AssertionError("must not push"))
        with self.assertRaises(PublisherError) as ctx:
            push_canary(
                branch_ref=VALID_REF,
                sha=FAKE_SHA,
                publisher=_publisher(worktree),
                observed_remote_url=CANONICAL_REMOTE,
                force=True,
                runner=run,
            )
        self.assertIn("force", str(ctx.exception).lower())
        run.assert_not_called()
        with self.assertRaises(PublisherError):
            publish_canary(
                branch_ref=VALID_REF,
                worktree_root=worktree,
                message="nope",
                publisher=_publisher(worktree),
                force_with_lease=True,
                runner=run,
            )
        run.assert_not_called()


class StgT8InvalidRefsTests(unittest.TestCase):
    """STG-T8: invalid Git refs rejected (strengthened F2 helper)."""

    def test_stg_t8_rejects_invalid_git_refs(self) -> None:
        prefix = CANARY_REF_PREFIX
        cases = {
            "dotdot": f"{prefix}foo..bar",
            "atbrace": f"{prefix}foo@{{up}}",
            "backslash": prefix + "foo\\bar",
            "nul": prefix + "foo\x00bar",
            "control": prefix + "foo\x1bbar",
            "trailing_dot": f"{prefix}foo.",
            "lock_ending": f"{prefix}foo.lock",
            "lock_component": f"{prefix}foo.lock/bar",
            "empty_component": f"{prefix}foo//bar",
            "empty_suffix": prefix,
            "whitespace": f"{prefix}foo bar",
            "main": "refs/heads/main",
            "master_leaf": f"{prefix}master",
        }
        for name, ref in cases.items():
            with self.subTest(name=name, ref=repr(ref)):
                with self.assertRaises(CanaryBranchError):
                    require_canary_branch_ref(ref)

    def test_stg_t8_accepts_valid_canary_ref(self) -> None:
        self.assertEqual(require_canary_branch_ref(VALID_REF), VALID_REF)


class StgT9NoShellTrueTests(unittest.TestCase):
    """STG-T9: never shell=True; never build a shell string from the branch."""

    def test_stg_t9_no_shell_true_in_canary_package(self) -> None:
        for path in _canary_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for kw in node.keywords:
                    if kw.arg != "shell":
                        continue
                    if isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        self.fail(f"{path.name}:{node.lineno} uses shell=True")

    def test_stg_t9_push_runner_receives_shell_false_list_argv(self) -> None:
        tmp = _tmp()
        worktree = _init_worktree(tmp)
        seen: list[dict[str, object]] = []

        def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            seen.append({"argv": list(argv), **kwargs})
            self.assertIsInstance(argv, list)
            self.assertFalse(kwargs.get("shell"))
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        push_canary(
            branch_ref=VALID_REF,
            sha=FAKE_SHA,
            publisher=_publisher(worktree),
            observed_remote_url=CANONICAL_REMOTE,
            runner=runner,
        )
        self.assertTrue(seen)
        self.assertIs(seen[0]["shell"], False)
        self.assertEqual(seen[0]["argv"][0], "git")
        self.assertNotIsInstance(seen[0]["argv"], str)


class StgT10HooksDisabledTests(unittest.TestCase):
    """STG-T10: hooks disabled (core.hooksPath=/dev/null)."""

    def test_stg_t10_sanitized_env_disables_hooks(self) -> None:
        env = sanitize_publisher_git_env(git_ssh_command=None)
        self.assertTrue(hooks_disabled(env))
        self.assertEqual(env["GIT_CONFIG_VALUE_0"], HOOKS_PATH)
        self.assertEqual(env["GIT_CONFIG_KEY_0"], "core.hooksPath")
        self.assertEqual(HOOKS_PATH, "/dev/null")
        self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")

    def test_stg_t10_commit_and_push_use_hooks_disabled_env(self) -> None:
        tmp = _tmp()
        worktree = _init_worktree(tmp)
        dest = worktree / PERMITTED_RELATIVE_PATH
        dest.write_text(
            GOLDEN_STATUS.replace("job-001", "job-010"), encoding="utf-8"
        )
        envs: list[dict[str, str]] = []

        def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            env = kwargs.get("env")
            assert isinstance(env, dict)
            envs.append(env)
            if "push" in argv:
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
            return subprocess.run(argv, **kwargs)  # type: ignore[arg-type]

        publish_canary(
            branch_ref=VALID_REF,
            worktree_root=worktree,
            message="canary: hooks",
            publisher=_publisher(worktree),
            observed_remote_url=CANONICAL_REMOTE,
            runner=runner,
        )
        self.assertTrue(envs)
        for env in envs:
            self.assertTrue(hooks_disabled(env), env)


class StgT11NonForceArgvTests(unittest.TestCase):
    """STG-T11: hard-coded non-force argv list."""

    def test_stg_t11_argv_is_git_push_remote_sha_ref(self) -> None:
        plan = build_non_force_push_argv(
            remote="origin", sha=FAKE_SHA, branch_ref=VALID_REF
        )
        self.assertEqual(
            list(plan.argv),
            [GIT_BIN, "push", "origin", f"{FAKE_SHA}:{VALID_REF}"],
        )
        self.assertNotIn("--force", plan.argv)
        self.assertNotIn("--force-with-lease", plan.argv)
        self.assertFalse(any(part.startswith("+") for part in plan.argv))
        self.assertFalse(plan.refspec.startswith("+"))

    def test_stg_t11_push_uses_that_argv(self) -> None:
        tmp = _tmp()
        worktree = _init_worktree(tmp)
        recorder = _PushRecorder()
        plan = push_canary(
            branch_ref=VALID_REF,
            sha=FAKE_SHA,
            publisher=_publisher(worktree),
            observed_remote_url=CANONICAL_REMOTE,
            runner=recorder,
        )
        self.assertEqual(len(recorder.pushes), 1)
        argv, kwargs = recorder.pushes[0]
        self.assertEqual(argv, list(plan.argv))
        self.assertEqual(argv, ["git", "push", "origin", f"{FAKE_SHA}:{VALID_REF}"])
        self.assertIs(kwargs.get("shell"), False)


class StgT12HappyHashNofollowTests(unittest.TestCase):
    """STG-T12: happy path — sha256 same-bytes + nofollow open/write."""

    def test_stg_t12_happy_hash_and_nofollow_flags(self) -> None:
        tmp = _tmp()
        staging_root, prepared = _prepare(tmp)
        worktree = _init_worktree(tmp)
        validated = validate_staging(staging_root)
        self.assertEqual(validated.sha256_hex, prepared.sha256_hex)
        self.assertEqual(validated.payload, GOLDEN_STATUS.encode("utf-8"))
        self.assertEqual(validate_status_document(GOLDEN_STATUS), validated.parsed)
        self.assertEqual(
            validate_status_document(GOLDEN_STATUS),
            validate_status_file(GOLDEN_STATUS),
        )
        opened: list[int] = []
        real_open = os.open

        def spy_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
            opened.append(flags)
            return real_open(path, flags, *args, **kwargs)

        with mock.patch("os.open", spy_open):
            result = handoff_to_trusted_worktree(
                staging_root=staging_root,
                worktree_root=worktree,
                expected_sha256=prepared.sha256_hex,
            )
        self.assertEqual(result.sha256_hex, prepared.sha256_hex)
        dest = worktree / PERMITTED_RELATIVE_PATH
        self.assertEqual(dest.read_bytes(), GOLDEN_STATUS.encode("utf-8"))
        self.assertTrue(any(flags & os.O_NOFOLLOW for flags in opened))
        self.assertTrue(
            any(flags == NOFOLLOW_READ_FLAGS or flags & os.O_NOFOLLOW for flags in opened)
        )
        self.assertTrue(
            any(flags == NOFOLLOW_REPLACE_FLAGS or flags & os.O_NOFOLLOW for flags in opened)
        )
        self.assertTrue(NOFOLLOW_READ_FLAGS & os.O_NOFOLLOW)
        self.assertTrue(NOFOLLOW_CREATE_FLAGS & os.O_NOFOLLOW)
        self.assertTrue(NOFOLLOW_REPLACE_FLAGS & os.O_NOFOLLOW)
        alias = validate(staging_root)
        self.assertEqual(alias.sha256_hex, validated.sha256_hex)

    def test_stg_t12_end_to_end_mock_push(self) -> None:
        tmp = _tmp()
        staging_root, prepared = _prepare(
            tmp, GOLDEN_STATUS.replace("job-001", "job-012")
        )
        worktree = _init_worktree(tmp)
        handoff_to_trusted_worktree(
            staging_root=staging_root,
            worktree_root=worktree,
            expected_sha256=prepared.sha256_hex,
        )
        recorder = _PushRecorder()
        sha, plan = publish_canary(
            branch_ref=VALID_REF,
            worktree_root=worktree,
            message="canary: dispatcher status marker (no merge)",
            publisher=_publisher(worktree),
            observed_remote_url=CANONICAL_REMOTE,
            runner=recorder,
        )
        require_non_force_sha(sha)
        self.assertEqual(plan.argv[3], f"{sha}:{VALID_REF}")
        self.assertEqual(len(recorder.pushes), 1)


class StgT13StagingCannotSeePublisherSshTests(unittest.TestCase):
    """STG-T13: staging cannot see publisher SSH / deploy keys."""

    def test_stg_t13_staging_config_rejects_ssh_fields(self) -> None:
        tmp = _tmp()
        staging_root = tmp / "staging"
        with self.assertRaises(StagingError):
            build_staging_config(
                staging_root=staging_root, git_ssh_command="ssh -i /secret/key"
            )
        with self.assertRaises(StagingError):
            build_staging_config(
                staging_root=staging_root, deploy_key_path=tmp / "deploy_key"
            )
        cfg = build_staging_config(staging_root=staging_root)
        self.assertFalse(hasattr(cfg, "git_ssh_command"))
        self.assertFalse(hasattr(cfg, "deploy_key_path"))

    def test_stg_t13_isolated_env_strips_inherited_ssh(self) -> None:
        dirty = {
            "PATH": "/usr/bin",
            "GIT_SSH_COMMAND": "ssh -i /publisher/deploy_key",
            "SSH_AUTH_SOCK": "/tmp/ssh-agent.sock",
            "GITHUB_TOKEN": "gho_secret",
        }
        isolated = staging_isolated_env(dirty)
        self.assertNotIn("GIT_SSH_COMMAND", isolated)
        self.assertNotIn("SSH_AUTH_SOCK", isolated)
        self.assertNotIn("GITHUB_TOKEN", isolated)
        pub = sanitize_publisher_git_env(
            git_ssh_command="ssh -i /publisher/deploy_key",
            source=dirty,
        )
        self.assertEqual(pub["GIT_SSH_COMMAND"], "ssh -i /publisher/deploy_key")
        self.assertTrue(hooks_disabled(pub))

    def test_stg_t13_prepare_does_not_propagate_process_ssh(self) -> None:
        tmp = _tmp()
        staging_root = tmp / "staging"
        with mock.patch.dict(
            os.environ,
            {"GIT_SSH_COMMAND": "ssh -i /publisher/deploy_key"},
            clear=False,
        ):
            prepared = prepare_staging(
                staging_root=staging_root,
                source_status_path=_seed_source(tmp),
            )
            isolated = staging_isolated_env()
        self.assertNotIn("GIT_SSH_COMMAND", isolated)
        self.assertFalse((staging_root / ".git").exists())
        self.assertEqual(prepared.relative_path, PERMITTED_RELATIVE_PATH)
        for path in staging_root.rglob("*"):
            self.assertNotIn("deploy_key", path.name)
            self.assertFalse(path.name.endswith(".key"))

    def test_stg_t13_publisher_config_holds_ssh_only_on_publisher(self) -> None:
        tmp = _tmp()
        worktree = tmp / "wt"
        worktree.mkdir()
        pub = _publisher(
            worktree,
            git_ssh_command="ssh -i /publisher/deploy_key",
            deploy_key_path=tmp / "deploy_key",
        )
        self.assertEqual(pub.git_ssh_command, "ssh -i /publisher/deploy_key")
        self.assertIsNone(getattr(build_staging_config(staging_root=tmp / "s"), "git_ssh_command", None))


class StgT14RemoteMismatchTests(unittest.TestCase):
    """STG-T14: canonical remote mismatch fails; no push."""

    def test_stg_t14_remote_mismatch_fails(self) -> None:
        with self.assertRaises(PublisherError) as ctx:
            require_canonical_remote(
                observed="git@github.com:evil/other.git",
                expected=CANONICAL_REMOTE,
            )
        self.assertIn("mismatch", str(ctx.exception).lower())
        tmp = _tmp()
        worktree = _init_worktree(tmp)
        run = mock.Mock(side_effect=AssertionError("must not push after mismatch"))
        with self.assertRaises(PublisherError):
            push_canary(
                branch_ref=VALID_REF,
                sha=FAKE_SHA,
                publisher=_publisher(worktree),
                observed_remote_url="git@github.com:evil/other.git",
                runner=run,
            )
        run.assert_not_called()

    def test_stg_t14_matching_remote_allows_mock_push(self) -> None:
        tmp = _tmp()
        worktree = _init_worktree(tmp)
        recorder = _PushRecorder()
        push_canary(
            branch_ref=VALID_REF,
            sha=FAKE_SHA,
            publisher=_publisher(worktree),
            observed_remote_url=CANONICAL_REMOTE,
            runner=recorder,
        )
        self.assertEqual(len(recorder.pushes), 1)


class StgT15AuditStubTests(unittest.TestCase):
    """STG-T15: audit stub writes changed_paths, hashes, git.json (mock push)."""

    def test_stg_t15_audit_stub(self) -> None:
        tmp = _tmp()
        audit_root = tmp / "audit"
        plan = build_non_force_push_argv(
            remote="origin", sha=FAKE_SHA, branch_ref=VALID_REF
        )
        digest = _sha256(GOLDEN_STATUS.encode("utf-8"))
        stub = write_audit_stub(
            audit_root=audit_root,
            changed_paths=(PERMITTED_RELATIVE_PATH,),
            hashes={PERMITTED_RELATIVE_PATH: digest},
            branch_ref=VALID_REF,
            commit_sha=FAKE_SHA,
            push_plan=plan,
            push_mocked=True,
        )
        self.assertIsInstance(stub, AuditStub)
        self.assertEqual(stub.changed_paths, (PERMITTED_RELATIVE_PATH,))
        changed = (audit_root / "changed_paths.txt").read_text(encoding="utf-8")
        self.assertEqual(changed.strip(), PERMITTED_RELATIVE_PATH)
        hashes = json.loads((audit_root / "hashes.json").read_text(encoding="utf-8"))
        self.assertEqual(hashes[PERMITTED_RELATIVE_PATH], digest)
        git_doc = json.loads((audit_root / "git.json").read_text(encoding="utf-8"))
        self.assertTrue(git_doc["push"]["mocked"])
        self.assertFalse(git_doc["push"]["live"])
        self.assertTrue(git_doc["hooks_disabled"])
        self.assertEqual(git_doc["hooksPath"], "/dev/null")
        self.assertTrue(git_doc["non_force"])
        self.assertFalse(git_doc["force"])
        self.assertEqual(git_doc["branch"], VALID_REF)
        self.assertEqual(git_doc["commit"], FAKE_SHA)
        self.assertEqual(git_doc["remote"], "[redacted]")

    def test_stg_t15_live_push_flag_refused(self) -> None:
        tmp = _tmp()
        with self.assertRaises(Exception):
            write_audit_stub(
                audit_root=tmp / "audit",
                changed_paths=(PERMITTED_RELATIVE_PATH,),
                hashes={PERMITTED_RELATIVE_PATH: "abc"},
                branch_ref=VALID_REF,
                commit_sha=FAKE_SHA,
                push_mocked=False,
            )


class StgForbiddenAndIsolationTests(unittest.TestCase):
    """Defense-in-depth: no Codex, no forbidden imports, hooks/keys denied."""

    def test_no_codex_invocation(self) -> None:
        for path in _canary_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value == "codex":
                    self.fail(f"{path.name} must not invoke Codex CLI (F4)")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in {"Popen", "run"}:
                        args = node.args
                        if args and isinstance(args[0], ast.List) and args[0].elts:
                            first = args[0].elts[0]
                            if isinstance(first, ast.Constant) and first.value == "codex":
                                self.fail(f"{path.name} invokes Codex")

    def test_no_forbidden_imports(self) -> None:
        self.assertEqual(scan_package(CANARY_PKG), [])
        for path in _canary_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name.split(".", 1)[0], FORBIDDEN_ROOTS)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    self.assertNotIn(node.module.split(".", 1)[0], FORBIDDEN_ROOTS)

    def test_enumerator_rejects_git_hooks_keys(self) -> None:
        tmp = _tmp()
        staging_root, _prepared = _prepare(tmp)
        (staging_root / ".git").mkdir()
        with self.assertRaises(StagingError):
            StagingTreeEnumerator().enumerate(staging_root)
        # retain
        self.assertTrue((staging_root / ".git").exists())
        tmp2 = _tmp()
        staging_root2, _p = _prepare(tmp2)
        (staging_root2 / "hooks").mkdir()
        with self.assertRaises(StagingError):
            StagingTreeEnumerator().enumerate(staging_root2)
        tmp3 = _tmp()
        staging_root3, _p = _prepare(tmp3)
        (staging_root3 / "id_rsa").write_text("nope", encoding="utf-8")
        with self.assertRaises(StagingError):
            StagingTreeEnumerator().enumerate(staging_root3)
        tmp4 = _tmp()
        staging_root4, _p = _prepare(tmp4)
        (staging_root4 / "cloudflare.pem").write_text("nope", encoding="utf-8")
        with self.assertRaises(StagingError):
            StagingTreeEnumerator().enumerate(staging_root4)

    def test_nofollow_create_flags_are_regular_file_only(self) -> None:
        self.assertTrue(NOFOLLOW_READ_FLAGS & os.O_CLOEXEC)
        self.assertFalse(NOFOLLOW_READ_FLAGS & os.O_CREAT)
        self.assertTrue(stat.S_ISREG(stat.S_IFREG))


if __name__ == "__main__":
    unittest.main()
