"""GET-only GitHub source: allowlist fail-closed + no mutation surface."""

from __future__ import annotations

import json
import unittest
from io import BytesIO
from unittest import mock

from codex_dispatcher.allowlist import AllowlistError
from codex_dispatcher.github.source import GitHubIssueSource, _get_json


class GitHubGetOnlyTests(unittest.TestCase):
    def test_allowlist_required(self) -> None:
        with self.assertRaises(AllowlistError) as ctx:
            GitHubIssueSource("acme/demo", token=None)
        self.assertIn("allowlist", str(ctx.exception).lower())

    def test_empty_allowlist_rejected(self) -> None:
        with self.assertRaises(AllowlistError):
            GitHubIssueSource(
                "acme/demo",
                token=None,
                allowed_repositories=frozenset(),
            )

    def test_repo_must_be_allowlisted(self) -> None:
        with self.assertRaises(AllowlistError):
            GitHubIssueSource(
                "acme/demo",
                token=None,
                allowed_repositories=frozenset({"other/repo"}),
            )

    def test_no_mutation_methods(self) -> None:
        src = GitHubIssueSource(
            "acme/demo",
            token=None,
            allowed_repositories=frozenset({"acme/demo"}),
        )
        forbidden = {
            "create_issue",
            "update_issue",
            "comment",
            "add_comment",
            "close_issue",
            "open_pull_request",
            "request",
            "post",
            "patch",
            "put",
            "delete",
        }
        for name in forbidden:
            self.assertFalse(hasattr(src, name), name)

    def test_get_json_uses_get_method_only(self) -> None:
        payload = json.dumps({"ok": True}).encode()

        class _Resp(BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with mock.patch("urllib.request.urlopen", return_value=_Resp(payload)) as urlopen:
            with mock.patch("urllib.request.Request") as Request:
                Request.return_value = mock.Mock()
                _get_json("https://api.github.com/repos/acme/demo/issues/1", {"Accept": "x"})
                kwargs = Request.call_args.kwargs
                self.assertEqual(kwargs.get("method"), "GET")
                # No method escape hatch parameter on _get_json beyond hard-coded GET.
                self.assertNotIn("method", _get_json.__code__.co_varnames[2:])

    def test_get_json_signature_has_no_method_param(self) -> None:
        import inspect

        params = inspect.signature(_get_json).parameters
        self.assertNotIn("method", params)


if __name__ == "__main__":
    unittest.main()
