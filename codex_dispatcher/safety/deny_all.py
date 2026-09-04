"""Built-in policy that always blocks ticket and diff checks."""

from __future__ import annotations

from collections.abc import Sequence

from codex_dispatcher.safety.codes import POLICY_DENY_ALL
from codex_dispatcher.safety.engine import SafetyViolation


class DenyAllSafetyPolicy:
    """Every ticket assessment and every candidate-diff check blocks.

    Explicit inject only — never auto-substituted when safety_policy is None.
    """

    def require_safe_ticket(
        self,
        *,
        paths: Sequence[str],
        texts: Sequence[str],
    ) -> None:
        raise SafetyViolation.from_codes(
            (POLICY_DENY_ALL,),
            subject="DenyAllSafetyPolicy",
            message="DenyAllSafetyPolicy rejected ticket assessment",
        )

    def validate_candidate_diff(
        self,
        *,
        declared_paths: Sequence[str],
        changed_paths: Sequence[str],
        patch_text: str,
    ) -> None:
        raise SafetyViolation.from_codes(
            (POLICY_DENY_ALL,),
            subject="DenyAllSafetyPolicy",
            message="DenyAllSafetyPolicy rejected candidate diff",
        )


__all__ = ["DenyAllSafetyPolicy"]
