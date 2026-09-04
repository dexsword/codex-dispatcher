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
            "Use offline --ticket-file examples with an explicitly supplied --allowlist."
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
        help="owner/name checked against --allowlist when provided",
    )
    parser.add_argument(
        "--allowlist",
        action="append",
        default=[],
        help="allowed owner/name (repeatable). Required; absent allowlist fails closed.",
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

    # Fail closed: without an explicit allowlist, do not inject any seams.
    if not args.allowlist:
        result = assess(issue, ticket)
        result["issues_processed"] = 1
        return result

    require_keys = list(args.require_keys)
    deny_keys = list(args.deny_keys)
    known = {str(x) for x in args.known_ids}
    id_field = args.id_field

    def _validate(t: Mapping[str, Any]) -> None:
        missing = [k for k in require_keys if k not in t]
        if missing:
            raise TicketValidationError(f"missing required ticket keys: {missing}")

    def _safe(t: Mapping[str, Any]) -> None:
        hit = [k for k in deny_keys if k in t]
        if hit:
            raise SafetyViolation(f"ticket contains denied keys: {hit}")

    def _dup(t: Mapping[str, Any]) -> bool:
        value = t.get(id_field)
        return value is not None and str(value) in known

    result = assess(
        issue,
        ticket,
        validate_ticket=CallableTicketValidator(_validate),
        safety_policy=CallableSafetyPolicy(_safe),
        duplicate_check=CallableDuplicateChecker(_dup),
        repository_allowlist=frozenset(args.allowlist),
        repository=args.repository,
    )
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
