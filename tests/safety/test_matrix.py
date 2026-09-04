"""Decision matrix §8.2 — synthetic injected policy exact decisions + codes."""

from __future__ import annotations

import re
import unittest

from codex_dispatcher.github import Issue
from codex_dispatcher.ledger import CallableDuplicateChecker
from codex_dispatcher.safety import (
    ACTION_PROHIBITED,
    CONFIG_INVALID,
    PATH_DENIED,
    PATH_ESCAPE,
    PATH_PROTECTED,
    PATH_UNEXPECTED,
    POLICY_DENY_ALL,
    ActionRule,
    DenyAllSafetyPolicy,
    MappingTicketSafetySurface,
    PathRule,
    RuleBasedSafetyPolicy,
    SafetyRuleConfig,
    SafetyViolation,
)
from codex_dispatcher.worker.assess import assess
from codex_dispatcher.worker.policies import CallableTicketValidator


def fixture_config() -> SafetyRuleConfig:
    return SafetyRuleConfig(
        denied_paths=(
            PathRule(rule_id="deny.secrets_dir", pattern=r"^secrets(/|$)"),
            PathRule(
                rule_id="deny.private_key_file",
                pattern=r"(^|/)private[_-]?key(\.|$|/)",
            ),
        ),
        protected_paths=(
            PathRule(rule_id="protect.foundation", pattern=r"^foundation(/|$)"),
        ),
        prohibited_actions=(
            ActionRule(
                rule_id="prohibit.force_push",
                pattern=r"(?i)(?:git\s+push\s+[^\n]*--force|--force-with-lease|force[_ -]?push)",
            ),
            ActionRule(
                rule_id="prohibit.auto_merge",
                pattern=r"(?i)(?:gh\s+pr\s+merge|auto[_ -]?merge)",
            ),
        ),
    )


def fixture_policy() -> RuleBasedSafetyPolicy:
    return RuleBasedSafetyPolicy(fixture_config())


def _codes_subjects(exc: SafetyViolation) -> list[tuple[str, str]]:
    return [(d.code, d.subject) for d in exc.details]


class TicketMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = fixture_policy()

    def test_t0_ticket_clean(self) -> None:
        self.policy.require_safe_ticket(paths=["src/ok.py"], texts=["add logging"])

    def test_t1_denied_path(self) -> None:
        with self.assertRaises(SafetyViolation) as ctx:
            self.policy.require_safe_ticket(paths=["secrets/x"], texts=[])
        self.assertEqual(ctx.exception.codes, (PATH_DENIED,))
        self.assertIn((PATH_DENIED, "secrets/x"), _codes_subjects(ctx.exception))

    def test_t2_escape(self) -> None:
        with self.assertRaises(SafetyViolation) as ctx:
            self.policy.require_safe_ticket(paths=["../outside"], texts=[])
        self.assertEqual(ctx.exception.codes, (PATH_ESCAPE,))
        self.assertIn((PATH_ESCAPE, "../outside"), _codes_subjects(ctx.exception))

    def test_t3_prohibited_in_text(self) -> None:
        with self.assertRaises(SafetyViolation) as ctx:
            self.policy.require_safe_ticket(
                paths=["src/ok.py"],
                texts=["please git push origin main --force"],
            )
        self.assertEqual(ctx.exception.codes, (ACTION_PROHIBITED,))
        self.assertIn(
            (ACTION_PROHIBITED, "prohibit.force_push"),
            _codes_subjects(ctx.exception),
        )

    def test_t4_multi(self) -> None:
        with self.assertRaises(SafetyViolation) as ctx:
            self.policy.require_safe_ticket(
                paths=["secrets/x"],
                texts=["git push --force"],
            )
        self.assertEqual(
            ctx.exception.codes,
            (ACTION_PROHIBITED, PATH_DENIED),
        )


class DiffMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = fixture_policy()

    def test_d0_diff_clean(self) -> None:
        self.policy.validate_candidate_diff(
            declared_paths=["src/ok.py"],
            changed_paths=["src/ok.py"],
            patch_text="diff --git a/src/ok.py b/src/ok.py\n+print('hi')\n",
        )

    def test_d1_unexpected(self) -> None:
        with self.assertRaises(SafetyViolation) as ctx:
            self.policy.validate_candidate_diff(
                declared_paths=["src/ok.py"],
                changed_paths=["src/ok.py", "src/extra.py"],
                patch_text="",
            )
        self.assertEqual(ctx.exception.codes, (PATH_UNEXPECTED,))
        self.assertIn((PATH_UNEXPECTED, "src/extra.py"), _codes_subjects(ctx.exception))

    def test_d2_protected(self) -> None:
        with self.assertRaises(SafetyViolation) as ctx:
            self.policy.validate_candidate_diff(
                declared_paths=["foundation/core.py"],
                changed_paths=["foundation/core.py"],
                patch_text="",
            )
        self.assertEqual(ctx.exception.codes, (PATH_PROTECTED,))
        self.assertIn(
            (PATH_PROTECTED, "foundation/core.py"),
            _codes_subjects(ctx.exception),
        )

    def test_d3_deny_on_diff(self) -> None:
        with self.assertRaises(SafetyViolation) as ctx:
            self.policy.validate_candidate_diff(
                declared_paths=["secrets/x"],
                changed_paths=["secrets/x"],
                patch_text="",
            )
        self.assertEqual(ctx.exception.codes, (PATH_DENIED,))
        self.assertIn((PATH_DENIED, "secrets/x"), _codes_subjects(ctx.exception))

    def test_d4_prohibit_in_patch(self) -> None:
        with self.assertRaises(SafetyViolation) as ctx:
            self.policy.validate_candidate_diff(
                declared_paths=["src/ok.py"],
                changed_paths=["src/ok.py"],
                patch_text="+ run: gh pr merge --auto\n",
            )
        self.assertEqual(ctx.exception.codes, (ACTION_PROHIBITED,))
        self.assertIn(
            (ACTION_PROHIBITED, "prohibit.auto_merge"),
            _codes_subjects(ctx.exception),
        )

    def test_d5_every_action_rule(self) -> None:
        """Phrase (2): every injected prohibited-action rule propagates; no skip."""
        patch = (
            "git push origin HEAD --force\n"
            "gh pr merge --auto\n"
            "force_push and auto-merge both present\n"
        )
        with self.assertRaises(SafetyViolation) as ctx:
            self.policy.validate_candidate_diff(
                declared_paths=["src/ok.py"],
                changed_paths=["src/ok.py"],
                patch_text=patch,
            )
        self.assertEqual(ctx.exception.codes, (ACTION_PROHIBITED,))
        subjects = {d.subject for d in ctx.exception.details if d.code == ACTION_PROHIBITED}
        self.assertEqual(
            subjects,
            {"prohibit.force_push", "prohibit.auto_merge"},
        )
        # Confirm fixture actually has exactly those two action rules.
        self.assertEqual(
            {r.rule_id for r in fixture_config().prohibited_actions},
            subjects,
        )

    def test_d6_normalize_before_unexpected(self) -> None:
        self.policy.validate_candidate_diff(
            declared_paths=["./src/ok.py"],
            changed_paths=["src/ok.py"],
            patch_text="harmless",
        )


class DenyAllMatrixTests(unittest.TestCase):
    def test_a0_deny_all_ticket(self) -> None:
        policy = DenyAllSafetyPolicy()
        with self.assertRaises(SafetyViolation) as ctx:
            policy.require_safe_ticket(paths=[], texts=[])
        self.assertEqual(ctx.exception.codes, (POLICY_DENY_ALL,))

    def test_a1_deny_all_diff(self) -> None:
        policy = DenyAllSafetyPolicy()
        with self.assertRaises(SafetyViolation) as ctx:
            policy.validate_candidate_diff(
                declared_paths=[],
                changed_paths=[],
                patch_text="",
            )
        self.assertEqual(ctx.exception.codes, (POLICY_DENY_ALL,))


class ConfigAndAssessMatrixTests(unittest.TestCase):
    def test_c0_assess_none_policy(self) -> None:
        issue = Issue(1, "t", "{}", "https://example.test/1")
        result = assess(
            issue,
            {"id": "x"},
            validate_ticket=CallableTicketValidator(lambda _t: None),
            safety_policy=None,
            ticket_safety_surface=MappingTicketSafetySurface(),
            duplicate_check=CallableDuplicateChecker(lambda _t: False),
            repository_allowlist=frozenset({"acme/demo"}),
            repository="acme/demo",
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertIn("safety policy is not configured", result["reason"])

    def test_c1_empty_config_structural(self) -> None:
        policy = RuleBasedSafetyPolicy(
            SafetyRuleConfig(
                denied_paths=(),
                protected_paths=(),
                prohibited_actions=(),
            )
        )
        policy.require_safe_ticket(paths=["src/ok.py"], texts=["add logging"])

    def test_c2_empty_pattern_construct(self) -> None:
        with self.assertRaises(SafetyViolation) as ctx:
            RuleBasedSafetyPolicy(
                SafetyRuleConfig(
                    denied_paths=(PathRule(rule_id="bad.empty", pattern=""),),
                    protected_paths=(),
                    prohibited_actions=(),
                )
            )
        self.assertEqual(ctx.exception.codes, (CONFIG_INVALID,))

    def test_invalid_regex_construct(self) -> None:
        with self.assertRaises(SafetyViolation) as ctx:
            RuleBasedSafetyPolicy(
                SafetyRuleConfig(
                    denied_paths=(PathRule(rule_id="bad.regex", pattern="[unterminated"),),
                    protected_paths=(),
                    prohibited_actions=(),
                )
            )
        self.assertEqual(ctx.exception.codes, (CONFIG_INVALID,))

    def test_config_immutable(self) -> None:
        cfg = fixture_config()
        with self.assertRaises(Exception):
            cfg.denied_paths = ()  # type: ignore[misc]

    def test_no_product_patterns_in_fixture(self) -> None:
        blob = repr(fixture_config()).lower()
        for banned in ("copymoney", "live_trading", "polymarket", "wallet"):
            self.assertNotIn(banned, blob)


if __name__ == "__main__":
    unittest.main()
