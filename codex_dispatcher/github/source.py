"""GET-only GitHub issue retrieval (no mutation methods, no method escape hatch)."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Set, Mapping
from dataclasses import dataclass
from typing import Any


GITHUB_API_BASE = "https://api.github.com"


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    url: str


def _get_json(url: str, headers: Mapping[str, str], *, timeout: float = 15.0) -> Any:
    """Perform a hard-coded HTTP GET. No method parameter (no escape hatch)."""
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


class GitHubIssueSource:
    """Fetch open issues via GET only.

    Mutation APIs intentionally do not exist. There is no generic
    request(method=...) helper.
    """

    def __init__(
        self,
        repository: str,
        token: str | None,
        *,
        allowed_repositories: Set[str] | None = None,
        api_base: str = GITHUB_API_BASE,
        ready_label: str = "ready-for-agent",
    ) -> None:
        if not re.fullmatch(r"[^/\s]+/[^/\s]+", repository):
            raise ValueError("repository must be owner/name")
        if allowed_repositories is None:
            raise ValueError(
                "repository allowlist is required (fail closed); "
                "pass allowed_repositories explicitly"
            )
        if repository not in allowed_repositories:
            raise ValueError(f"repository is not in the supplied allowlist: {repository}")
        if api_base != GITHUB_API_BASE:
            raise ValueError(f"api_base must be pinned to {GITHUB_API_BASE}")
        self.repository = repository
        self.token = token
        self.allowed_repositories = frozenset(allowed_repositories)
        self.api_base = api_base
        self.ready_label = ready_label

    def get_issue(self, number: int) -> Issue:
        url = f"{self.api_base}/repos/{self.repository}/issues/{int(number)}"
        row = _get_json(url, self._headers())
        if "pull_request" in row:
            raise ValueError(f"issue {number} is a pull request, not an issue")
        return Issue(
            int(row["number"]),
            str(row["title"]),
            str(row.get("body") or ""),
            str(row["html_url"]),
        )

    def next_ready_issue(self) -> Issue | None:
        query = urllib.parse.urlencode(
            {
                "labels": self.ready_label,
                "state": "open",
                "per_page": "2",
                "sort": "created",
                "direction": "asc",
            }
        )
        url = f"{self.api_base}/repos/{self.repository}/issues?{query}"
        rows = _get_json(url, self._headers())
        for row in rows:
            if "pull_request" not in row:
                return Issue(
                    int(row["number"]),
                    str(row["title"]),
                    str(row.get("body") or ""),
                    str(row["html_url"]),
                )
        return None

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "codex-dispatcher-dry-run",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers
