"""Frozen DexTech canary profile (Task F2) + staging/publisher (Task F3).

Gates default off. Staging → validate → trusted publisher. No Codex
invoke (F4). No full website SafetyRuleConfig fixtures (F5).
OPS1 provisioning is not F2/F3.

Assess (later) must authorize the ``dispatcher-canary`` label from GitHub
issue metadata, never from a ticket JSON ``label`` field (rev3 A5).

F3: ``require_canary_branch_ref`` immediately before every
commit/publish/push. Hard-coded non-force argv. No ``shell=True``.
"""

from __future__ import annotations

from codex_dispatcher.canary.audit import AuditError, AuditStub, write_audit_stub
from codex_dispatcher.canary.branch import (
    CANARY_REF_PREFIX,
    CanaryApiError,
    CanaryBranchError,
    refuse_open_draft_pr,
    require_canary_branch_ref,
)
from codex_dispatcher.canary.profile import (
    CANARY_ALLOWED_REPOSITORIES,
    CANARY_PERMITTED_PATH,
    CANARY_PERMITTED_PATHS,
    DISPATCHER_CANARY_LABEL,
    CanaryGateError,
    CanaryProfile,
    CanaryProfileError,
    build_canary_profile,
    default_canary_profile,
    minimal_canary_safety_rule_config,
    require_activation_gates_satisfied,
    require_dispatcher_canary_label_from_issue_metadata,
)
from codex_dispatcher.canary.publisher import (
    GIT_BIN,
    HOOKS_PATH,
    HandoffError,
    HandoffResult,
    PublisherConfig,
    PublisherError,
    PushPlan,
    build_non_force_push_argv,
    commit_canary,
    handoff_to_trusted_worktree,
    hooks_disabled,
    publish_canary,
    push_canary,
    refuse_force_push,
    require_canonical_remote,
    sanitize_publisher_git_env,
)
from codex_dispatcher.canary.staging import (
    PERMITTED_RELATIVE_PATH,
    PreparedStaging,
    StagingConfig,
    StagingError,
    StagingTreeEnumerator,
    StagingValidation,
    build_staging_config,
    prepare_staging,
    staging_isolated_env,
    validate,
    validate_staging,
)
from codex_dispatcher.canary.status import (
    STATUS_SCHEMA_KEYS,
    STATUS_SCHEMA_VERSION,
    STATUS_SUCCESS,
    StatusSchemaError,
    validate_status_document,
    validate_status_file,
)

__all__ = [
    "CANARY_ALLOWED_REPOSITORIES",
    "CANARY_PERMITTED_PATH",
    "CANARY_PERMITTED_PATHS",
    "CANARY_REF_PREFIX",
    "DISPATCHER_CANARY_LABEL",
    "GIT_BIN",
    "HOOKS_PATH",
    "PERMITTED_RELATIVE_PATH",
    "STATUS_SCHEMA_KEYS",
    "STATUS_SCHEMA_VERSION",
    "STATUS_SUCCESS",
    "AuditError",
    "AuditStub",
    "CanaryApiError",
    "CanaryBranchError",
    "CanaryGateError",
    "CanaryProfile",
    "CanaryProfileError",
    "HandoffError",
    "HandoffResult",
    "PreparedStaging",
    "PublisherConfig",
    "PublisherError",
    "PushPlan",
    "StagingConfig",
    "StagingError",
    "StagingTreeEnumerator",
    "StagingValidation",
    "StatusSchemaError",
    "build_canary_profile",
    "build_non_force_push_argv",
    "build_staging_config",
    "commit_canary",
    "default_canary_profile",
    "handoff_to_trusted_worktree",
    "hooks_disabled",
    "minimal_canary_safety_rule_config",
    "prepare_staging",
    "publish_canary",
    "push_canary",
    "refuse_force_push",
    "refuse_open_draft_pr",
    "require_activation_gates_satisfied",
    "require_canary_branch_ref",
    "require_canonical_remote",
    "require_dispatcher_canary_label_from_issue_metadata",
    "sanitize_publisher_git_env",
    "staging_isolated_env",
    "validate",
    "validate_staging",
    "validate_status_document",
    "validate_status_file",
    "write_audit_stub",
]
