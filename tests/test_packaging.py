"""Zero runtime dependencies + ledger seam is read-only."""

from __future__ import annotations

import ast
import tomllib
import unittest
from pathlib import Path

import codex_dispatcher.ledger as ledger_mod


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_zero_runtime_dependencies(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(data["project"].get("dependencies") or [], [])

    def test_ledger_module_has_no_append_or_write_apis(self) -> None:
        source = (ROOT / "codex_dispatcher" / "ledger" / "__init__.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for banned in ("append", "write", "mutate", "open", "unlink"):
            self.assertNotIn(banned, defined)
        self.assertTrue(hasattr(ledger_mod, "DuplicateChecker"))
        self.assertFalse(hasattr(ledger_mod, "append"))
        self.assertFalse(hasattr(ledger_mod, "append_event"))


class LockStubTests(unittest.TestCase):
    def test_lock_package_does_not_define_process_lock(self) -> None:
        import codex_dispatcher.lock as lock_mod

        self.assertFalse(hasattr(lock_mod, "ProcessLock"))
        self.assertFalse(hasattr(lock_mod, "GLOBAL_AGENT_LOCK_PATH"))


if __name__ == "__main__":
    unittest.main()
