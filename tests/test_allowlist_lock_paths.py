"""Task D: injectable nonempty allowlist + lock-path config."""

from __future__ import annotations

import unittest
from pathlib import Path

from codex_dispatcher.adapter import AdapterConfig, AdapterDisabled, CodingAgentAdapter
from codex_dispatcher.allowlist import AllowlistError, require_nonempty_allowlist
from codex_dispatcher.github import GitHubIssueSource
from codex_dispatcher.lock import (
    PAIRED_CAPTURE_LOCK_ROOT,
    LockPathConfig,
    LockPathError,
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

    def test_rejects_paired_capture_namespace(self) -> None:
        bad = PAIRED_CAPTURE_LOCK_ROOT / "capture-abc.lock"
        with self.assertRaises(LockPathError) as ctx:
            require_lock_path(bad, label="global_agent_lock")
        self.assertIn("paired-capture", str(ctx.exception))

    def test_rejects_paired_capture_root_itself(self) -> None:
        with self.assertRaises(LockPathError):
            require_lock_path(PAIRED_CAPTURE_LOCK_ROOT, label="implementation_lock")

    def test_no_default_into_paired_capture(self) -> None:
        # Constructing LockPathConfig with paired-capture paths must fail.
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
        self.assertEqual(cfg.global_agent_lock, Path("/run/lock/copymoney-agent.lock"))
        self.assertEqual(
            cfg.implementation_lock,
            Path("/run/lock/copymoney-agent-implementation.lock"),
        )

    def test_lock_paths_must_be_distinct(self) -> None:
        with self.assertRaises(LockPathError):
            LockPathConfig(
                global_agent_lock=Path("/run/lock/copymoney-agent.lock"),
                implementation_lock=Path("/run/lock/copymoney-agent.lock"),
            )


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
            Path("/run/lock/copymoney-agent.lock"),
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


if __name__ == "__main__":
    unittest.main()
