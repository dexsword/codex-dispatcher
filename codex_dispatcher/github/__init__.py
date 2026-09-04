"""GitHub GET-only issue source + unambiguous ticket extract."""

from codex_dispatcher.github.extract import extract_ticket
from codex_dispatcher.github.source import GITHUB_API_BASE, GitHubIssueSource, Issue

__all__ = [
    "GITHUB_API_BASE",
    "GitHubIssueSource",
    "Issue",
    "extract_ticket",
]
