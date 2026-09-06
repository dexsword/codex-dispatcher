"""Exact ``canary/DISPATCHER_STATUS.md`` schema (rev3 §4.10 / Astra A6)."""

from __future__ import annotations

import re

STATUS_HEADING = "# DISPATCHER_STATUS"
STATUS_SCHEMA_VERSION = 1
STATUS_SUCCESS = "canary_ok"
STATUS_SCHEMA_KEYS = (
    "schema_version",
    "task_id",
    "job_id",
    "dispatcher_sha",
    "timestamp_utc",
    "status",
)
MAX_STATUS_BYTES = 8192

_TASK_OR_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DISPATCHER_SHA = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_TIMESTAMP_UTC = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_KV_LINE = re.compile(r"^- ([a-z_]+): (.+)$")
_HTML = re.compile(r"</?[A-Za-z!?][^>]*>")
_CREDENTIAL_URL = re.compile(r"://[^/\s]*:[^/\s]*@")
_BASE64_CANDIDATE = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{48,}={0,2}(?![A-Za-z0-9+/])")

# Defense-in-depth credential substrings (schema grammar is primary).
_CREDENTIAL_NEEDLES = (
    "begin private key",
    "begin rsa private key",
    "begin openssh private key",
    "begin certificate",
    "github_token",
    "ghp_",
    "gho_",
    "github_pat_",
    "aws_secret",
    "akia",
    "password=",
    "api_key",
    "secret_key",
    "-----begin",
)


class StatusSchemaError(ValueError):
    """Status file does not match the exact §4.10 schema."""


def validate_status_document(text: object) -> dict[str, str]:
    """F3 name for the F2 §4.10 validator (byte-identical rules)."""
    return validate_status_file(text)


def validate_status_file(text: object) -> dict[str, str]:
    """Accept only the frozen key-value document. Reject extra/missing/fences."""
    if not isinstance(text, str):
        raise StatusSchemaError("status file must be a UTF-8 string")
    raw = text.encode("utf-8")
    if len(raw) > MAX_STATUS_BYTES:
        raise StatusSchemaError("status file exceeds 8 KiB UTF-8")
    if "\x00" in text:
        raise StatusSchemaError("status file must not contain NUL")
    if "\r" in text:
        raise StatusSchemaError("status file must use LF newlines only")
    if any(ord(c) < 32 and c != "\n" for c in text) or "\x7f" in text:
        raise StatusSchemaError("status file must not contain control characters")
    if "```" in text or "~~~" in text:
        raise StatusSchemaError("code fences are not permitted")
    if _HTML.search(text):
        raise StatusSchemaError("HTML is not permitted")
    lowered = text.lower()
    for needle in _CREDENTIAL_NEEDLES:
        if needle in lowered:
            raise StatusSchemaError("credential-like content is not permitted")
    if _CREDENTIAL_URL.search(text):
        raise StatusSchemaError("URLs with embedded credentials are not permitted")
    if _contains_encoded_blob(text):
        raise StatusSchemaError("encoded blobs are not permitted")

    if not text.endswith("\n"):
        raise StatusSchemaError("status file must end with a single trailing newline")
    lines = text.split("\n")
    # split leaves a final empty from the trailing newline
    if lines and lines[-1] == "":
        lines = lines[:-1]
    expected_len = 2 + len(STATUS_SCHEMA_KEYS)  # heading + blank + keys
    if len(lines) != expected_len:
        raise StatusSchemaError(
            f"status file must have exactly {expected_len} lines "
            f"(heading, blank, {len(STATUS_SCHEMA_KEYS)} keys); got {len(lines)}"
        )
    if lines[0] != STATUS_HEADING:
        raise StatusSchemaError("status file heading must be exactly '# DISPATCHER_STATUS'")
    if lines[1] != "":
        raise StatusSchemaError("status file must have exactly one blank line after the heading")

    parsed: dict[str, str] = {}
    for index, key in enumerate(STATUS_SCHEMA_KEYS):
        line = lines[2 + index]
        match = _KV_LINE.fullmatch(line)
        if match is None:
            raise StatusSchemaError(f"status line does not match schema grammar: {line!r}")
        found_key, value = match.group(1), match.group(2)
        if found_key != key:
            raise StatusSchemaError(
                f"status keys must appear once each in order; expected {key!r}, got {found_key!r}"
            )
        if key in parsed:
            raise StatusSchemaError(f"duplicate status key: {key}")
        if value != value.strip() or " " in value:
            # tight values: no surrounding or internal whitespace
            raise StatusSchemaError(f"status value for {key} must not contain whitespace")
        parsed[key] = value
        _validate_value(key, value)

    return parsed


def _contains_encoded_blob(text: str) -> bool:
    """True for long base64-like tokens that are not lowercase/uppercase hex."""
    for match in _BASE64_CANDIDATE.finditer(text):
        token = match.group(0).rstrip("=")
        if re.fullmatch(r"[0-9a-f]+", token) or re.fullmatch(r"[0-9A-F]+", token):
            continue
        return True
    return False


def _validate_value(key: str, value: str) -> None:
    if key == "schema_version":
        if value != str(STATUS_SCHEMA_VERSION):
            raise StatusSchemaError(
                f"schema_version must be the integer literal {STATUS_SCHEMA_VERSION}"
            )
        return
    if key == "status":
        if value != STATUS_SUCCESS:
            raise StatusSchemaError(f"status must be exactly {STATUS_SUCCESS!r}")
        return
    if key in {"task_id", "job_id"}:
        if _TASK_OR_JOB_ID.fullmatch(value) is None:
            raise StatusSchemaError(f"{key} does not match the locked identifier grammar")
        return
    if key == "dispatcher_sha":
        if _DISPATCHER_SHA.fullmatch(value) is None:
            raise StatusSchemaError("dispatcher_sha must be lowercase hex (40 or 64 chars)")
        return
    if key == "timestamp_utc":
        if _TIMESTAMP_UTC.fullmatch(value) is None:
            raise StatusSchemaError("timestamp_utc must be ISO-8601 UTC ending in Z")
        return
    raise StatusSchemaError(f"unexpected status key: {key}")
