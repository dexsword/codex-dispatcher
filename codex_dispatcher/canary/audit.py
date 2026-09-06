"""Audit stub for F3 (changed_paths, hashes, git.json). Mock push only."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from codex_dispatcher.canary.branch import require_canary_branch_ref
from codex_dispatcher.canary.publisher import HOOKS_PATH, PushPlan
from codex_dispatcher.canary.staging import PERMITTED_RELATIVE_PATH


class AuditError(ValueError):
    """Audit stub refused (fail closed)."""


@dataclass(frozen=True)
class AuditStub:
    audit_root: Path
    changed_paths: tuple[str, ...]
    hashes: dict[str, str]
    git: dict[str, object]


def write_audit_stub(
    *,
    audit_root: Path,
    changed_paths: Sequence[str],
    hashes: Mapping[str, str],
    branch_ref: str,
    commit_sha: str,
    push_plan: PushPlan | None = None,
    push_mocked: bool = True,
) -> AuditStub:
    """Write ``changed_paths.txt``, ``hashes.json``, and ``git.json``.

    Push is recorded as mocked — F3 does not perform a live push.
    """
    require_canary_branch_ref(branch_ref)
    if not isinstance(audit_root, Path):
        raise AuditError("audit_root must be a pathlib.Path")
    paths = tuple(changed_paths)
    if paths != (PERMITTED_RELATIVE_PATH,):
        raise AuditError(
            f"changed_paths must be exactly ({PERMITTED_RELATIVE_PATH!r},); got {paths!r}"
        )
    if PERMITTED_RELATIVE_PATH not in hashes:
        raise AuditError("hashes must include the permitted path")
    if not push_mocked:
        raise AuditError("F3 audit stub records mock push only (no live push)")
    git_doc: dict[str, object] = {
        "branch": branch_ref,
        "commit": commit_sha,
        "remote": "[redacted]",
        "push": {
            "mocked": True,
            "result": "ok",
            "live": False,
        },
        "hooks_disabled": True,
        "hooksPath": HOOKS_PATH,
        "non_force": True,
        "force": False,
        "force_with_lease": False,
    }
    if push_plan is not None:
        git_doc["argv"] = list(push_plan.argv)
        git_doc["refspec"] = push_plan.refspec
        git_doc["remote_name"] = push_plan.remote
    if not audit_root.exists():
        audit_root.mkdir(mode=0o700)
    (audit_root / "changed_paths.txt").write_text(
        PERMITTED_RELATIVE_PATH + "\n", encoding="utf-8"
    )
    (audit_root / "hashes.json").write_text(
        json.dumps(dict(hashes), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (audit_root / "git.json").write_text(
        json.dumps(git_doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return AuditStub(
        audit_root=audit_root,
        changed_paths=paths,
        hashes=dict(hashes),
        git=git_doc,
    )


__all__ = ["AuditError", "AuditStub", "write_audit_stub"]
