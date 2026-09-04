"""CLI dry-run refusal + offline allowlist / demo-pass-policies."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from codex_dispatcher.worker import cli


ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_missing_allowlist_blocked(self) -> None:
        ticket = ROOT / "examples" / "ticket.valid.json"
        result = cli.run(["--ticket-file", str(ticket)])
        self.assertEqual(result["disposition"], "blocked")

    def test_allowlist_and_repository_without_policies_blocked(self) -> None:
        ticket = ROOT / "examples" / "ticket.valid.json"
        result = cli.run(
            [
                "--ticket-file",
                str(ticket),
                "--allowlist",
                "acme/demo",
                "--repository",
                "acme/demo",
            ]
        )
        self.assertEqual(result["disposition"], "blocked")
        self.assertNotIn("demo_pass_policies", result)

    def test_demo_pass_policies_eligible(self) -> None:
        ticket = ROOT / "examples" / "ticket.valid.json"
        result = cli.run(
            [
                "--ticket-file",
                str(ticket),
                "--allowlist",
                "acme/demo",
                "--repository",
                "acme/demo",
                "--demo-pass-policies",
            ]
        )
        self.assertEqual(result["disposition"], "eligible")
        self.assertTrue(result.get("demo_pass_policies"))
        self.assertEqual(result.get("policy_mode"), "demo-pass-policies")

    def test_deny_key_blocks_with_demo_base(self) -> None:
        ticket = ROOT / "examples" / "ticket.denied.json"
        result = cli.run(
            [
                "--ticket-file",
                str(ticket),
                "--allowlist",
                "acme/demo",
                "--repository",
                "acme/demo",
                "--demo-pass-policies",
                "--deny-key",
                "live_trading",
            ]
        )
        self.assertEqual(result["disposition"], "blocked")

    def test_known_id_duplicate_blocks_with_demo_base(self) -> None:
        ticket = ROOT / "examples" / "ticket.valid.json"
        result = cli.run(
            [
                "--ticket-file",
                str(ticket),
                "--allowlist",
                "acme/demo",
                "--repository",
                "acme/demo",
                "--demo-pass-policies",
                "--known-id",
                "demo-001",
            ]
        )
        self.assertEqual(result["disposition"], "blocked")

    def test_non_dry_run_refused(self) -> None:
        ticket = ROOT / "examples" / "ticket.valid.json"
        with mock.patch.dict(os.environ, {"CODEX_DISPATCHER_DRY_RUN": "false"}, clear=False):
            code = cli.main(
                [
                    "--ticket-file",
                    str(ticket),
                    "--allowlist",
                    "acme/demo",
                    "--repository",
                    "acme/demo",
                    "--demo-pass-policies",
                ]
            )
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
