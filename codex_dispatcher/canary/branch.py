"""Branch-only canary ref helper (W2/W10). No PR-open API.

F3 strengthens Git ref rejection (git-check-ref-format subset): ``..``,
``@{``, backslash, controls/NUL, trailing dots, ``.lock`` endings, and
empty components. Callers that commit/publish/push must invoke
``require_canary_branch_ref`` immediately before those paths.
"""

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
# git-check-ref-format specials that must not appear in a canary ref.
_FORBIDDEN_REF_SUBSTRINGS = ("..", "@{", "\\")
_FORBIDDEN_REF_CHARS = frozenset("~^:?*[")


class CanaryBranchError(ValueError):
    """Ref is not a permitted ``refs/heads/agent/canary/*`` branch."""


class CanaryApiError(RuntimeError):
    """Forbidden canary API operation (dispatcher must not open PRs)."""


def require_canary_branch_ref(ref: object) -> str:
    """Accept only ``refs/heads/agent/canary/<name>``. Forbid main/master.

    Also reject invalid Git refs: ``..``, ``@{``, backslash, controls/NUL,
    trailing dots, ``.lock`` component endings, and empty components.
    """
    if not isinstance(ref, str) or not ref:
        raise CanaryBranchError("canary ref must be a nonempty string")
    if "\x00" in ref or any(ord(c) < 32 or ord(c) == 127 for c in ref):
        raise CanaryBranchError("canary ref must not contain NUL or control characters")
    if any(c.isspace() for c in ref):
        raise CanaryBranchError("canary ref must not contain whitespace")
    for needle in _FORBIDDEN_REF_SUBSTRINGS:
        if needle in ref:
            raise CanaryBranchError(
                f"canary ref must not contain {needle!r}; got {ref!r}"
            )
    if any(ch in _FORBIDDEN_REF_CHARS for ch in ref):
        raise CanaryBranchError(
            f"canary ref contains a forbidden Git special character: {ref!r}"
        )
    if ref.endswith("."):
        raise CanaryBranchError(f"canary ref must not end with a trailing dot: {ref!r}")
    stripped = ref.strip("/")
    leaf = ref.rsplit("/", 1)[-1]
    if ref in _FORBIDDEN_DEFAULT_REFS or stripped in _FORBIDDEN_DEFAULT_REFS:
        raise CanaryBranchError("main/master is forbidden for canary publish")
    if leaf in _FORBIDDEN_DEFAULT_LEAVES:
        raise CanaryBranchError("main/master is forbidden for canary publish")
    if leaf.endswith(".lock"):
        raise CanaryBranchError(
            f"canary ref component must not end with .lock: {ref!r}"
        )
    if not ref.startswith(CANARY_REF_PREFIX):
        raise CanaryBranchError(
            f"canary ref must start with {CANARY_REF_PREFIX!r}; got {ref!r}"
        )
    rest = ref[len(CANARY_REF_PREFIX) :]
    if not rest or rest.startswith("/") or rest.endswith("/"):
        raise CanaryBranchError(f"canary ref suffix is empty or malformed: {ref!r}")
    for part in rest.split("/"):
        if part in {".", "..", ""}:
            raise CanaryBranchError(f"canary ref suffix must not escape: {ref!r}")
        if part.endswith(".lock"):
            raise CanaryBranchError(
                f"canary ref component must not end with .lock: {ref!r}"
            )
        if part.endswith("."):
            raise CanaryBranchError(
                f"canary ref component must not end with a trailing dot: {ref!r}"
            )
        if part.startswith("."):
            raise CanaryBranchError(
                f"canary ref component must not start with a dot: {ref!r}"
            )
    return ref


def refuse_open_draft_pr(*_args: object, **_kwargs: object) -> None:
    """Hard refuse — dispatcher canary API must not open draft PRs (W10)."""
    raise CanaryApiError(
        "canary API must not open pull requests (branch-only W10); "
        "Picard routes an external identity after branch + evidence"
    )
