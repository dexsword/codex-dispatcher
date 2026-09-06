"""Trusted publisher: handoff, commit, publish, push (Task F3).

One-way boundary: publisher config (including ``GIT_SSH_COMMAND`` / deploy
key) lives only here. Staging APIs never receive it.

Every commit / publish / push path calls ``require_canary_branch_ref``
*immediately first*. Git is invoked with a subprocess argv list
(``shell=False`` always). Push refspec is hard-coded non-force:

    [git, push, <remote>, <sha>:refs/heads/agent/canary/<validated>]

Hooks are disabled via sanitized env (``core.hooksPath=/dev/null``).
Canonical remote is validated before push. No live deploy-key install
and no Codex invoke (F4). Failures retain staging/worktree (no auto-delete).
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codex_dispatcher.canary.branch import require_canary_branch_ref
from codex_dispatcher.canary.staging import (
    PERMITTED_RELATIVE_PATH,
    StagingError,
    read_regular_nofollow,
    require_realpath_contained,
    sha256_hex,
    validate_staging,
)


GIT_BIN = "git"
HOOKS_PATH = "/dev/null"
HOOKS_CONFIG_KEY = "core.hooksPath"

_SHA_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_REMOTE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")

NOFOLLOW_REPLACE_FLAGS = os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC

# Inherited Git knobs that must not leak into publisher git(1).
_PUBLISHER_STRIP_ENV = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CONFIG",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
        "GIT_CONFIG_COUNT",
        "GIT_EXEC_PATH",
        "GIT_TEMPLATE_DIR",
        "GIT_PREFIX",
        "GIT_SSH",
        "GIT_SSH_COMMAND",
    }
)

GitRunner = Callable[..., subprocess.CompletedProcess[str]]


class PublisherError(RuntimeError):
    """Trusted-publisher path refused (fail closed; trees retained)."""


class HandoffError(PublisherError):
    """Same-bytes / hash handoff failed. Staging and worktree are retained."""


@dataclass(frozen=True)
class PublisherConfig:
    """Publisher-side only. Staging APIs must not be given this object.

    ``git_ssh_command`` / ``deploy_key_path`` are optional and never flow
    into staging. Tests typically omit them (mock push).
    """

    worktree_root: Path
    remote_name: str
    canonical_remote_url: str
    git_ssh_command: str | None = None
    deploy_key_path: Path | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.worktree_root, Path):
            raise PublisherError("worktree_root must be a pathlib.Path")
        if not isinstance(self.remote_name, str) or _REMOTE_NAME_RE.fullmatch(
            self.remote_name
        ) is None:
            raise PublisherError(f"invalid remote name: {self.remote_name!r}")
        if not isinstance(self.canonical_remote_url, str) or not self.canonical_remote_url:
            raise PublisherError("canonical_remote_url must be a nonempty string")
        if "\x00" in self.canonical_remote_url or any(
            ord(c) < 32 for c in self.canonical_remote_url
        ):
            raise PublisherError("canonical_remote_url must not contain controls")
        if self.git_ssh_command is not None:
            if not isinstance(self.git_ssh_command, str) or not self.git_ssh_command:
                raise PublisherError("git_ssh_command must be a nonempty string when set")
        if self.deploy_key_path is not None and not isinstance(self.deploy_key_path, Path):
            raise PublisherError("deploy_key_path must be a pathlib.Path when set")


@dataclass(frozen=True)
class HandoffResult:
    relative_path: str
    sha256_hex: str
    staging_root: Path
    worktree_root: Path


@dataclass(frozen=True)
class PushPlan:
    """Hard-coded non-force argv. Never includes ``--force`` or a ``+`` refspec."""

    argv: tuple[str, ...]
    remote: str
    sha: str
    branch_ref: str
    refspec: str


def sanitize_publisher_git_env(
    *,
    git_ssh_command: str | None = None,
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Sanitize Git env; disable hooks; re-inject publisher SSH only here."""
    env = {k: v for k, v in (os.environ if source is None else source).items()}
    for key in list(env):
        if key in _PUBLISHER_STRIP_ENV or key.startswith("GIT_CONFIG_KEY_"):
            env.pop(key, None)
        elif key.startswith("GIT_CONFIG_VALUE_"):
            env.pop(key, None)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = HOOKS_CONFIG_KEY
    env["GIT_CONFIG_VALUE_0"] = HOOKS_PATH
    if git_ssh_command:
        env["GIT_SSH_COMMAND"] = git_ssh_command
    return env


def hooks_disabled(env: Mapping[str, str]) -> bool:
    """True when sanitized env pins ``core.hooksPath`` to ``/dev/null``."""
    return (
        env.get("GIT_CONFIG_KEY_0") == HOOKS_CONFIG_KEY
        and env.get("GIT_CONFIG_VALUE_0") == HOOKS_PATH
        and env.get("GIT_CONFIG_NOSYSTEM") == "1"
    )


def require_canonical_remote(*, observed: str, expected: str) -> str:
    if not isinstance(observed, str) or not isinstance(expected, str):
        raise PublisherError("canonical remote values must be strings")
    if observed != expected:
        raise PublisherError(
            f"canonical remote mismatch: observed {observed!r} != expected {expected!r}"
        )
    return observed


def refuse_force_push(*, force: bool = False, force_with_lease: bool = False) -> None:
    if force or force_with_lease:
        raise PublisherError(
            "force push is refused (v1 hard-coded non-force only; "
            "no --force / --force-with-lease / +refspec)"
        )


def require_non_force_sha(sha: object) -> str:
    if not isinstance(sha, str) or _SHA_RE.fullmatch(sha) is None:
        raise PublisherError("commit sha must be lowercase hex (40 or 64 chars)")
    if sha.startswith("+"):
        raise PublisherError("sha must not start with '+' (force refspec)")
    return sha


def build_non_force_push_argv(*, remote: str, sha: str, branch_ref: str) -> PushPlan:
    """Return ``[git, push, remote, sha:refs/heads/agent/canary/<validated>]``."""
    validated = require_canary_branch_ref(branch_ref)
    if not isinstance(remote, str) or _REMOTE_NAME_RE.fullmatch(remote) is None:
        raise PublisherError(f"invalid remote name: {remote!r}")
    digest = require_non_force_sha(sha)
    refspec = f"{digest}:{validated}"
    if refspec.startswith("+"):
        raise PublisherError("force refspec (+) refused")
    if "--force" in refspec or "--force-with-lease" in refspec:
        raise PublisherError("force tokens in refspec refused")
    argv = (GIT_BIN, "push", remote, refspec)
    if any(part in {"--force", "--force-with-lease"} for part in argv):
        raise PublisherError("force flags must never appear in push argv")
    if any(isinstance(part, str) and part.startswith("+") for part in argv):
        raise PublisherError("plus-prefixed argv element refused")
    return PushPlan(
        argv=argv,
        remote=remote,
        sha=digest,
        branch_ref=validated,
        refspec=refspec,
    )


def _run_git(
    argv: list[str] | tuple[str, ...],
    *,
    cwd: Path,
    env: Mapping[str, str],
    runner: GitRunner,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    if not isinstance(argv, (list, tuple)) or not argv:
        raise PublisherError("git argv must be a nonempty list/tuple")
    if any(not isinstance(item, str) for item in argv):
        raise PublisherError("git argv items must be strings (never a shell string)")
    if argv[0] != GIT_BIN:
        raise PublisherError("git argv[0] must be 'git'")
    if "--force" in argv or "--force-with-lease" in argv:
        raise PublisherError("force flags refused in git argv")
    if any(item.startswith("+") for item in argv[1:]):
        raise PublisherError("plus-prefixed git argv refused")
    kwargs: dict[str, Any] = {
        "cwd": os.fspath(cwd),
        "env": dict(env),
        "check": True,
        "shell": False,
        "text": True,
    }
    if capture:
        kwargs["capture_output"] = True
    return runner(list(argv), **kwargs)


def write_regular_nofollow_replace(path: Path, data: bytes) -> None:
    """Overwrite an existing regular file with ``O_NOFOLLOW`` (W7)."""
    try:
        link_st = os.lstat(path)
    except OSError as exc:
        raise HandoffError(
            f"W7: destination must already exist as a regular file: {exc}"
        ) from exc
    if stat.S_ISLNK(link_st.st_mode):
        raise HandoffError("W7: destination must not be a symlink (no auto-delete)")
    if not stat.S_ISREG(link_st.st_mode):
        raise HandoffError("W7: destination must be a regular file (no auto-delete)")
    try:
        fd = os.open(path, NOFOLLOW_REPLACE_FLAGS)
    except OSError as exc:
        raise HandoffError(f"nofollow write failed for {path}: {exc}") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise HandoffError(f"destination fd is not a regular file: {path}")
        written = os.write(fd, data)
        if written != len(data):
            raise HandoffError(f"short write of {path} (no auto-delete)")
    finally:
        os.close(fd)


def handoff_to_trusted_worktree(
    *,
    staging_root: Path,
    worktree_root: Path,
    expected_sha256: str,
) -> HandoffResult:
    """Copy validated bytes with nofollow write; abort on hash mismatch.

    Hash equality is required before any commit. Failures retain both trees.
    """
    try:
        validated = validate_staging(staging_root)
    except StagingError as exc:
        raise HandoffError(f"staging validate failed (trees retained): {exc}") from exc
    if validated.sha256_hex != expected_sha256:
        raise HandoffError(
            "hash mismatch before handoff write "
            f"(staging={validated.sha256_hex} expected={expected_sha256}; "
            "trees retained; no auto-delete)"
        )
    dest = worktree_root / PERMITTED_RELATIVE_PATH
    require_realpath_contained(dest, worktree_root)
    write_regular_nofollow_replace(dest, validated.payload)
    written = read_regular_nofollow(dest)
    written_hex = sha256_hex(written)
    if written != validated.payload or written_hex != validated.sha256_hex:
        raise HandoffError(
            "hash mismatch after nofollow write "
            f"(dest={written_hex} staging={validated.sha256_hex}; "
            "abort before commit; trees retained; no auto-delete)"
        )
    return HandoffResult(
        relative_path=PERMITTED_RELATIVE_PATH,
        sha256_hex=written_hex,
        staging_root=staging_root,
        worktree_root=worktree_root,
    )


def commit_canary(
    *,
    branch_ref: str,
    worktree_root: Path,
    message: str,
    publisher: PublisherConfig,
    runner: GitRunner | None = None,
) -> str:
    """Commit the single permitted path. ``require_canary_branch_ref`` first."""
    require_canary_branch_ref(branch_ref)
    run = runner or subprocess.run
    env = sanitize_publisher_git_env(git_ssh_command=publisher.git_ssh_command)
    if not hooks_disabled(env):
        raise PublisherError("publisher Git env must disable hooks")
    _run_git(
        (GIT_BIN, "add", "--", PERMITTED_RELATIVE_PATH),
        cwd=worktree_root,
        env=env,
        runner=run,
        capture=True,
    )
    _run_git(
        (
            GIT_BIN,
            "-c",
            "user.name=codex-dispatcher-canary",
            "-c",
            "user.email=canary@invalid",
            "commit",
            "-m",
            message,
            "--only",
            "--",
            PERMITTED_RELATIVE_PATH,
        ),
        cwd=worktree_root,
        env=env,
        runner=run,
        capture=True,
    )
    parsed = _run_git(
        (GIT_BIN, "rev-parse", "HEAD"),
        cwd=worktree_root,
        env=env,
        runner=run,
        capture=True,
    )
    sha = (parsed.stdout or "").strip()
    return require_non_force_sha(sha)


def push_canary(
    *,
    branch_ref: str,
    sha: str,
    publisher: PublisherConfig,
    observed_remote_url: str | None = None,
    force: bool = False,
    force_with_lease: bool = False,
    runner: GitRunner | None = None,
) -> PushPlan:
    """Non-force push. ``require_canary_branch_ref`` first. No ``shell=True``."""
    require_canary_branch_ref(branch_ref)
    refuse_force_push(force=force, force_with_lease=force_with_lease)
    run = runner or subprocess.run
    env = sanitize_publisher_git_env(git_ssh_command=publisher.git_ssh_command)
    if not hooks_disabled(env):
        raise PublisherError("publisher Git env must disable hooks")
    observed = observed_remote_url
    if observed is None:
        queried = _run_git(
            (GIT_BIN, "remote", "get-url", publisher.remote_name),
            cwd=publisher.worktree_root,
            env=env,
            runner=run,
            capture=True,
        )
        observed = (queried.stdout or "").strip()
    require_canonical_remote(
        observed=observed, expected=publisher.canonical_remote_url
    )
    plan = build_non_force_push_argv(
        remote=publisher.remote_name, sha=sha, branch_ref=branch_ref
    )
    _run_git(plan.argv, cwd=publisher.worktree_root, env=env, runner=run)
    return plan


def publish_canary(
    *,
    branch_ref: str,
    worktree_root: Path,
    message: str,
    publisher: PublisherConfig,
    observed_remote_url: str | None = None,
    force: bool = False,
    force_with_lease: bool = False,
    runner: GitRunner | None = None,
) -> tuple[str, PushPlan]:
    """Publish path (commit + push). ``require_canary_branch_ref`` first."""
    require_canary_branch_ref(branch_ref)
    refuse_force_push(force=force, force_with_lease=force_with_lease)
    sha = commit_canary(
        branch_ref=branch_ref,
        worktree_root=worktree_root,
        message=message,
        publisher=publisher,
        runner=runner,
    )
    plan = push_canary(
        branch_ref=branch_ref,
        sha=sha,
        publisher=publisher,
        observed_remote_url=observed_remote_url,
        runner=runner,
    )
    return sha, plan


__all__ = [
    "GIT_BIN",
    "HOOKS_CONFIG_KEY",
    "HOOKS_PATH",
    "HandoffError",
    "HandoffResult",
    "NOFOLLOW_REPLACE_FLAGS",
    "PublisherConfig",
    "PublisherError",
    "PushPlan",
    "build_non_force_push_argv",
    "commit_canary",
    "handoff_to_trusted_worktree",
    "hooks_disabled",
    "publish_canary",
    "push_canary",
    "refuse_force_push",
    "require_canonical_remote",
    "require_non_force_sha",
    "sanitize_publisher_git_env",
    "write_regular_nofollow_replace",
]
