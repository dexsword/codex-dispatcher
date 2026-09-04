"""Unambiguous JSON-object ticket extraction from issue bodies."""

from __future__ import annotations

import json
import re
from typing import Any

from codex_dispatcher.schema import require_ticket_object


def extract_ticket(body: str) -> dict[str, Any]:
    """Extract exactly one JSON object ticket from *body*.

    After success, the mapping is opaque to the dispatcher: eligibility is
    decided only by injected validators/policies, never by inspecting product
    fields here.
    """
    stripped = body.strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as raw_error:
        fences = list(re.finditer(r"```(?:json)?\s*(.*?)\s*```", body, re.S | re.I))
        if len(fences) != 1:
            raise ValueError(
                "issue body must contain exactly one unambiguous JSON ticket"
            ) from raw_error
        outside = body[: fences[0].start()] + body[fences[0].end() :]
        if "{" in outside or "}" in outside or "```" in outside:
            raise ValueError(
                "issue body contains ambiguous content outside the JSON ticket"
            )
        try:
            value = json.loads(fences[0].group(1))
        except json.JSONDecodeError as exc:
            raise ValueError(f"fenced ticket is malformed JSON: {exc}") from exc
    return require_ticket_object(value)
