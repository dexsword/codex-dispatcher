"""Credential-free staging prepare + exact enumeration + validate (Task F3).

Staging is not a Git worktree. It contains ONLY ``canary/DISPATCHER_STATUS.md``.
No ``.git``, no hooks, no keys, no publisher SSH / deploy-key config.

Publisher credentials live only on the publisher side (one-way boundary).
This module must not accept, store, or propagate ``GIT_SSH_COMMAND``,
deploy-key paths, or ``SSH_AUTH_SOCK``. No Codex invoke (F4).
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields
from pathlib import Path

from codex_dispatcher.canary.profile import CANARY_PERMITTED_PATH
from codex_dispatcher.canary.status import validate_status_document


NOFOLLOW_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
NOFOLLOW_CREATE_FLAGS = (
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
)
STAGING_DIR_MODE = 0o700
PERMITTED_RELATIVE_PATH = CANARY_PERMITTED_PATH

# Isolation: staging APIs must not see publisher SSH / deploy keys.
FORBIDDEN_STAGING_FIELD_NAMES = frozenset(
    {
        "git_ssh_command",
        "git_ssh",
        "ssh_auth_sock",
        "deploy_key",
        "deploy_key_path",
        "deploy_key_private",
        "github_token",
        "gh_token",
        "ssh_identity",
    }
)
STAGING_STRIP_ENV = frozenset(
    {
        "GIT_SSH_COMMAND",
        "GIT_SSH",
        "SSH_AUTH_SOCK",
        "SSH_AGENT_PID",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CONFIG",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
        "GIT_CONFIG_COUNT",
    }
)
_FORBIDDEN_COMPONENTS = frozenset({".git", "hooks"})
_FORBIDDEN_SUFFIXES = (".key", ".pem")
_FORBIDDEN_KEY_NAMES = frozenset(
    {
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "deploy_key",
        "authorized_keys",
        "known_hosts",
    }
)


class StagingError(ValueError):
    """Staging tree is not the exact permitted one-file layout."""


def reject_staging_credential_fields(names: Iterable[object]) -> None:
    """Fail closed if staging config would carry publisher credentials."""
    for raw in names:
        if not isinstance(raw, str):
            raise StagingError("staging field names must be strings")
        lowered = raw.replace("-", "_").lower()
        if lowered in FORBIDDEN_STAGING_FIELD_NAMES:
            raise StagingError(
                f"staging must not carry publisher credential field {raw!r} "
                f"(one-way staging vs publisher boundary)"
            )
        if lowered.startswith("git_ssh") or lowered.endswith("_key"):
            raise StagingError(
                f"staging must not carry publisher credential field {raw!r}"
            )


def staging_isolated_env(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Copy env with publisher SSH / Git auth vars removed.

    Staging APIs never need Git or SSH. Even if the process inherited
    ``GIT_SSH_COMMAND``, staging must not see or propagate it.
    """
    base = dict(os.environ if source is None else source)
    for key in list(base):
        if key in STAGING_STRIP_ENV or key.startswith("GIT_CONFIG_KEY_"):
            base.pop(key, None)
        elif key.startswith("GIT_CONFIG_VALUE_"):
            base.pop(key, None)
    return base


@dataclass(frozen=True)
class StagingConfig:
    """Injected staging root. Credential-free; tests use tmp."""

    staging_root: Path

    def __post_init__(self) -> None:
        reject_staging_credential_fields(f.name for f in fields(self))
        if not isinstance(self.staging_root, Path):
            raise StagingError("staging_root must be a pathlib.Path")


def build_staging_config(**kwargs: object) -> StagingConfig:
    """Constructor that rejects publisher SSH / deploy-key kwargs."""
    reject_staging_credential_fields(kwargs)
    allowed = {f.name for f in fields(StagingConfig)}
    unknown = set(kwargs) - allowed
    if unknown:
        raise StagingError(f"unknown StagingConfig fields: {sorted(unknown)}")
    root = kwargs.get("staging_root")
    if root is None:
        raise StagingError("staging_root is required")
    return StagingConfig(staging_root=root)  # type: ignore[arg-type]


@dataclass(frozen=True)
class PreparedStaging:
    """Result of ``prepare_staging`` — one file, hashed, no ``.git``."""

    root: Path
    relative_path: str
    sha256_hex: str
    size: int


@dataclass(frozen=True)
class StagingValidation:
    """Validated staging payload ready for trusted handoff."""

    root: Path
    relative_path: str
    sha256_hex: str
    payload: bytes
    parsed: dict[str, str]


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_regular_nofollow(path: Path) -> bytes:
    """Open ``path`` with ``O_NOFOLLOW``; require a nonempty regular file."""
    try:
        fd = os.open(path, NOFOLLOW_READ_FLAGS)
    except OSError as exc:
        raise StagingError(f"nofollow open failed for {path}: {exc}") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise StagingError(f"not a regular file: {path}")
        if st.st_size == 0:
            raise StagingError(f"empty file refused: {path}")
        chunks: list[bytes] = []
        remaining = st.st_size
        while remaining > 0:
            block = os.read(fd, remaining)
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        data = b"".join(chunks)
        if len(data) != st.st_size:
            raise StagingError(f"short read of {path}")
        return data
    finally:
        os.close(fd)


def write_regular_nofollow_create(path: Path, data: bytes) -> None:
    """Create ``path`` exclusively with ``O_NOFOLLOW`` (no follow, no clobber)."""
    try:
        fd = os.open(path, NOFOLLOW_CREATE_FLAGS, 0o600)
    except OSError as exc:
        raise StagingError(f"nofollow create failed for {path}: {exc}") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise StagingError(f"created path is not a regular file: {path}")
        written = os.write(fd, data)
        if written != len(data):
            raise StagingError(f"short write of {path}")
    finally:
        os.close(fd)


def require_realpath_contained(path: Path, root: Path) -> Path:
    """W7: resolved path must stay inside ``root``."""
    real_root = os.path.realpath(root)
    real_path = os.path.realpath(path)
    if real_path != real_root and not real_path.startswith(real_root + os.sep):
        raise StagingError(
            f"realpath escapes containment root: {real_path!r} not under {real_root!r}"
        )
    return Path(real_path)


def _reject_name(name: str, *, relative: str) -> None:
    if name in _FORBIDDEN_COMPONENTS:
        raise StagingError(f"forbidden staging component {name!r} at {relative}")
    lowered = name.lower()
    if lowered in _FORBIDDEN_KEY_NAMES:
        raise StagingError(f"key-like name refused at {relative}")
    if lowered.endswith(_FORBIDDEN_SUFFIXES):
        raise StagingError(f"key/pem suffix refused at {relative}")


def _is_allowed_staging_directory(relative: str, *, permitted: str) -> bool:
    """True iff *relative* is a strict prefix of the permitted file path.

    The only allowed directory under the staging root is ``canary/``
    (prefix of ``canary/DISPATCHER_STATUS.md``). Unexpected empty dirs
    such as ``evil_empty/`` or ``canary/nested_empty/`` fail closed.
    """
    if not isinstance(relative, str) or not relative:
        return False
    return permitted.startswith(relative + "/")


class StagingTreeEnumerator:
    """Exact one-file enumeration. Fail closed on extras/symlinks/.git/keys.

    Directories are allowed only when they are a strict prefix of
    ``canary/DISPATCHER_STATUS.md`` (i.e. ``canary/`` only). Empty
    unexpected directories fail closed — they are not ignored.
    """

    permitted_relative_path = PERMITTED_RELATIVE_PATH

    def enumerate(self, staging_root: Path) -> tuple[str, ...]:
        if not isinstance(staging_root, Path):
            raise StagingError("staging_root must be a pathlib.Path")
        if not staging_root.exists():
            raise StagingError(f"staging root is missing: {staging_root}")
        try:
            root_st = os.lstat(staging_root)
        except OSError as exc:
            raise StagingError(f"cannot lstat staging root: {exc}") from exc
        if stat.S_ISLNK(root_st.st_mode):
            raise StagingError("staging root must not be a symlink")
        if not stat.S_ISDIR(root_st.st_mode):
            raise StagingError("staging root must be a directory")
        found = self._walk(staging_root)
        if not found:
            raise StagingError("staging tree is empty; permitted file is missing")
        expected = (self.permitted_relative_path,)
        if tuple(found) != expected:
            raise StagingError(
                "staging enumeration must be exactly "
                f"{expected!r}; got {tuple(found)!r}"
            )
        return expected

    def _walk(self, root: Path) -> list[str]:
        found: list[str] = []
        self._scan(root, relative="", found=found)
        found.sort()
        return found

    def _scan(self, root: Path, *, relative: str, found: list[str]) -> None:
        current = root if not relative else root / relative
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            raise StagingError(f"cannot scan {current}: {exc}") from exc
        for entry in entries:
            name = entry.name
            child_rel = name if not relative else f"{relative}/{name}"
            _reject_name(name, relative=child_rel)
            try:
                is_link = entry.is_symlink()
            except OSError as exc:
                raise StagingError(f"cannot stat {child_rel}: {exc}") from exc
            if is_link:
                raise StagingError(f"symlink refused: {child_rel}")
            if entry.is_dir(follow_symlinks=False):
                if not _is_allowed_staging_directory(
                    child_rel, permitted=self.permitted_relative_path
                ):
                    raise StagingError(
                        f"unexpected directory refused: {child_rel} "
                        f"(only strict prefixes of {self.permitted_relative_path} "
                        "are allowed; empty extras fail closed)"
                    )
                self._scan(root, relative=child_rel, found=found)
            elif entry.is_file(follow_symlinks=False):
                try:
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError as exc:
                    raise StagingError(f"cannot stat {child_rel}: {exc}") from exc
                if size == 0:
                    raise StagingError(f"empty file refused: {child_rel}")
                found.append(child_rel)
            else:
                raise StagingError(f"non-regular staging entry refused: {child_rel}")


def prepare_staging(
    *,
    staging_root: Path,
    source_status_path: Path,
) -> PreparedStaging:
    """Copy the permitted file into a credential-free staging directory.

    Tests inject a tmp ``staging_root``. Does not create ``.git``. Does not
    read or propagate ``GIT_SSH_COMMAND`` / deploy keys. Does not auto-delete
    on failure.
    """
    reject_staging_credential_fields(())
    # Touch isolated env so a leak of publisher SSH cannot ride along.
    staging_isolated_env()
    if not isinstance(staging_root, Path) or not isinstance(source_status_path, Path):
        raise StagingError("prepare_staging requires pathlib.Path arguments")
    source_data = read_regular_nofollow(source_status_path)
    if staging_root.exists():
        try:
            already = list(os.scandir(staging_root))
        except OSError as exc:
            raise StagingError(f"cannot inspect staging_root: {exc}") from exc
        if already:
            raise StagingError(
                "staging_root must be empty; extras fail closed (no auto-delete)"
            )
    else:
        os.mkdir(staging_root, STAGING_DIR_MODE)
    os.chmod(staging_root, STAGING_DIR_MODE)
    canary_dir = staging_root / "canary"
    if canary_dir.exists():
        raise StagingError("canary/ already exists in staging_root (no auto-delete)")
    os.mkdir(canary_dir, STAGING_DIR_MODE)
    dest = staging_root / PERMITTED_RELATIVE_PATH
    write_regular_nofollow_create(dest, source_data)
    copied = read_regular_nofollow(dest)
    digest = sha256_hex(copied)
    if copied != source_data or digest != sha256_hex(source_data):
        raise StagingError("staging copy hash mismatch (retained; no auto-delete)")
    # Confirm exact layout and no .git.
    StagingTreeEnumerator().enumerate(staging_root)
    git_dir = staging_root / ".git"
    if git_dir.exists() or os.path.lexists(git_dir):
        raise StagingError("staging must not contain .git")
    return PreparedStaging(
        root=staging_root,
        relative_path=PERMITTED_RELATIVE_PATH,
        sha256_hex=digest,
        size=len(copied),
    )


def validate_staging(staging_root: Path) -> StagingValidation:
    """Enumerate + F2 ``validate_status_document`` + W7 + realpath + sha256."""
    relative = StagingTreeEnumerator().enumerate(staging_root)[0]
    path = staging_root / relative
    require_realpath_contained(path, staging_root)
    try:
        link_st = os.lstat(path)
    except OSError as exc:
        raise StagingError(f"cannot lstat permitted path: {exc}") from exc
    if stat.S_ISLNK(link_st.st_mode):
        raise StagingError("W7: permitted path must not be a symlink")
    if not stat.S_ISREG(link_st.st_mode):
        raise StagingError("W7: permitted path must be a regular file")
    payload = read_regular_nofollow(path)
    digest = sha256_hex(payload)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StagingError("status file must be UTF-8") from exc
    parsed = validate_status_document(text)
    return StagingValidation(
        root=staging_root,
        relative_path=relative,
        sha256_hex=digest,
        payload=payload,
        parsed=parsed,
    )


# F3 packet name.
validate = validate_staging

# Self-check: StagingConfig must stay credential-free.
reject_staging_credential_fields(f.name for f in fields(StagingConfig))


__all__ = [
    "FORBIDDEN_STAGING_FIELD_NAMES",
    "NOFOLLOW_CREATE_FLAGS",
    "NOFOLLOW_READ_FLAGS",
    "PERMITTED_RELATIVE_PATH",
    "PreparedStaging",
    "STAGING_DIR_MODE",
    "STAGING_STRIP_ENV",
    "StagingConfig",
    "StagingError",
    "StagingTreeEnumerator",
    "StagingValidation",
    "build_staging_config",
    "prepare_staging",
    "read_regular_nofollow",
    "reject_staging_credential_fields",
    "require_realpath_contained",
    "sha256_hex",
    "staging_isolated_env",
    "validate",
    "validate_staging",
    "write_regular_nofollow_create",
]
