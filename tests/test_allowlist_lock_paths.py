"""Task D: injectable nonempty allowlist + lock-path config."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_dispatcher.adapter import AdapterConfig, AdapterDisabled, CodingAgentAdapter
from codex_dispatcher.allowlist import AllowlistError, require_nonempty_allowlist
from codex_dispatcher.github import GitHubIssueSource
from codex_dispatcher.lock import (
    PAIRED_CAPTURE_LOCK_ROOT,
    LockPathConfig,
    LockPathError,
    canonicalize_lock_path,
    require_lock_path,
)


class AllowlistInjectionTests(unittest.TestCase):
    def test_require_nonempty_rejects_none(self) -> None:
        with self.assertRaises(AllowlistError):
            require_nonempty_allowlist(None)

    def test_require_nonempty_rejects_empty(self) -> None:
        with self.assertRaises(AllowlistError):
            require_nonempty_allowlist(frozenset())

    def test_github_source_rejects_empty_allowlist(self) -> None:
        with self.assertRaises(AllowlistError):
            GitHubIssueSource(
                "acme/demo",
                token=None,
                allowed_repositories=frozenset(),
            )

    def test_github_source_rejects_missing_allowlist(self) -> None:
        with self.assertRaises(AllowlistError):
            GitHubIssueSource("acme/demo", token=None)

    def test_github_source_accepts_injected_nonempty_allowlist(self) -> None:
        src = GitHubIssueSource(
            "acme/demo",
            token=None,
            allowed_repositories=frozenset({"acme/demo", "acme/other"}),
        )
        self.assertEqual(src.allowed_repositories, frozenset({"acme/demo", "acme/other"}))


class LockPathInjectionTests(unittest.TestCase):
    def test_lock_paths_required(self) -> None:
        with self.assertRaises(LockPathError):
            require_lock_path(None, label="global_agent_lock")
        with self.assertRaises(LockPathError):
            require_lock_path("  ", label="global_agent_lock")

    def test_relative_path_rejected(self) -> None:
        with self.assertRaises(LockPathError) as ctx:
            require_lock_path("relative/agent.lock", label="global_agent_lock")
        self.assertIn("absolute", str(ctx.exception).lower())

    def test_rejects_paired_capture_namespace(self) -> None:
        bad = PAIRED_CAPTURE_LOCK_ROOT / "capture-abc.lock"
        with self.assertRaises(LockPathError) as ctx:
            require_lock_path(bad, label="global_agent_lock")
        self.assertIn("paired-capture", str(ctx.exception))

    def test_rejects_paired_capture_root_itself(self) -> None:
        with self.assertRaises(LockPathError):
            require_lock_path(PAIRED_CAPTURE_LOCK_ROOT, label="implementation_lock")

    def test_rejects_paired_capture_via_dotdot(self) -> None:
        sneaky = Path("/run/lock/copymoney-paired-capture/../copymoney-paired-capture/x.lock")
        with self.assertRaises(LockPathError) as ctx:
            require_lock_path(sneaky, label="global_agent_lock")
        self.assertIn("paired-capture", str(ctx.exception))

    def test_rejects_symlink_into_paired_capture_where_practical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp) / "alias.lock"
            target = PAIRED_CAPTURE_LOCK_ROOT / "capture-from-symlink.lock"
            try:
                link.symlink_to(target)
            except OSError as exc:  # pragma: no cover - platform/fs limits
                self.skipTest(f"symlink not available: {exc}")
            # Symlink path itself may be absolute under /tmp; canonicalize follows it.
            with self.assertRaises(LockPathError) as ctx:
                require_lock_path(link, label="global_agent_lock")
            self.assertIn("paired-capture", str(ctx.exception))

    def test_no_default_into_paired_capture(self) -> None:
        with self.assertRaises(LockPathError):
            LockPathConfig(
                global_agent_lock=PAIRED_CAPTURE_LOCK_ROOT / "x.lock",
                implementation_lock=Path("/run/lock/copymoney-agent-implementation.lock"),
            )

    def test_explicit_disjoint_paths_ok(self) -> None:
        cfg = LockPathConfig(
            global_agent_lock=Path("/run/lock/copymoney-agent.lock"),
            implementation_lock=Path("/run/lock/copymoney-agent-implementation.lock"),
        )
        self.assertEqual(
            cfg.global_agent_lock,
            canonicalize_lock_path(
                Path("/run/lock/copymoney-agent.lock"), label="global_agent_lock"
            ),
        )
        self.assertTrue(cfg.global_agent_lock.is_absolute())
        self.assertTrue(cfg.implementation_lock.is_absolute())

    def test_lock_paths_must_be_distinct(self) -> None:
        with self.assertRaises(LockPathError):
            LockPathConfig(
                global_agent_lock=Path("/run/lock/copymoney-agent.lock"),
                implementation_lock=Path("/run/lock/copymoney-agent.lock"),
            )

    def test_lexically_different_same_canonical_file_rejected(self) -> None:
        a = Path("/run/lock/copymoney-agent.lock")
        b = Path("/run/lock/../lock/copymoney-agent.lock")
        self.assertNotEqual(a.as_posix(), b.as_posix())
        with self.assertRaises(LockPathError) as ctx:
            LockPathConfig(global_agent_lock=a, implementation_lock=b)
        self.assertIn("distinct", str(ctx.exception).lower())


class AdapterConfigTests(unittest.TestCase):
    def _locks(self) -> LockPathConfig:
        return LockPathConfig(
            global_agent_lock=Path("/run/lock/copymoney-agent.lock"),
            implementation_lock=Path("/run/lock/copymoney-agent-implementation.lock"),
        )

    def test_adapter_requires_nonempty_allowlist(self) -> None:
        with self.assertRaises(AllowlistError):
            AdapterConfig(
                allowed_repositories=frozenset(),
                lock_paths=self._locks(),
            )

    def test_adapter_holds_injected_lock_paths(self) -> None:
        cfg = AdapterConfig(
            allowed_repositories=frozenset({"dexsword/copymoney"}),
            lock_paths=self._locks(),
        )
        self.assertIn("dexsword/copymoney", cfg.allowed_repositories)
        self.assertEqual(
            cfg.lock_paths.global_agent_lock,
            canonicalize_lock_path(
                Path("/run/lock/copymoney-agent.lock"), label="global_agent_lock"
            ),
        )
        self.assertFalse(cfg.verified_noninteractive)

    def test_adapter_run_disabled(self) -> None:
        adapter = CodingAgentAdapter(
            AdapterConfig(
                allowed_repositories=frozenset({"acme/demo"}),
                lock_paths=self._locks(),
            )
        )
        with self.assertRaises(AdapterDisabled):
            adapter.run()

    def test_worf_verified_noninteractive_true_still_no_invoke(self) -> None:
        adapter = CodingAgentAdapter(
            AdapterConfig(
                allowed_repositories=frozenset({"acme/demo"}),
                lock_paths=self._locks(),
                verified_noninteractive=True,
            )
        )
        with self.assertRaises(AdapterDisabled) as ctx:
            adapter.run()
        self.assertIn("no invoke", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
