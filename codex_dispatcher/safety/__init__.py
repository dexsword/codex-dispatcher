"""Injectable safety policy seam (fail closed when absent).

Generic rule engine + DenyAll. No product path tables. No silent-allow
CallableSafetyPolicy. CopyMoney/live-trading parity is deferred to a facade.
"""

from __future__ import annotations

from codex_dispatcher.safety.codes import (
    ACTION_PROHIBITED,
    CONFIG_INVALID,
    PATH_DENIED,
    PATH_ESCAPE,
    PATH_PROTECTED,
    PATH_UNEXPECTED,
    POLICY_DENY_ALL,
)
from codex_dispatcher.safety.config import ActionRule, PathRule, SafetyRuleConfig
from codex_dispatcher.safety.deny_all import DenyAllSafetyPolicy
from codex_dispatcher.safety.engine import (
    MappingTicketSafetySurface,
    RuleBasedSafetyPolicy,
    SafetyPolicy,
    SafetyViolation,
    SafetyViolationDetail,
    TicketSafetySurface,
)
from codex_dispatcher.safety.normalize import normalize_path

__all__ = [
    "ACTION_PROHIBITED",
    "CONFIG_INVALID",
    "PATH_DENIED",
    "PATH_ESCAPE",
    "PATH_PROTECTED",
    "PATH_UNEXPECTED",
    "POLICY_DENY_ALL",
    "ActionRule",
    "DenyAllSafetyPolicy",
    "MappingTicketSafetySurface",
    "PathRule",
    "RuleBasedSafetyPolicy",
    "SafetyPolicy",
    "SafetyRuleConfig",
    "SafetyViolation",
    "SafetyViolationDetail",
    "TicketSafetySurface",
    "normalize_path",
]
