"""Immutable injected rule configuration for RuleBasedSafetyPolicy."""

from __future__ import annotations

from dataclasses import dataclass


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


__all__ = ["ActionRule", "PathRule", "SafetyRuleConfig"]
