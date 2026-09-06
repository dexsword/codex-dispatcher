"""Frozen DexTech canary profile (Task F2) — config surface only.

Gates default off. No staging (F3), no Codex invoke (F4), no full website
SafetyRuleConfig fixtures (F5). OPS1 provisioning is not F2.

Assess (later) must authorize the ``dispatcher-canary`` label from GitHub
issue metadata, never from a ticket JSON ``label`` field (rev3 A5).
"""

from __future__ import annotations

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
from codex_dispatcher.canary.status import (
    STATUS_SCHEMA_KEYS,
    STATUS_SCHEMA_VERSION,
    STATUS_SUCCESS,
    StatusSchemaError,
    validate_status_file,
)

__all__ = [
    "CANARY_ALLOWED_REPOSITORIES",
    "CANARY_PERMITTED_PATH",
    "CANARY_PERMITTED_PATHS",
    "CANARY_REF_PREFIX",
    "DISPATCHER_CANARY_LABEL",
    "STATUS_SCHEMA_KEYS",
    "STATUS_SCHEMA_VERSION",
    "STATUS_SUCCESS",
    "CanaryApiError",
    "CanaryBranchError",
    "CanaryGateError",
    "CanaryProfile",
    "CanaryProfileError",
    "StatusSchemaError",
    "build_canary_profile",
    "default_canary_profile",
    "minimal_canary_safety_rule_config",
    "refuse_open_draft_pr",
    "require_activation_gates_satisfied",
    "require_canary_branch_ref",
    "require_dispatcher_canary_label_from_issue_metadata",
    "validate_status_file",
]
