"""Dry-run assess: extract-shaped tickets + injected fail-closed policies."""

from __future__ import annotations

import os
from collections.abc import Set, Mapping
from typing import Any

from codex_dispatcher.github.source import Issue
from codex_dispatcher.ledger import DuplicateChecker
from codex_dispatcher.safety import SafetyPolicy, SafetyViolation
from codex_dispatcher.worker.policies import TicketValidationError, TicketValidator

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def require_dry_run(*, env: Mapping[str, str] | None = None) -> None:
    """Refuse unless CODEX_DISPATCHER_DRY_RUN is enabled (default true)."""
    environ = env if env is not None else os.environ
    raw = environ.get("CODEX_DISPATCHER_DRY_RUN", "true")
    if str(raw).lower() not in _TRUTHY:
        raise RuntimeError(
            "non-dry-run operation is not implemented or enabled "
            "(set CODEX_DISPATCHER_DRY_RUN=true)"
        )


def _blocked(issue: Issue | None, reason: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "mode": "dry-run",
        "disposition": "blocked",
        "reason": reason,
        "github_mutated": False,
        "repository_mutated": False,
        "agent_invoked": False,
        "ledger_mutated": False,
    }
    if issue is not None:
        result["issue"] = issue.number
    return result


def _eligible(issue: Issue) -> dict[str, Any]:
    return {
        "mode": "dry-run",
        "issue": issue.number,
        "disposition": "eligible",
        "would": [
            "record a proposed ledger event (not performed in dry-run)",
            "create a work branch from the configured default branch (not performed)",
            "invoke the separately verified coding-agent adapter once (not performed)",
            "run deterministic tests and safety checks (not performed)",
            "mark the candidate ready only after tests pass (not performed)",
        ],
        "github_mutated": False,
        "repository_mutated": False,
        "agent_invoked": False,
        "ledger_mutated": False,
    }


def assess(
    issue: Issue,
    ticket: Mapping[str, Any],
    *,
    validate_ticket: TicketValidator | None = None,
    safety_policy: SafetyPolicy | None = None,
    duplicate_check: DuplicateChecker | None = None,
    repository_allowlist: Set[str] | None = None,
    repository: str | None = None,
) -> dict[str, Any]:
    """Assess an opaque ticket under injected policies.

    Any missing seam fails closed (disposition blocked, never eligible).
    The dispatcher does not interpret product fields inside *ticket*.
    """
    if validate_ticket is None:
        return _blocked(issue, "ticket validation policy is not configured")
    if safety_policy is None:
        return _blocked(issue, "safety policy is not configured")
    if duplicate_check is None:
        return _blocked(issue, "duplicate-check capability is not configured")
    if repository_allowlist is None:
        return _blocked(issue, "repository allowlist is not configured")
    if repository is not None and repository not in repository_allowlist:
        return _blocked(
            issue,
            f"repository is not in the supplied allowlist: {repository}",
        )

    try:
        validate_ticket.validate(ticket)
        safety_policy.require_safe(ticket)
        if duplicate_check.is_duplicate(ticket):
            raise SafetyViolation(
                "ticket identity already known to duplicate-check; silent repetition refused"
            )
    except (TicketValidationError, SafetyViolation, ValueError, TypeError, KeyError) as exc:
        return _blocked(issue, str(exc))

    return _eligible(issue)
