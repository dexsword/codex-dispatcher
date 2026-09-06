"""Task F2 CanaryProfile acceptance tests — CFG-T1 through CFG-T10.

Test IDs are CFG-T* (not F2–F7). Implementation packet is F2.
Config surface only: no staging (F3), no Codex invoke (F4), no full
website SafetyRuleConfig fixtures (F5). OPS1 is not F2.
"""

from __future__ import annotations

import ast
import dataclasses
import os
import unittest
from pathlib import Path

from codex_dispatcher.canary import (
    CANARY_ALLOWED_REPOSITORIES,
    CANARY_PERMITTED_PATH,
    CANARY_PERMITTED_PATHS,
    CANARY_REF_PREFIX,
    DISPATCHER_CANARY_LABEL,
    CanaryApiError,
    CanaryBranchError,
    CanaryGateError,
    CanaryProfile,
    CanaryProfileError,
    StatusSchemaError,
    build_canary_profile,
    default_canary_profile,
    minimal_canary_safety_rule_config,
    refuse_open_draft_pr,
    require_activation_gates_satisfied,
    require_canary_branch_ref,
    require_dispatcher_canary_label_from_issue_metadata,
    validate_status_file,
)
from codex_dispatcher.lock import (
    AGENT_LOCK_BASENAME,
    IMPLEMENTATION_LOCK_BASENAME,
    LockPathConfig,
    LockPathError,
    PAIRED_CAPTURE_LOCK_ROOT,
)
from codex_dispatcher.safety import PathRule, SafetyRuleConfig
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


def _locks(
    root: Path = Path("/run/lock/codex-dispatcher"),
) -> LockPathConfig:
    return LockPathConfig(
        global_agent_lock=root / AGENT_LOCK_BASENAME,
        implementation_lock=root / IMPLEMENTATION_LOCK_BASENAME,
    )


def _profile(**overrides: object) -> CanaryProfile:
    kwargs: dict[str, object] = {
        "lock_paths": _locks(),
        "safety_rules": minimal_canary_safety_rule_config(),
    }
    kwargs.update(overrides)
    return CanaryProfile(**kwargs)  # type: ignore[arg-type]


def _empty_safety() -> SafetyRuleConfig:
    return SafetyRuleConfig(denied_paths=(), protected_paths=(), prohibited_actions=())


def _canary_sources() -> list[Path]:
    return sorted(CANARY_PKG.rglob("*.py"))


class CfgT1DefaultsOffTests(unittest.TestCase):
    """CFG-T1: gates default off; checker refuses; does not flip env."""

    def test_cfg_t1_defaults_off(self) -> None:
        profile = default_canary_profile(
            lock_paths=_locks(),
            safety_rules=minimal_canary_safety_rule_config(),
        )
        self.assertFalse(profile.canary_execution_enabled)
        self.assertFalse(profile.verified_noninteractive)
        self.assertFalse(profile.open_draft_pr)
        self.assertFalse(profile.daemon)
        self.assertFalse(profile.unattended_polling)
        with self.assertRaises(CanaryGateError):
            require_activation_gates_satisfied(profile)

    def test_cfg_t1_checker_does_not_flip_env(self) -> None:
        profile = _profile()
        before = dict(os.environ)
        dry = os.environ.get("CODEX_DISPATCHER_DRY_RUN")
        with self.assertRaises(CanaryGateError):
            require_activation_gates_satisfied(profile)
        self.assertEqual(os.environ.get("CODEX_DISPATCHER_DRY_RUN"), dry)
        self.assertEqual(dict(os.environ), before)

    def test_cfg_t1_all_true_plus_branch_only_passes_without_env_flip(self) -> None:
        profile = _profile(
            canary_execution_enabled=True,
            verified_noninteractive=True,
        )
        before = dict(os.environ)
        require_activation_gates_satisfied(profile)
        self.assertEqual(dict(os.environ), before)
        self.assertFalse(profile.open_draft_pr)

    def test_cfg_t1_no_daemon_or_polling_surface(self) -> None:
        profile = _profile()
        self.assertFalse(hasattr(profile, "start_daemon"))
        self.assertFalse(hasattr(profile, "poll"))
        self.assertFalse(hasattr(CanaryProfile, "start_daemon"))
        with self.assertRaises(CanaryProfileError):
            _profile(daemon=True)
        with self.assertRaises(CanaryProfileError):
            _profile(unattended_polling=True)


class CfgT2AllowlistTests(unittest.TestCase):
    """CFG-T2: exact dexsword/dextech allowlist; empty/other fail closed."""

    def test_cfg_t2_exact_allowlist(self) -> None:
        profile = _profile()
        self.assertEqual(profile.allowed_repositories, CANARY_ALLOWED_REPOSITORIES)
        self.assertEqual(profile.allowed_repositories, frozenset({"dexsword/dextech"}))
        self.assertIs(profile.allowed_repositories, CANARY_ALLOWED_REPOSITORIES)

    def test_cfg_t2_empty_fail_closed(self) -> None:
        with self.assertRaises(CanaryProfileError):
            _profile(allowed_repositories=frozenset())

    def test_cfg_t2_other_repo_fail_closed(self) -> None:
        with self.assertRaises(CanaryProfileError):
            _profile(allowed_repositories=frozenset({"dexsword/copymoney"}))
        with self.assertRaises(CanaryProfileError):
            _profile(allowed_repositories=frozenset({"acme/demo"}))

    def test_cfg_t2_no_runtime_expansion(self) -> None:
        profile = _profile()
        with self.assertRaises((TypeError, AttributeError)):
            profile.allowed_repositories.add("dexsword/other")  # type: ignore[attr-defined]
        with self.assertRaises(CanaryProfileError):
            _profile(
                allowed_repositories=frozenset({"dexsword/dextech", "dexsword/other"})
            )


class CfgT3PathTests(unittest.TestCase):
    """CFG-T3: permitted path is exactly canary/DISPATCHER_STATUS.md."""

    def test_cfg_t3_exact_permitted_path(self) -> None:
        profile = _profile()
        self.assertEqual(profile.permitted_paths, CANARY_PERMITTED_PATHS)
        self.assertEqual(profile.permitted_paths, frozenset({CANARY_PERMITTED_PATH}))
        self.assertEqual(CANARY_PERMITTED_PATH, "canary/DISPATCHER_STATUS.md")

    def test_cfg_t3_other_path_fail_closed(self) -> None:
        with self.assertRaises(CanaryProfileError):
            _profile(permitted_paths=frozenset({"index.html"}))
        with self.assertRaises(CanaryProfileError):
            _profile(permitted_paths=frozenset())
        with self.assertRaises(CanaryProfileError):
            _profile(
                permitted_paths=frozenset(
                    {"canary/DISPATCHER_STATUS.md", "canary/EXTRA.md"}
                )
            )


class CfgT4NoOpenDraftPrTests(unittest.TestCase):
    """CFG-T4: open_draft_pr False/absent; PR-open API refused."""

    def test_cfg_t4_open_draft_pr_false_or_absent(self) -> None:
        omitted = _profile()
        self.assertFalse(omitted.open_draft_pr)
        explicit = _profile(open_draft_pr=False)
        self.assertFalse(explicit.open_draft_pr)

    def test_cfg_t4_true_rejected(self) -> None:
        with self.assertRaises(CanaryProfileError):
            _profile(open_draft_pr=True)

    def test_cfg_t4_refuse_pr_open_api(self) -> None:
        with self.assertRaises(CanaryApiError):
            refuse_open_draft_pr()
        import codex_dispatcher.canary as canary_mod

        self.assertFalse(hasattr(canary_mod, "open_pull_request"))
        self.assertFalse(hasattr(canary_mod, "create_pull_request"))
        self.assertFalse(hasattr(canary_mod, "gh_pr_create"))


class CfgT5EmptySafetyRefusedTests(unittest.TestCase):
    """CFG-T5: empty SafetyRuleConfig refused; nonempty stub accepted."""

    def test_cfg_t5_empty_safety_rule_config_refused(self) -> None:
        with self.assertRaises(CanaryProfileError) as ctx:
            _profile(safety_rules=_empty_safety())
        self.assertIn("empty", str(ctx.exception).lower())

    def test_cfg_t5_minimal_stub_accepted(self) -> None:
        stub = minimal_canary_safety_rule_config()
        self.assertTrue(stub.denied_paths)
        profile = _profile(safety_rules=stub)
        self.assertIs(profile.safety_rules, stub)

    def test_cfg_t5_missing_safety_rules_refused(self) -> None:
        with self.assertRaises(TypeError):
            CanaryProfile(lock_paths=_locks())  # type: ignore[call-arg]
        with self.assertRaises(CanaryProfileError):
            build_canary_profile(lock_paths=_locks())


class CfgT6SchemaTests(unittest.TestCase):
    """CFG-T6: §4.10 exact schema — golden accept; reject smuggling."""

    def test_cfg_t6_accepts_golden(self) -> None:
        parsed = validate_status_file(GOLDEN_STATUS)
        self.assertEqual(parsed["schema_version"], "1")
        self.assertEqual(parsed["status"], "canary_ok")
        self.assertEqual(
            list(parsed),
            [
                "schema_version",
                "task_id",
                "job_id",
                "dispatcher_sha",
                "timestamp_utc",
                "status",
            ],
        )

    def test_cfg_t6_rejects_extra_keys(self) -> None:
        extra = GOLDEN_STATUS.replace(
            "- status: canary_ok\n",
            "- status: canary_ok\n- extra: no\n",
        )
        with self.assertRaises(StatusSchemaError):
            validate_status_file(extra)

    def test_cfg_t6_rejects_missing_keys(self) -> None:
        missing = GOLDEN_STATUS.replace("- timestamp_utc: 2026-09-06T20:00:00Z\n", "")
        with self.assertRaises(StatusSchemaError):
            validate_status_file(missing)

    def test_cfg_t6_rejects_reordered_keys(self) -> None:
        reordered = (
            "# DISPATCHER_STATUS\n"
            "\n"
            "- schema_version: 1\n"
            "- job_id: job-001\n"
            "- task_id: dextech-canary-001\n"
            "- dispatcher_sha: 56a2dcf8d6f7c0a6b879d03eb06691ea1d469122\n"
            "- timestamp_utc: 2026-09-06T20:00:00Z\n"
            "- status: canary_ok\n"
        )
        with self.assertRaises(StatusSchemaError):
            validate_status_file(reordered)

    def test_cfg_t6_rejects_fences(self) -> None:
        fenced = GOLDEN_STATUS.replace(
            "# DISPATCHER_STATUS\n",
            "# DISPATCHER_STATUS\n```\npayload\n```\n",
        )
        with self.assertRaises(StatusSchemaError):
            validate_status_file(fenced)

    def test_cfg_t6_rejects_html(self) -> None:
        html = GOLDEN_STATUS.replace(
            "# DISPATCHER_STATUS\n",
            "# DISPATCHER_STATUS\n<script>alert(1)</script>\n",
        )
        with self.assertRaises(StatusSchemaError):
            validate_status_file(html)

    def test_cfg_t6_rejects_credentials(self) -> None:
        cred = GOLDEN_STATUS.replace(
            "- status: canary_ok\n",
            "- status: canary_ok\n- note: GITHUB_TOKEN=gho_secret\n",
        )
        with self.assertRaises(StatusSchemaError):
            validate_status_file(cred)
        pem = GOLDEN_STATUS + "-----BEGIN PRIVATE KEY-----\n"
        with self.assertRaises(StatusSchemaError):
            validate_status_file(pem)

    def test_cfg_t6_rejects_wrong_status(self) -> None:
        wrong = GOLDEN_STATUS.replace("canary_ok", "failed")
        with self.assertRaises(StatusSchemaError):
            validate_status_file(wrong)

    def test_cfg_t6_rejects_oversized(self) -> None:
        oversized = GOLDEN_STATUS + ("x" * 8192)
        self.assertGreater(len(oversized.encode("utf-8")), 8192)
        with self.assertRaises(StatusSchemaError) as ctx:
            validate_status_file(oversized)
        self.assertIn("8 KiB", str(ctx.exception))

    def test_cfg_t6_rejects_encoded_blob(self) -> None:
        blob = GOLDEN_STATUS.replace(
            "- status: canary_ok\n",
            "- status: canary_ok\n- blob: YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY3ODkwQUJDREU=\n",
        )
        with self.assertRaises(StatusSchemaError):
            validate_status_file(blob)

    def test_cfg_t6_rejects_wrong_schema_version(self) -> None:
        with self.assertRaises(StatusSchemaError):
            validate_status_file(GOLDEN_STATUS.replace("schema_version: 1", "schema_version: 2"))


class CfgT7TokenFieldsFailTests(unittest.TestCase):
    """CFG-T7: GITHUB_TOKEN-like / gh / App key fields fail; identities OK."""

    def test_cfg_t7_no_token_fields_on_profile(self) -> None:
        names = {f.name for f in dataclasses.fields(CanaryProfile)}
        banned = {
            "github_token",
            "GITHUB_TOKEN",
            "gh",
            "gh_token",
            "app_key",
            "app_private_key",
            "token",
        }
        self.assertFalse(names & banned)

    def test_cfg_t7_github_token_kwarg_fails(self) -> None:
        with self.assertRaises(CanaryProfileError):
            build_canary_profile(
                lock_paths=_locks(),
                safety_rules=minimal_canary_safety_rule_config(),
                github_token="secret",
            )
        with self.assertRaises((TypeError, CanaryProfileError)):
            CanaryProfile(  # type: ignore[call-arg]
                lock_paths=_locks(),
                safety_rules=minimal_canary_safety_rule_config(),
                github_token="secret",
            )

    def test_cfg_t7_gh_and_app_key_fields_fail(self) -> None:
        stub = {
            "lock_paths": _locks(),
            "safety_rules": minimal_canary_safety_rule_config(),
        }
        with self.assertRaises(CanaryProfileError):
            build_canary_profile(**stub, gh="auth")
        with self.assertRaises(CanaryProfileError):
            build_canary_profile(**stub, app_key="k")
        with self.assertRaises(CanaryProfileError):
            build_canary_profile(**stub, app_private_key="k")
        with self.assertRaises(CanaryProfileError):
            build_canary_profile(**stub, ORCHESTRATOR_DRY_RUN="1")

    def test_cfg_t7_runner_publisher_identity_ok(self) -> None:
        profile = default_canary_profile(
            lock_paths=_locks(),
            safety_rules=minimal_canary_safety_rule_config(),
            runner_identity="codex-runner",
            publisher_identity="codex-publisher",
        )
        self.assertEqual(profile.runner_identity, "codex-runner")
        self.assertEqual(profile.publisher_identity, "codex-publisher")


class CfgT8NoForbiddenImportsTests(unittest.TestCase):
    """CFG-T8: no measurement/trading/copymoney / ORCHESTRATOR_* imports."""

    def test_cfg_t8_no_measurement_trading_copymoney_imports(self) -> None:
        violations = scan_package(CANARY_PKG)
        self.assertEqual(violations, [])
        for path in _canary_sources():
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name.split(".", 1)[0], FORBIDDEN_ROOTS)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    self.assertNotIn(node.module.split(".", 1)[0], FORBIDDEN_ROOTS)

    def test_cfg_t8_no_orchestrator_env_imports(self) -> None:
        for path in _canary_sources():
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr.startswith("ORCHESTRATOR_"):
                    self.fail(f"{path.name} references {node.attr}")
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if node.value.startswith("ORCHESTRATOR_") and "forbidden" not in (
                        ast.get_docstring(tree) or ""
                    ):
                        # Error-message constants naming the forbidden prefix are OK
                        # only inside isolation rejection strings; still must not import.
                        self.assertIn("ORCHESTRATOR_", node.value)
                        self.assertTrue(
                            "forbidden" in source.lower() or "CopyMoney" in source,
                            f"{path.name} must not consume ORCHESTRATOR_*",
                        )


class CfgT9LockPathConfigTests(unittest.TestCase):
    """CFG-T9: LockPathConfig + agent.lock/implementation.lock; paired-capture."""

    def test_cfg_t9_requires_lock_path_config(self) -> None:
        with self.assertRaises(TypeError):
            CanaryProfile(safety_rules=minimal_canary_safety_rule_config())  # type: ignore[call-arg]
        with self.assertRaises(CanaryProfileError):
            _profile(lock_paths="not-a-config")

    def test_cfg_t9_agent_and_implementation_lock(self) -> None:
        cfg = _locks()
        self.assertEqual(cfg.global_agent_lock.name, AGENT_LOCK_BASENAME)
        self.assertEqual(cfg.implementation_lock.name, IMPLEMENTATION_LOCK_BASENAME)
        profile = _profile(lock_paths=cfg)
        self.assertIs(profile.lock_paths, cfg)

    def test_cfg_t9_paired_capture_rejected(self) -> None:
        with self.assertRaises(LockPathError) as ctx:
            LockPathConfig(
                global_agent_lock=PAIRED_CAPTURE_LOCK_ROOT / AGENT_LOCK_BASENAME,
                implementation_lock=PAIRED_CAPTURE_LOCK_ROOT / IMPLEMENTATION_LOCK_BASENAME,
            )
        self.assertIn("paired-capture", str(ctx.exception))

    def test_cfg_t9_does_not_reimplement_locks(self) -> None:
        import codex_dispatcher.canary as canary_mod

        self.assertFalse(hasattr(canary_mod, "SecureProcessLock"))
        self.assertFalse(hasattr(canary_mod, "flock"))
        for path in _canary_sources():
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in {"flock", "openat"}:
                    self.fail(f"{path.name} must not reimplement locks ({node.attr})")


class CfgT10BranchHelperTests(unittest.TestCase):
    """CFG-T10: branch helper — canary prefix; forbid main/master."""

    def test_cfg_t10_accepts_canary_ref(self) -> None:
        ref = f"{CANARY_REF_PREFIX}dextech-canary-001-20260906-56a2dcf"
        self.assertEqual(require_canary_branch_ref(ref), ref)
        self.assertTrue(CANARY_REF_PREFIX.startswith("refs/heads/agent/canary/"))

    def test_cfg_t10_forbids_main_and_master(self) -> None:
        for ref in (
            "main",
            "master",
            "refs/heads/main",
            "refs/heads/master",
            f"{CANARY_REF_PREFIX}main",
            f"{CANARY_REF_PREFIX}master",
        ):
            with self.subTest(ref=ref):
                with self.assertRaises(CanaryBranchError):
                    require_canary_branch_ref(ref)

    def test_cfg_t10_requires_prefix(self) -> None:
        with self.assertRaises(CanaryBranchError):
            require_canary_branch_ref("refs/heads/agent/other/x")
        with self.assertRaises(CanaryBranchError):
            require_canary_branch_ref("agent/canary/x")


class CanaryLabelContractTests(unittest.TestCase):
    """Label constant + fail-closed missing; metadata not JSON (A5)."""

    def test_label_constant_and_required(self) -> None:
        self.assertEqual(DISPATCHER_CANARY_LABEL, "dispatcher-canary")
        self.assertEqual(_profile().canary_label, DISPATCHER_CANARY_LABEL)
        with self.assertRaises(CanaryProfileError):
            _profile(canary_label="")
        with self.assertRaises(CanaryProfileError):
            _profile(canary_label="ready-for-agent")

    def test_assess_uses_issue_metadata_not_json(self) -> None:
        require_dispatcher_canary_label_from_issue_metadata(
            ["bug", DISPATCHER_CANARY_LABEL]
        )
        with self.assertRaises(CanaryProfileError) as ctx:
            require_dispatcher_canary_label_from_issue_metadata(["ready-for-agent"])
        self.assertIn("metadata", str(ctx.exception).lower())
        self.assertIn("json", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
