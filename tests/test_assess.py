"""Fail-closed assess dispositions."""

from __future__ import annotations

import os
import unittest
from collections.abc import Mapping
from typing import Any
from unittest import mock

from codex_dispatcher.github import Issue
from codex_dispatcher.ledger import CallableDuplicateChecker
from codex_dispatcher.safety import CallableSafetyPolicy, SafetyViolation
from codex_dispatcher.worker import assess, require_dry_run
from codex_dispatcher.worker.policies import CallableTicketValidator, TicketValidationError


def _issue() -> Issue:
    return Issue(7, "t", "{}", "https://example.test/issues/7")


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

    def test_missing_duplicate_check_blocked(self) -> None:
        result = assess(
            _issue(),
            {"id": "x"},
            validate_ticket=CallableTicketValidator(lambda _t: None),
            safety_policy=CallableSafetyPolicy(lambda _t: None),
            repository_allowlist=frozenset({"acme/demo"}),
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertIn("duplicate-check", result["reason"])

    def test_missing_allowlist_blocked(self) -> None:
        result = assess(
            _issue(),
            {"id": "x"},
            validate_ticket=CallableTicketValidator(lambda _t: None),
            safety_policy=CallableSafetyPolicy(lambda _t: None),
            duplicate_check=CallableDuplicateChecker(lambda _t: False),
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertIn("allowlist", result["reason"])

    def test_explicit_eligible(self) -> None:
        result = assess(
            _issue(),
            {"id": "ok", "summary": "fine"},
            validate_ticket=CallableTicketValidator(lambda _t: None),
            safety_policy=CallableSafetyPolicy(lambda _t: None),
            duplicate_check=CallableDuplicateChecker(lambda _t: False),
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
            safety_policy=CallableSafetyPolicy(lambda _t: None),
            duplicate_check=CallableDuplicateChecker(lambda _t: False),
            repository_allowlist=frozenset({"acme/demo"}),
            repository="acme/demo",
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertEqual(result["reason"], "nope")

    def test_explicit_safety_blocked(self) -> None:
        def _unsafe(ticket: Mapping[str, Any]) -> None:
            raise SafetyViolation("unsafe")

        result = assess(
            _issue(),
            {"id": "x"},
            validate_ticket=CallableTicketValidator(lambda _t: None),
            safety_policy=CallableSafetyPolicy(_unsafe),
            duplicate_check=CallableDuplicateChecker(lambda _t: False),
            repository_allowlist=frozenset({"acme/demo"}),
            repository="acme/demo",
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertEqual(result["reason"], "unsafe")

    def test_duplicate_blocked(self) -> None:
        result = assess(
            _issue(),
            {"id": "dup"},
            validate_ticket=CallableTicketValidator(lambda _t: None),
            safety_policy=CallableSafetyPolicy(lambda _t: None),
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
            validate_ticket=CallableTicketValidator(lambda _t: None),
            safety_policy=CallableSafetyPolicy(lambda _t: None),
            duplicate_check=CallableDuplicateChecker(lambda _t: False),
            repository_allowlist=frozenset({"acme/demo"}),
            repository="other/repo",
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertIn("allowlist", result["reason"])


class DryRunEnvTests(unittest.TestCase):
    def test_default_allows_dry_run(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            require_dry_run(env={})

    def test_false_refuses(self) -> None:
        with self.assertRaises(RuntimeError):
            require_dry_run(env={"CODEX_DISPATCHER_DRY_RUN": "false"})

    def test_does_not_read_orchestrator_env(self) -> None:
        # ORCHESTRATOR_DRY_RUN=false must not affect us when CODEX flag is true/default.
        require_dry_run(
            env={
                "ORCHESTRATOR_DRY_RUN": "false",
                "CODEX_DISPATCHER_DRY_RUN": "true",
            }
        )


if __name__ == "__main__":
    unittest.main()
