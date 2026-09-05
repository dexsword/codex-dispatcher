"""DexServe FAIL regress: actual embedded NUL in repository paths."""

from __future__ import annotations

import unittest

from codex_dispatcher.github import Issue
from codex_dispatcher.ledger import CallableDuplicateChecker
from codex_dispatcher.safety import (
    PATH_ESCAPE,
    MappingTicketSafetySurface,
    PathRule,
    RuleBasedSafetyPolicy,
    SafetyRuleConfig,
    SafetyViolation,
)
from codex_dispatcher.safety.normalize import normalize_path
from codex_dispatcher.worker.assess import assess
from codex_dispatcher.worker.policies import CallableTicketValidator

# Build the NUL at runtime so this source file stays NUL-free for the parser.
_NUL = chr(0)


def _empty_policy() -> RuleBasedSafetyPolicy:
    return RuleBasedSafetyPolicy(
        SafetyRuleConfig(
            denied_paths=(),
            protected_paths=(),
            prohibited_actions=(),
        )
    )


def _fixture_policy() -> RuleBasedSafetyPolicy:
    return RuleBasedSafetyPolicy(
        SafetyRuleConfig(
            denied_paths=(PathRule(rule_id="deny.secrets_dir", pattern=r"^secrets(/|$)"),),
            protected_paths=(),
            prohibited_actions=(),
        )
    )


class EmbeddedNulNormalizeTests(unittest.TestCase):
    def test_normalize_rejects_actual_nul(self) -> None:
        raw = "src/" + _NUL + "bad.py"
        self.assertIn(_NUL, raw)
        self.assertEqual(len(_NUL), 1)
        self.assertEqual(ord(_NUL), 0)
        self.assertEqual(raw[4], _NUL)
        normalized, err = normalize_path(raw)
        self.assertIsNone(normalized)
        self.assertIsNotNone(err)
        self.assertIn("NUL", err or "")

    def test_literal_u0000_text_is_not_nul(self) -> None:
        # Characters backslash + "u0000" are NOT an embedded NUL byte.
        raw = "src/" + chr(92) + "u0000bad.py"
        self.assertNotIn(_NUL, raw)
        normalized, err = normalize_path(raw)
        self.assertIsNotNone(normalized)
        self.assertIsNone(err)


class EmbeddedNulTicketDiffTests(unittest.TestCase):
    def test_ticket_rejects_nul_path(self) -> None:
        policy = _fixture_policy()
        raw = "src/" + _NUL + "bad.py"
        with self.assertRaises(SafetyViolation) as ctx:
            policy.require_safe_ticket(paths=[raw], texts=["add logging"])
        self.assertEqual(ctx.exception.codes, (PATH_ESCAPE,))

    def test_diff_rejects_nul_in_declared(self) -> None:
        policy = _empty_policy()
        raw = "src/" + _NUL + "bad.py"
        with self.assertRaises(SafetyViolation) as ctx:
            policy.validate_candidate_diff(
                declared_paths=[raw],
                changed_paths=[raw],
                patch_text="harmless",
            )
        self.assertIn(PATH_ESCAPE, ctx.exception.codes)

    def test_diff_rejects_nul_in_changed(self) -> None:
        policy = _empty_policy()
        raw = "src/" + _NUL + "bad.py"
        with self.assertRaises(SafetyViolation) as ctx:
            policy.validate_candidate_diff(
                declared_paths=["src/ok.py"],
                changed_paths=[raw],
                patch_text="harmless",
            )
        self.assertEqual(ctx.exception.codes, (PATH_ESCAPE,))


class EmbeddedNulAssessPrecedenceTests(unittest.TestCase):
    """Blocking precedes any injected SafetyPolicy / TicketValidator permission."""

    def test_assess_blocks_nul_under_empty_fixture_policy(self) -> None:
        raw = "src/" + _NUL + "bad.py"
        issue = Issue(1, "t", "{}", "https://example.test/1")
        result = assess(
            issue,
            {"id": "x", "paths": [raw], "texts": ["add logging"]},
            validate_ticket=CallableTicketValidator(lambda _t: None),
            safety_policy=_empty_policy(),
            ticket_safety_surface=MappingTicketSafetySurface(),
            duplicate_check=CallableDuplicateChecker(lambda _t: False),
            repository_allowlist=frozenset({"acme/demo"}),
            repository="acme/demo",
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertNotEqual(result["disposition"], "eligible")
        self.assertIn("NUL", result["reason"])

    def test_assess_blocks_nul_even_if_policy_would_permit(self) -> None:
        class PermitAll:
            def require_safe_ticket(self, *, paths, texts) -> None:
                return None

            def validate_candidate_diff(
                self, *, declared_paths, changed_paths, patch_text
            ) -> None:
                return None

        raw = "src/" + _NUL + "bad.py"
        issue = Issue(2, "t", "{}", "https://example.test/2")
        result = assess(
            issue,
            {"id": "y", "paths": [raw], "texts": []},
            validate_ticket=CallableTicketValidator(lambda _t: None),
            safety_policy=PermitAll(),  # type: ignore[arg-type]
            ticket_safety_surface=MappingTicketSafetySurface(),
            duplicate_check=CallableDuplicateChecker(lambda _t: False),
            repository_allowlist=frozenset({"acme/demo"}),
            repository="acme/demo",
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertIn("NUL", result["reason"])


if __name__ == "__main__":
    unittest.main()
