"""Frozen injectable ``CanaryProfile`` (fail closed, default off)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields

from codex_dispatcher.lock import (
    AGENT_LOCK_BASENAME,
    IMPLEMENTATION_LOCK_BASENAME,
    LockPathConfig,
    require_allowed_lock_basename,
)
from codex_dispatcher.safety.config import (
    PathRule,
    SafetyRuleConfig,
    validate_rule_config,
)
from codex_dispatcher.validation import ValidationError


CANARY_ALLOWED_REPOSITORIES = frozenset({"dexsword/dextech"})
CANARY_PERMITTED_PATH = "canary/DISPATCHER_STATUS.md"
CANARY_PERMITTED_PATHS = frozenset({CANARY_PERMITTED_PATH})
DISPATCHER_CANARY_LABEL = "dispatcher-canary"

# Isolation: these names must never be fields or constructor kwargs.
FORBIDDEN_PROFILE_FIELD_NAMES = frozenset(
    {
        "github_token",
        "githubtoken",
        "gittoken",
        "gh",
        "gh_token",
        "gh_auth",
        "ghtoken",
        "app_key",
        "app_private_key",
        "app_id",
        "github_app_key",
        "github_app_private_key",
        "github_app_id",
        "private_key",
        "access_token",
        "bearer_token",
        "oauth_token",
        "personal_access_token",
        "ssh_auth_sock",
        "deploy_key",
        "deploy_key_private",
    }
)


class CanaryProfileError(ValueError):
    """Invalid CanaryProfile construction or isolation violation."""


class CanaryGateError(RuntimeError):
    """Activation gates not satisfied. Checker only — does not flip env."""


def reject_forbidden_profile_fields(names: Iterable[object]) -> None:
    """Fail closed on GITHUB_TOKEN-like / gh / App-key / ORCHESTRATOR_* names."""
    for raw in names:
        if not isinstance(raw, str):
            raise CanaryProfileError("profile field names must be strings")
        normalized = raw.replace("-", "_")
        lowered = normalized.lower()
        if lowered in FORBIDDEN_PROFILE_FIELD_NAMES:
            raise CanaryProfileError(
                f"isolation: {raw!r} is forbidden on CanaryProfile "
                f"(no GitHub API / gh / App key credentials)"
            )
        if lowered.startswith("orchestrator_"):
            raise CanaryProfileError(
                f"isolation: CopyMoney ORCHESTRATOR_* field {raw!r} is forbidden"
            )
        if lowered.startswith("gh_") or lowered == "gh":
            raise CanaryProfileError(
                f"isolation: gh credential field {raw!r} is forbidden on CanaryProfile"
            )
        if "github_token" in lowered or lowered.endswith("_token") or lowered == "token":
            raise CanaryProfileError(
                f"isolation: token field {raw!r} is forbidden on CanaryProfile"
            )


def _require_exact_allowlist(value: object) -> frozenset[str]:
    if value is None:
        raise CanaryProfileError(
            "allowed_repositories is required and must be exactly "
            "frozenset({'dexsword/dextech'}); empty/other fail closed"
        )
    try:
        frozen = frozenset(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise CanaryProfileError("allowed_repositories must be a set of repository strings") from exc
    if frozen != CANARY_ALLOWED_REPOSITORIES:
        raise CanaryProfileError(
            "allowed_repositories must be exactly frozenset({'dexsword/dextech'}); "
            "runtime expansion is forbidden"
        )
    return CANARY_ALLOWED_REPOSITORIES


def _require_exact_permitted_paths(value: object) -> frozenset[str]:
    if value is None:
        raise CanaryProfileError(
            "permitted_paths is required and must be exactly "
            "frozenset({'canary/DISPATCHER_STATUS.md'})"
        )
    try:
        frozen = frozenset(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise CanaryProfileError("permitted_paths must be a set of path strings") from exc
    if frozen != CANARY_PERMITTED_PATHS:
        raise CanaryProfileError(
            "permitted_paths must be exactly frozenset({'canary/DISPATCHER_STATUS.md'})"
        )
    return CANARY_PERMITTED_PATHS


def _require_canary_lock_paths(lock_paths: object) -> LockPathConfig:
    if not isinstance(lock_paths, LockPathConfig):
        raise CanaryProfileError("lock_paths must be a LockPathConfig (F1 types; do not reimplement locks)")
    # Consume F1 basename allowlist — exact agent.lock + implementation.lock.
    try:
        require_allowed_lock_basename(lock_paths.global_agent_lock.name)
        require_allowed_lock_basename(lock_paths.implementation_lock.name)
    except Exception as exc:
        raise CanaryProfileError(f"canary lock basenames must be F1-allowlisted: {exc}") from exc
    if lock_paths.global_agent_lock.name != AGENT_LOCK_BASENAME:
        raise CanaryProfileError("global_agent_lock must be agent.lock")
    if lock_paths.implementation_lock.name != IMPLEMENTATION_LOCK_BASENAME:
        raise CanaryProfileError("implementation_lock must be implementation.lock")
    return lock_paths


def _require_nonempty_safety_rules(config: object) -> SafetyRuleConfig:
    if not isinstance(config, SafetyRuleConfig):
        raise CanaryProfileError("safety_rules must be a SafetyRuleConfig (Task E N2)")
    try:
        validate_rule_config(config)
    except ValidationError as exc:
        raise CanaryProfileError(f"safety_rules is invalid: {exc}") from exc
    if not (config.denied_paths or config.protected_paths or config.prohibited_actions):
        raise CanaryProfileError(
            "empty SafetyRuleConfig refused (Task E N2); inject a nonempty config"
        )
    return config


def _require_canary_label(label: object) -> str:
    if label is None or (isinstance(label, str) and not label.strip()):
        raise CanaryProfileError(
            "canary_label is required (fail closed). Assess must read the real "
            "GitHub issue label metadata, not a ticket JSON field named label."
        )
    if not isinstance(label, str):
        raise CanaryProfileError("canary_label must be a string")
    if label != DISPATCHER_CANARY_LABEL:
        raise CanaryProfileError(
            f"canary_label must be exactly {DISPATCHER_CANARY_LABEL!r}; got {label!r}"
        )
    return DISPATCHER_CANARY_LABEL


def _require_off_or_bool(value: object, *, label: str, allow_true: bool) -> bool:
    if type(value) is not bool:
        raise CanaryProfileError(f"{label} must be a bool")
    if value and not allow_true:
        raise CanaryProfileError(f"{label} must be False (fail closed)")
    return value


def _require_identity(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CanaryProfileError(f"{label} must be a nonempty string")
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        raise CanaryProfileError(f"{label} must not contain whitespace or control characters")
    return value


def minimal_canary_safety_rule_config() -> SafetyRuleConfig:
    """Minimal nonempty stub (F5 owns the full website table)."""
    return SafetyRuleConfig(
        denied_paths=(
            PathRule(rule_id="canary.stub.deny-env", pattern=r"(^|/)\.env(\.|$)"),
        ),
        protected_paths=(),
        prohibited_actions=(),
    )


@dataclass(frozen=True)
class CanaryProfile:
    """Injectable DexTech canary config. Frozen; gates default off.

    Runner/publisher identity fields are allowed. GitHub token / gh / App key
    fields are forbidden. CopyMoney ``ORCHESTRATOR_*`` is forbidden.

    ``open_draft_pr`` is False only (branch-only). Setting True fails closed.
    """

    lock_paths: LockPathConfig
    safety_rules: SafetyRuleConfig
    canary_label: str = DISPATCHER_CANARY_LABEL
    allowed_repositories: frozenset[str] = CANARY_ALLOWED_REPOSITORIES
    permitted_paths: frozenset[str] = CANARY_PERMITTED_PATHS
    canary_execution_enabled: bool = False
    verified_noninteractive: bool = False
    open_draft_pr: bool = False
    runner_identity: str = "codex-runner"
    publisher_identity: str = "codex-publisher"
    daemon: bool = False
    unattended_polling: bool = False

    def __post_init__(self) -> None:
        reject_forbidden_profile_fields(f.name for f in fields(self))
        object.__setattr__(self, "lock_paths", _require_canary_lock_paths(self.lock_paths))
        object.__setattr__(
            self, "safety_rules", _require_nonempty_safety_rules(self.safety_rules)
        )
        object.__setattr__(self, "canary_label", _require_canary_label(self.canary_label))
        object.__setattr__(
            self,
            "allowed_repositories",
            _require_exact_allowlist(self.allowed_repositories),
        )
        object.__setattr__(
            self,
            "permitted_paths",
            _require_exact_permitted_paths(self.permitted_paths),
        )
        object.__setattr__(
            self,
            "canary_execution_enabled",
            _require_off_or_bool(
                self.canary_execution_enabled,
                label="canary_execution_enabled",
                allow_true=True,
            ),
        )
        object.__setattr__(
            self,
            "verified_noninteractive",
            _require_off_or_bool(
                self.verified_noninteractive,
                label="verified_noninteractive",
                allow_true=True,
            ),
        )
        object.__setattr__(
            self,
            "open_draft_pr",
            _require_off_or_bool(
                self.open_draft_pr, label="open_draft_pr", allow_true=False
            ),
        )
        object.__setattr__(
            self,
            "daemon",
            _require_off_or_bool(self.daemon, label="daemon", allow_true=False),
        )
        object.__setattr__(
            self,
            "unattended_polling",
            _require_off_or_bool(
                self.unattended_polling, label="unattended_polling", allow_true=False
            ),
        )
        object.__setattr__(
            self,
            "runner_identity",
            _require_identity(self.runner_identity, label="runner_identity"),
        )
        object.__setattr__(
            self,
            "publisher_identity",
            _require_identity(self.publisher_identity, label="publisher_identity"),
        )


def default_canary_profile(
    *,
    lock_paths: LockPathConfig,
    safety_rules: SafetyRuleConfig,
    canary_label: str = DISPATCHER_CANARY_LABEL,
    runner_identity: str = "codex-runner",
    publisher_identity: str = "codex-publisher",
) -> CanaryProfile:
    """Gates-off constructor. Does not read or flip environment variables."""
    return CanaryProfile(
        lock_paths=lock_paths,
        safety_rules=safety_rules,
        canary_label=canary_label,
        runner_identity=runner_identity,
        publisher_identity=publisher_identity,
    )


def build_canary_profile(**kwargs: object) -> CanaryProfile:
    """Injectable constructor. Rejects token-like kwargs before construction."""
    reject_forbidden_profile_fields(kwargs)
    allowed = {f.name for f in fields(CanaryProfile)}
    unknown = set(kwargs) - allowed
    if unknown:
        raise CanaryProfileError(f"unknown CanaryProfile fields: {sorted(unknown)}")
    typed: dict[str, object] = dict(kwargs)
    lock_paths = typed.get("lock_paths")
    safety_rules = typed.get("safety_rules")
    if lock_paths is None:
        raise CanaryProfileError("lock_paths is required")
    if safety_rules is None:
        raise CanaryProfileError("safety_rules is required")
    return CanaryProfile(**typed)  # type: ignore[arg-type]


def require_activation_gates_satisfied(profile: CanaryProfile) -> None:
    """Refuse unless enablement flags are all true **and** branch-only.

    Checker only. Does **not** flip ``CODEX_DISPATCHER_DRY_RUN`` or any other
    environment variable. Does not start a daemon or poll.
    """
    if not isinstance(profile, CanaryProfile):
        raise CanaryGateError("activation checker requires a CanaryProfile")
    if profile.daemon or profile.unattended_polling:
        raise CanaryGateError("daemon/unattended polling refused (W8 one-shot)")
    if profile.open_draft_pr:
        raise CanaryGateError("open_draft_pr must be false (branch-only W10)")
    if not profile.canary_execution_enabled:
        raise CanaryGateError("canary_execution_enabled is false (default off)")
    if not profile.verified_noninteractive:
        raise CanaryGateError("verified_noninteractive is false (default off)")


def require_dispatcher_canary_label_from_issue_metadata(labels: object) -> None:
    """Authorize using GitHub issue label metadata — never ticket JSON.

    *labels* is the issue metadata labels array (names), not a JSON body field.
    """
    if isinstance(labels, (str, bytes, bytearray, Mapping)) or not isinstance(labels, Iterable):
        raise CanaryProfileError(
            "issue label metadata must be a non-scalar iterable of label names"
        )
    names: list[str] = []
    for item in labels:
        if not isinstance(item, str):
            raise CanaryProfileError("issue label metadata entries must be strings")
        names.append(item)
    if DISPATCHER_CANARY_LABEL not in names:
        raise CanaryProfileError(
            "dispatcher-canary label missing from GitHub issue metadata (A5); "
            "do not trust a ticket JSON label field"
        )


# Self-check: a token-like field on the dataclass is a construction bug.
reject_forbidden_profile_fields(f.name for f in fields(CanaryProfile))
