"""RuleBasedSafetyPolicy engine + SafetyViolation types."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from codex_dispatcher.safety.codes import (
    ACTION_PROHIBITED,
    CONFIG_INVALID,
    PATH_DENIED,
    PATH_ESCAPE,
    PATH_PROTECTED,
    PATH_UNEXPECTED,
)
from codex_dispatcher.safety.config import ActionRule, PathRule, SafetyRuleConfig
from codex_dispatcher.safety.normalize import normalize_path


@dataclass(frozen=True, slots=True)
class SafetyViolationDetail:
    """One structured safety rejection (stable code + subject)."""

    code: str
    subject: str
    message: str


class SafetyViolation(Exception):
    """Safety policy rejected a ticket or candidate diff.

    Stable API is ``.codes`` and ``.details``. ``str(exc)`` is human-readable
    only — callers and tests must not treat message text as the stable API.
    """

    codes: tuple[str, ...]
    details: tuple[SafetyViolationDetail, ...]

    def __init__(self, details: Sequence[SafetyViolationDetail]) -> None:
        if not details:
            raise ValueError("SafetyViolation requires a non-empty details sequence")
        ordered = tuple(
            sorted(details, key=lambda d: (d.code, d.subject, d.message))
        )
        unique_codes = tuple(sorted({d.code for d in ordered}))
        if not unique_codes:
            raise ValueError("SafetyViolation codes must be non-empty")
        self.details = ordered
        self.codes = unique_codes
        human = "; ".join(d.message for d in ordered)
        super().__init__(human)

    @classmethod
    def from_details(
        cls, details: Sequence[SafetyViolationDetail]
    ) -> SafetyViolation:
        return cls(details)

    @classmethod
    def from_codes(
        cls,
        codes: Sequence[str],
        *,
        subject: str = "",
        message: str = "safety policy rejected the request",
    ) -> SafetyViolation:
        unique = tuple(sorted({str(c) for c in codes}))
        if not unique:
            raise ValueError("from_codes requires at least one code")
        details = tuple(
            SafetyViolationDetail(code=c, subject=subject, message=message)
            for c in unique
        )
        return cls(details)


@runtime_checkable
class SafetyPolicy(Protocol):
    def require_safe_ticket(
        self,
        *,
        paths: Sequence[str],
        texts: Sequence[str],
    ) -> None:
        """Raise SafetyViolation if declared paths or action texts violate policy."""

    def validate_candidate_diff(
        self,
        *,
        declared_paths: Sequence[str],
        changed_paths: Sequence[str],
        patch_text: str,
    ) -> None:
        """Raise SafetyViolation if the actual candidate diff violates policy."""


@runtime_checkable
class TicketSafetySurface(Protocol):
    def paths(self, ticket: Mapping[str, Any]) -> Sequence[str]:
        """Return declared paths extracted from an opaque ticket."""

    def texts(self, ticket: Mapping[str, Any]) -> Sequence[str]:
        """Return action-text surfaces extracted from an opaque ticket."""


class MappingTicketSafetySurface:
    """Synthetic surface: read ``paths`` / ``texts`` keys from a mapping ticket.

    Missing keys yield empty sequences. Neutral field names only — not product
    CopyMoney ticket fields.
    """

    def paths(self, ticket: Mapping[str, Any]) -> Sequence[str]:
        raw = ticket.get("paths", ())
        if raw is None:
            return ()
        return tuple(str(p) for p in raw)

    def texts(self, ticket: Mapping[str, Any]) -> Sequence[str]:
        raw = ticket.get("texts", ())
        if raw is None:
            return ()
        return tuple(str(t) for t in raw)


def _compile_path_rules(
    rules: Sequence[PathRule],
) -> tuple[tuple[str, re.Pattern[str]], ...]:
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for rule in rules:
        if rule.pattern == "":
            raise SafetyViolation.from_codes(
                (CONFIG_INVALID,),
                subject=rule.rule_id,
                message=f"empty path pattern rejected for rule {rule.rule_id!r}",
            )
        try:
            compiled.append((rule.rule_id, re.compile(rule.pattern, rule.flags)))
        except re.error as exc:
            raise SafetyViolation.from_codes(
                (CONFIG_INVALID,),
                subject=rule.rule_id,
                message=f"invalid path regex for rule {rule.rule_id!r}: {exc}",
            ) from exc
    return tuple(compiled)


def _compile_action_rules(
    rules: Sequence[ActionRule],
) -> tuple[tuple[str, re.Pattern[str]], ...]:
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for rule in rules:
        if rule.pattern == "":
            raise SafetyViolation.from_codes(
                (CONFIG_INVALID,),
                subject=rule.rule_id,
                message=f"empty action pattern rejected for rule {rule.rule_id!r}",
            )
        try:
            compiled.append((rule.rule_id, re.compile(rule.pattern, rule.flags)))
        except re.error as exc:
            raise SafetyViolation.from_codes(
                (CONFIG_INVALID,),
                subject=rule.rule_id,
                message=f"invalid action regex for rule {rule.rule_id!r}: {exc}",
            ) from exc
    return tuple(compiled)


class RuleBasedSafetyPolicy:
    """Immutable injected-rule SafetyPolicy (path deny/protect + action prohibit)."""

    __slots__ = ("_config", "_denied", "_protected", "_actions")

    def __init__(self, config: SafetyRuleConfig) -> None:
        self._config = config
        self._denied = _compile_path_rules(config.denied_paths)
        self._protected = _compile_path_rules(config.protected_paths)
        self._actions = _compile_action_rules(config.prohibited_actions)

    @property
    def config(self) -> SafetyRuleConfig:
        return self._config

    def require_safe_ticket(
        self,
        *,
        paths: Sequence[str],
        texts: Sequence[str],
    ) -> None:
        details: list[SafetyViolationDetail] = []
        details.extend(self._check_paths_denied(paths))
        details.extend(self._check_actions(texts))
        if details:
            raise SafetyViolation.from_details(details)

    def validate_candidate_diff(
        self,
        *,
        declared_paths: Sequence[str],
        changed_paths: Sequence[str],
        patch_text: str,
    ) -> None:
        details: list[SafetyViolationDetail] = []
        norm_declared: set[str] = set()
        norm_changed: set[str] = set()

        for raw in declared_paths:
            normalized, err = normalize_path(raw)
            if normalized is None:
                details.append(
                    SafetyViolationDetail(
                        code=PATH_ESCAPE,
                        subject=str(raw),
                        message=err or "path escape",
                    )
                )
            else:
                norm_declared.add(normalized)

        for raw in changed_paths:
            normalized, err = normalize_path(raw)
            if normalized is None:
                details.append(
                    SafetyViolationDetail(
                        code=PATH_ESCAPE,
                        subject=str(raw),
                        message=err or "path escape",
                    )
                )
            else:
                norm_changed.add(normalized)

        for path in sorted(norm_changed - norm_declared):
            details.append(
                SafetyViolationDetail(
                    code=PATH_UNEXPECTED,
                    subject=path,
                    message=f"changed path not in declared set: {path}",
                )
            )

        for path in sorted(norm_changed):
            if self._matches_any(path, self._denied):
                details.append(
                    SafetyViolationDetail(
                        code=PATH_DENIED,
                        subject=path,
                        message=f"changed path denied: {path}",
                    )
                )
            if self._matches_any(path, self._protected):
                details.append(
                    SafetyViolationDetail(
                        code=PATH_PROTECTED,
                        subject=path,
                        message=f"changed path protected: {path}",
                    )
                )

        details.extend(self._check_actions((patch_text,)))
        if details:
            raise SafetyViolation.from_details(details)

    def _check_paths_denied(
        self, paths: Sequence[str]
    ) -> list[SafetyViolationDetail]:
        out: list[SafetyViolationDetail] = []
        seen_denied: set[str] = set()
        seen_escape: set[str] = set()
        for raw in paths:
            normalized, err = normalize_path(raw)
            if normalized is None:
                key = str(raw)
                if key not in seen_escape:
                    seen_escape.add(key)
                    out.append(
                        SafetyViolationDetail(
                            code=PATH_ESCAPE,
                            subject=key,
                            message=err or "path escape",
                        )
                    )
                continue
            if normalized in seen_denied:
                continue
            if self._matches_any(normalized, self._denied):
                seen_denied.add(normalized)
                out.append(
                    SafetyViolationDetail(
                        code=PATH_DENIED,
                        subject=normalized,
                        message=f"path denied: {normalized}",
                    )
                )
        return out

    def _check_actions(self, texts: Sequence[str]) -> list[SafetyViolationDetail]:
        out: list[SafetyViolationDetail] = []
        matched_ids: set[str] = set()
        for rule_id, pattern in self._actions:
            if rule_id in matched_ids:
                continue
            for text in texts:
                if pattern.search(text):
                    matched_ids.add(rule_id)
                    out.append(
                        SafetyViolationDetail(
                            code=ACTION_PROHIBITED,
                            subject=rule_id,
                            message=f"prohibited action matched rule {rule_id!r}",
                        )
                    )
                    break
        return out

    @staticmethod
    def _matches_any(
        path: str, rules: Sequence[tuple[str, re.Pattern[str]]]
    ) -> bool:
        return any(pattern.search(path) for _rule_id, pattern in rules)


__all__ = [
    "MappingTicketSafetySurface",
    "RuleBasedSafetyPolicy",
    "SafetyPolicy",
    "SafetyViolation",
    "SafetyViolationDetail",
    "TicketSafetySurface",
]
