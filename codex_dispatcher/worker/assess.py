"""Dry-run assess: extract-shaped tickets + injected fail-closed policies."""

from __future__ import annotations

import os
from collections.abc import Mapping, Set
from typing import Any

from codex_dispatcher.allowlist import require_repository_allowed
from codex_dispatcher.github.source import Issue
from codex_dispatcher.ledger import DuplicateChecker
from codex_dispatcher.safety import SafetyPolicy, SafetyViolation, TicketSafetySurface
from codex_dispatcher.safety.normalize import require_paths
from codex_dispatcher.validation import (
    require_boolean, require_mapping, require_none, require_strings,
)
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


def _eligible(issue: Issue, *, demo_pass_policies: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
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
    if demo_pass_policies:
        result["demo_pass_policies"] = True
        result["policy_mode"] = "demo-pass-policies"
    return result


def assess(
    issue: Issue,
    ticket: Mapping[str, Any],
    *,
    validate_ticket: TicketValidator | None = None,
    safety_policy: SafetyPolicy | None = None,
    ticket_safety_surface: TicketSafetySurface | None = None,
    duplicate_check: DuplicateChecker | None = None,
    repository_allowlist: Set[str] | None = None,
    repository: str | None = None,
    demo_pass_policies: bool = False,
) -> dict[str, Any]:
    """Assess an opaque ticket under injected policies.

    Any missing seam fails closed (disposition blocked, never eligible).
    Allowlist must be nonempty and a target repository must be named and listed.
    The dispatcher does not interpret product fields inside *ticket*.
    Disabled dry-run raises RuntimeError before any collaborator is called.
    Expected input/contract/collaborator errors block; other exceptions propagate
    without producing an eligible result.
    """
    require_dry_run()
    if validate_ticket is None:
        return _blocked(issue, "ticket validation policy is not configured")
    if safety_policy is None:
        return _blocked(issue, "safety policy is not configured")
    if ticket_safety_surface is None:
        return _blocked(issue, "ticket safety surface is not configured")
    if duplicate_check is None:
        return _blocked(issue, "duplicate-check capability is not configured")
    if repository_allowlist is None:
        return _blocked(issue, "repository allowlist is not configured")
    try:
        require_repository_allowed(repository, repository_allowlist)
        ticket = require_mapping(ticket, label="ticket")
        require_none(validate_ticket.validate(ticket), label="ticket validator")
        paths = require_paths(ticket_safety_surface.paths(ticket), label="paths")
        texts = require_strings(ticket_safety_surface.texts(ticket), label="texts")
        require_none(
            safety_policy.require_safe_ticket(paths=paths, texts=texts),
            label="safety policy",
        )
        if require_boolean(duplicate_check.is_duplicate(ticket), label="duplicate checker"):
            raise ValueError(
                "ticket identity already known to duplicate-check; silent repetition refused"
            )
    except (
        TicketValidationError, SafetyViolation, ValueError, TypeError, KeyError,
        AttributeError, RuntimeError, OSError,
    ) as exc:
        return _blocked(issue, str(exc))

    return _eligible(issue, demo_pass_policies=demo_pass_policies)
