"""Immutable injected rule configuration for RuleBasedSafetyPolicy."""

from __future__ import annotations

from dataclasses import dataclass

from codex_dispatcher.validation import ValidationError, require_string


@dataclass(frozen=True, slots=True)
class PathRule:
    """A denied or protected path pattern."""

    rule_id: str
    pattern: str
    flags: int = 0


@dataclass(frozen=True, slots=True)
class ActionRule:
    """A prohibited-action text/patch pattern."""

    rule_id: str
    pattern: str
    flags: int = 0


@dataclass(frozen=True, slots=True)
class SafetyRuleConfig:
    """Injected rule families. No bypass / allow_all / skip_* fields."""

    denied_paths: tuple[PathRule, ...]
    protected_paths: tuple[PathRule, ...]
    prohibited_actions: tuple[ActionRule, ...]


def validate_rule_config(config: SafetyRuleConfig) -> None:
    """Require immutable, typed rule families and unambiguous family-local IDs."""
    if not isinstance(config, SafetyRuleConfig):
        raise ValidationError("config must be a SafetyRuleConfig")
    for label, rule_type in (
        ("denied_paths", PathRule),
        ("protected_paths", PathRule),
        ("prohibited_actions", ActionRule),
    ):
        rules = getattr(config, label)
        if not isinstance(rules, tuple):
            raise ValidationError(f"{label} must be a tuple of {rule_type.__name__}")
        seen: set[str] = set()
        for rule in rules:
            if not isinstance(rule, rule_type):
                raise ValidationError(f"{label} contains an invalid rule type")
            rule_id = require_string(rule.rule_id, label="rule_id")
            if not rule_id.strip() or rule_id in seen:
                raise ValidationError(f"{label} requires nonblank, unique rule IDs")
            seen.add(rule_id)
            require_string(rule.pattern, label="pattern")
            if not isinstance(rule.flags, int) or isinstance(rule.flags, bool):
                raise ValidationError("regex flags must be an integer")


__all__ = ["ActionRule", "PathRule", "SafetyRuleConfig"]
