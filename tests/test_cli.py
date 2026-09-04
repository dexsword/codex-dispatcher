"""CLI dry-run refusal + offline allowlist examples."""

from __future__ import annotations

import json
import os
import tempfile
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

    def test_explicit_allowlist_eligible(self) -> None:
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
        self.assertEqual(result["disposition"], "eligible")

    def test_deny_key_blocks(self) -> None:
        ticket = ROOT / "examples" / "ticket.denied.json"
        result = cli.run(
            [
                "--ticket-file",
                str(ticket),
                "--allowlist",
                "acme/demo",
                "--repository",
                "acme/demo",
                "--deny-key",
                "live_trading",
            ]
        )
        self.assertEqual(result["disposition"], "blocked")

    def test_known_id_duplicate_blocks(self) -> None:
        ticket = ROOT / "examples" / "ticket.valid.json"
        result = cli.run(
            [
                "--ticket-file",
                str(ticket),
                "--allowlist",
                "acme/demo",
                "--repository",
                "acme/demo",
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
                ]
            )
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
