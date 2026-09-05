"""Dry-run assess: extract-shaped tickets + injected fail-closed policies."""

from __future__ import annotations

import os
from collections.abc import Mapping, Set
from typing import Any

from codex_dispatcher.github.source import Issue
from codex_dispatcher.ledger import DuplicateChecker
from codex_dispatcher.safety import SafetyPolicy, SafetyViolation, TicketSafetySurface
from codex_dispatcher.safety.codes import PATH_ESCAPE
from codex_dispatcher.safety.engine import SafetyViolationDetail
from codex_dispatcher.safety.normalize import structural_path_errors
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
    """
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
    if len(repository_allowlist) == 0:
        return _blocked(issue, "repository allowlist is empty")
    if repository is None or str(repository).strip() == "":
        return _blocked(issue, "target repository is not supplied")
    if repository not in repository_allowlist:
        return _blocked(
            issue,
            f"repository is not in the supplied allowlist: {repository}",
        )

    try:
        # Structural repository-path checks run before TicketValidator / SafetyPolicy
        # so a permissive injected policy cannot make a NUL-bearing path eligible.
        paths = ticket_safety_surface.paths(ticket)
        texts = ticket_safety_surface.texts(ticket)
        path_errors = structural_path_errors(paths)
        if path_errors:
            details = [
                SafetyViolationDetail(
                    code=PATH_ESCAPE,
                    subject=raw,
                    message=msg,
                )
                for raw, msg in path_errors
            ]
            raise SafetyViolation.from_details(details)

        validate_ticket.validate(ticket)
        safety_policy.require_safe_ticket(paths=paths, texts=texts)
        if duplicate_check.is_duplicate(ticket):
            raise ValueError(
                "ticket identity already known to duplicate-check; silent repetition refused"
            )
    except (TicketValidationError, SafetyViolation, ValueError, TypeError, KeyError) as exc:
        return _blocked(issue, str(exc))

    return _eligible(issue, demo_pass_policies=demo_pass_policies)
