"""Smoke: package and planned seam stubs import cleanly."""

from __future__ import annotations

import importlib
import unittest


SEAM_MODULES = (
    "codex_dispatcher",
    "codex_dispatcher.allowlist",
    "codex_dispatcher.github",
    "codex_dispatcher.lock",
    "codex_dispatcher.ledger",
    "codex_dispatcher.safety",
    "codex_dispatcher.adapter",
    "codex_dispatcher.worker",
    "codex_dispatcher.schema",
)


class ImportSmokeTests(unittest.TestCase):
    def test_seam_modules_import(self) -> None:
        for name in SEAM_MODULES:
            with self.subTest(module=name):
                module = importlib.import_module(name)
                self.assertIsNotNone(module)

    def test_package_version(self) -> None:
        import codex_dispatcher

        self.assertEqual(codex_dispatcher.__version__, "0.3.0")


if __name__ == "__main__":
    unittest.main()
