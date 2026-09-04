"""Fail-closed assess dispositions."""

from __future__ import annotations

import os
import unittest
from collections.abc import Mapping
from typing import Any
from unittest import mock

from codex_dispatcher.github import Issue
from codex_dispatcher.ledger import CallableDuplicateChecker
from codex_dispatcher.safety import (
    DenyAllSafetyPolicy,
    MappingTicketSafetySurface,
    RuleBasedSafetyPolicy,
    SafetyRuleConfig,
    SafetyViolation,
)
from codex_dispatcher.worker import assess, require_dry_run
from codex_dispatcher.worker.policies import CallableTicketValidator, TicketValidationError


def _issue() -> Issue:
    return Issue(7, "t", "{}", "https://example.test/issues/7")


def _empty_policy() -> RuleBasedSafetyPolicy:
    return RuleBasedSafetyPolicy(
        SafetyRuleConfig(
            denied_paths=(),
            protected_paths=(),
            prohibited_actions=(),
        )
    )


def _pass_policies() -> dict:
    return {
        "validate_ticket": CallableTicketValidator(lambda _t: None),
        "safety_policy": _empty_policy(),
        "ticket_safety_surface": MappingTicketSafetySurface(),
        "duplicate_check": CallableDuplicateChecker(lambda _t: False),
    }


class AssessFailClosedTests(unittest.TestCase):
    def test_missing_all_policies_blocked(self) -> None:
        result = assess(_issue(), {"id": "x"})
        self.assertEqual(result["disposition"], "blocked")
        self.assertIn("ticket validation", result["reason"])
        self.assertFalse(result["github_mutated"])
        self.assertFalse(result["ledger_mutated"])

    def test_missing_safety_blocked(self) -> None:
        result = assess(
            _issue(),
            {"id": "x"},
            validate_ticket=CallableTicketValidator(lambda _t: None),
            duplicate_check=CallableDuplicateChecker(lambda _t: False),
            repository_allowlist=frozenset({"acme/demo"}),
            repository="acme/demo",
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertIn("safety policy", result["reason"])

    def test_missing_surface_blocked(self) -> None:
        result = assess(
            _issue(),
            {"id": "x"},
            validate_ticket=CallableTicketValidator(lambda _t: None),
            safety_policy=_empty_policy(),
            duplicate_check=CallableDuplicateChecker(lambda _t: False),
            repository_allowlist=frozenset({"acme/demo"}),
            repository="acme/demo",
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertIn("ticket safety surface", result["reason"])

    def test_missing_duplicate_check_blocked(self) -> None:
        result = assess(
            _issue(),
            {"id": "x"},
            validate_ticket=CallableTicketValidator(lambda _t: None),
            safety_policy=_empty_policy(),
            ticket_safety_surface=MappingTicketSafetySurface(),
            repository_allowlist=frozenset({"acme/demo"}),
            repository="acme/demo",
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertIn("duplicate-check", result["reason"])

    def test_missing_allowlist_blocked(self) -> None:
        result = assess(
            _issue(),
            {"id": "x"},
            **_pass_policies(),
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertIn("allowlist", result["reason"])

    def test_empty_allowlist_blocked(self) -> None:
        result = assess(
            _issue(),
            {"id": "x"},
            **_pass_policies(),
            repository_allowlist=frozenset(),
            repository="acme/demo",
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertIn("empty", result["reason"])

    def test_allowlist_without_repository_blocked(self) -> None:
        result = assess(
            _issue(),
            {"id": "x"},
            **_pass_policies(),
            repository_allowlist=frozenset({"acme/demo"}),
            repository=None,
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertIn("repository", result["reason"].lower())

    def test_repository_without_allowlist_blocked(self) -> None:
        result = assess(
            _issue(),
            {"id": "x"},
            **_pass_policies(),
            repository_allowlist=None,
            repository="acme/demo",
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertIn("allowlist", result["reason"])

    def test_allowlist_and_repository_without_policies_blocked(self) -> None:
        result = assess(
            _issue(),
            {"id": "x"},
            repository_allowlist=frozenset({"acme/demo"}),
            repository="acme/demo",
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertIn("ticket validation", result["reason"])

    def test_explicit_policies_and_repo_in_allowlist_eligible(self) -> None:
        result = assess(
            _issue(),
            {"id": "ok", "summary": "fine"},
            **_pass_policies(),
            repository_allowlist=frozenset({"acme/demo"}),
            repository="acme/demo",
        )
        self.assertEqual(result["disposition"], "eligible")
        self.assertFalse(result["agent_invoked"])
        self.assertNotIn("experiment_id", result)

    def test_explicit_validator_blocked(self) -> None:
        def _bad(ticket: Mapping[str, Any]) -> None:
            raise TicketValidationError("nope")

        result = assess(
            _issue(),
            {"id": "x"},
            validate_ticket=CallableTicketValidator(_bad),
            safety_policy=_empty_policy(),
            ticket_safety_surface=MappingTicketSafetySurface(),
            duplicate_check=CallableDuplicateChecker(lambda _t: False),
            repository_allowlist=frozenset({"acme/demo"}),
            repository="acme/demo",
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertEqual(result["reason"], "nope")

    def test_explicit_safety_blocked(self) -> None:
        result = assess(
            _issue(),
            {"id": "x"},
            validate_ticket=CallableTicketValidator(lambda _t: None),
            safety_policy=DenyAllSafetyPolicy(),
            ticket_safety_surface=MappingTicketSafetySurface(),
            duplicate_check=CallableDuplicateChecker(lambda _t: False),
            repository_allowlist=frozenset({"acme/demo"}),
            repository="acme/demo",
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertIsInstance(result["reason"], str)
        # DenyAll raises SafetyViolation; assess keeps blocked disposition.
        with self.assertRaises(SafetyViolation) as ctx:
            DenyAllSafetyPolicy().require_safe_ticket(paths=[], texts=[])
        self.assertEqual(ctx.exception.codes, ("POLICY_DENY_ALL",))

    def test_duplicate_blocked(self) -> None:
        result = assess(
            _issue(),
            {"id": "dup"},
            validate_ticket=CallableTicketValidator(lambda _t: None),
            safety_policy=_empty_policy(),
            ticket_safety_surface=MappingTicketSafetySurface(),
            duplicate_check=CallableDuplicateChecker(lambda t: t.get("id") == "dup"),
            repository_allowlist=frozenset({"acme/demo"}),
            repository="acme/demo",
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertIn("duplicate", result["reason"].lower())

    def test_repo_not_in_allowlist_blocked(self) -> None:
        result = assess(
            _issue(),
            {"id": "x"},
            **_pass_policies(),
            repository_allowlist=frozenset({"acme/demo"}),
            repository="other/repo",
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertIn("allowlist", result["reason"])

    def test_no_callable_safety_policy_export(self) -> None:
        import codex_dispatcher.safety as safety_mod

        self.assertFalse(hasattr(safety_mod, "CallableSafetyPolicy"))


class DryRunEnvTests(unittest.TestCase):
    def test_default_allows_dry_run(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            require_dry_run(env={})

    def test_false_refuses(self) -> None:
        with self.assertRaises(RuntimeError):
            require_dry_run(env={"CODEX_DISPATCHER_DRY_RUN": "false"})

    def test_does_not_read_orchestrator_env(self) -> None:
        require_dry_run(
            env={
                "ORCHESTRATOR_DRY_RUN": "false",
                "CODEX_DISPATCHER_DRY_RUN": "true",
            }
        )


if __name__ == "__main__":
    unittest.main()
