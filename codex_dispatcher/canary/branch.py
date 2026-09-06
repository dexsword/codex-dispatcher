"""Branch-only canary ref helper (W2/W10). No PR-open API."""

from __future__ import annotations


CANARY_REF_PREFIX = "refs/heads/agent/canary/"
_FORBIDDEN_DEFAULT_LEAVES = frozenset({"main", "master"})
_FORBIDDEN_DEFAULT_REFS = frozenset(
    {
        "main",
        "master",
        "heads/main",
        "heads/master",
        "refs/heads/main",
        "refs/heads/master",
    }
)


class CanaryBranchError(ValueError):
    """Ref is not a permitted ``refs/heads/agent/canary/*`` branch."""


class CanaryApiError(RuntimeError):
    """Forbidden canary API operation (dispatcher must not open PRs)."""


def require_canary_branch_ref(ref: object) -> str:
    """Accept only ``refs/heads/agent/canary/<name>``. Forbid main/master."""
    if not isinstance(ref, str) or not ref:
        raise CanaryBranchError("canary ref must be a nonempty string")
    if "\x00" in ref or any(ord(c) < 32 or ord(c) == 127 for c in ref):
        raise CanaryBranchError("canary ref must not contain NUL or control characters")
    if any(c.isspace() for c in ref):
        raise CanaryBranchError("canary ref must not contain whitespace")
    stripped = ref.strip("/")
    leaf = ref.rsplit("/", 1)[-1]
    if ref in _FORBIDDEN_DEFAULT_REFS or stripped in _FORBIDDEN_DEFAULT_REFS:
        raise CanaryBranchError("main/master is forbidden for canary publish")
    if leaf in _FORBIDDEN_DEFAULT_LEAVES:
        raise CanaryBranchError("main/master is forbidden for canary publish")
    if not ref.startswith(CANARY_REF_PREFIX):
        raise CanaryBranchError(
            f"canary ref must start with {CANARY_REF_PREFIX!r}; got {ref!r}"
        )
    rest = ref[len(CANARY_REF_PREFIX) :]
    if not rest or rest.startswith("/") or rest.endswith("/"):
        raise CanaryBranchError(f"canary ref suffix is empty or malformed: {ref!r}")
    if any(part in {".", "..", ""} for part in rest.split("/")):
        raise CanaryBranchError(f"canary ref suffix must not escape: {ref!r}")
    return ref


def refuse_open_draft_pr(*_args: object, **_kwargs: object) -> None:
    """Hard refuse — dispatcher canary API must not open draft PRs (W10)."""
    raise CanaryApiError(
        "canary API must not open pull requests (branch-only W10); "
        "Picard routes an external identity after branch + evidence"
    )
