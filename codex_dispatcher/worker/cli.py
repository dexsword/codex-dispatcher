"""CLI entry: offline ticket-file dry-run assess (no locks, no ledger writes)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from codex_dispatcher.github import Issue, extract_ticket
from codex_dispatcher.ledger import CallableDuplicateChecker
from codex_dispatcher.safety import CallableSafetyPolicy, SafetyViolation
from codex_dispatcher.worker.assess import assess, require_dry_run
from codex_dispatcher.worker.policies import CallableTicketValidator, TicketValidationError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run Codex Dispatcher assess. "
            "Offline --ticket-file examples require --allowlist, --repository, "
            "and either real injected policy flags or --demo-pass-policies."
        )
    )
    parser.add_argument(
        "--ticket-file",
        type=Path,
        required=True,
        help="local issue-body / ticket file for an offline dry run",
    )
    parser.add_argument(
        "--repository",
        default=None,
        help="owner/name target repository (required for eligibility)",
    )
    parser.add_argument(
        "--allowlist",
        action="append",
        default=[],
        help="allowed owner/name (repeatable). Must be nonempty for eligibility.",
    )
    parser.add_argument(
        "--demo-pass-policies",
        action="store_true",
        help=(
            "UNMISTAKABLE offline demo only: inject pass-through validator/safety/"
            "duplicate-check policies. Allowlist alone never synthesizes policies."
        ),
    )
    parser.add_argument(
        "--require-key",
        action="append",
        default=[],
        dest="require_keys",
        help="injected ticket validator: require these opaque keys (repeatable)",
    )
    parser.add_argument(
        "--deny-key",
        action="append",
        default=[],
        dest="deny_keys",
        help="injected safety policy: block if opaque key is present (repeatable)",
    )
    parser.add_argument(
        "--known-id",
        action="append",
        default=[],
        dest="known_ids",
        help="injected duplicate-check: known opaque ticket id values (repeatable)",
    )
    parser.add_argument(
        "--id-field",
        default="id",
        help="opaque ticket field used by --known-id duplicate-check (default: id)",
    )
    return parser


def run(argv: list[str] | None = None) -> dict[str, Any]:
    args = _parser().parse_args(argv)
    require_dry_run()

    body = args.ticket_file.read_text(encoding="utf-8")
    issue = Issue(0, args.ticket_file.name, body, "local-file")
    try:
        ticket = extract_ticket(body)
    except (json.JSONDecodeError, ValueError) as exc:
        return {
            "mode": "dry-run",
            "issue": issue.number,
            "disposition": "blocked",
            "reason": f"ticket extract failed: {exc}",
            "github_mutated": False,
            "repository_mutated": False,
            "agent_invoked": False,
            "ledger_mutated": False,
            "issues_processed": 1,
        }

    allowlist = frozenset(args.allowlist) if args.allowlist else None
    require_keys = list(args.require_keys)
    deny_keys = list(args.deny_keys)
    known = {str(x) for x in args.known_ids}
    id_field = args.id_field
    demo = bool(args.demo_pass_policies)

    # Fail closed: do NOT synthesize policies from --allowlist alone.
    validate_ticket = None
    safety_policy = None
    duplicate_check = None

    if demo or require_keys:

        def _validate(t: Mapping[str, Any]) -> None:
            missing = [k for k in require_keys if k not in t]
            if missing:
                raise TicketValidationError(f"missing required ticket keys: {missing}")

        validate_ticket = CallableTicketValidator(_validate)

    if demo or deny_keys:

        def _safe(t: Mapping[str, Any]) -> None:
            hit = [k for k in deny_keys if k in t]
            if hit:
                raise SafetyViolation(f"ticket contains denied keys: {hit}")

        safety_policy = CallableSafetyPolicy(_safe)

    # Duplicate-check only when demo pass-through OR --known-id was used.
    if demo or bool(args.known_ids):

        def _dup(t: Mapping[str, Any]) -> bool:
            value = t.get(id_field)
            return value is not None and str(value) in known

        duplicate_check = CallableDuplicateChecker(_dup)

    result = assess(
        issue,
        ticket,
        validate_ticket=validate_ticket,
        safety_policy=safety_policy,
        duplicate_check=duplicate_check,
        repository_allowlist=allowlist,
        repository=args.repository,
        demo_pass_policies=demo,
    )
    if demo:
        result["demo_pass_policies"] = True
        result["policy_mode"] = "demo-pass-policies"
    result["issues_processed"] = 1
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(argv)
    except RuntimeError as exc:
        result = {
            "mode": "dry-run",
            "disposition": "refused",
            "reason": str(exc),
            "github_mutated": False,
            "repository_mutated": False,
            "agent_invoked": False,
            "ledger_mutated": False,
            "issues_processed": 0,
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("disposition") in {"eligible", "idle"} else 2


if __name__ == "__main__":
    sys.exit(main())
