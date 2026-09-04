"""AST dependency firewall for codex_dispatcher/.

Fails closed if any module under codex_dispatcher imports a forbidden root:
copymoney, measurement, agents, execution, trading.
"""

from __future__ import annotations

import ast
import tempfile
import textwrap
import unittest
from pathlib import Path


FORBIDDEN_ROOTS = frozenset(
    {
        "copymoney",
        "measurement",
        "agents",
        "execution",
        "trading",
    }
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "codex_dispatcher"


def _root_name(dotted: str | None) -> str | None:
    if not dotted:
        return None
    return dotted.split(".", 1)[0]


def forbidden_imports_in_source(source: str, *, filename: str = "<memory>") -> list[str]:
    """Return human-readable hits for forbidden import roots in *source*."""
    tree = ast.parse(source, filename=filename)
    hits: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _root_name(alias.name)
                if root in FORBIDDEN_ROOTS:
                    hits.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            # Relative imports (level > 0) stay inside the package and are allowed.
            if node.level and node.level > 0:
                continue
            root = _root_name(node.module)
            if root in FORBIDDEN_ROOTS:
                module = node.module or ""
                names = ", ".join(alias.name for alias in node.names)
                hits.append(f"from {module} import {names}")

    return hits


def scan_package(package_root: Path) -> list[str]:
    """Scan every .py file under *package_root*; return violation strings."""
    violations: list[str] = []
    for path in sorted(package_root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for hit in forbidden_imports_in_source(source, filename=str(path)):
            violations.append(f"{path.relative_to(package_root.parent)}: {hit}")
    return violations


class DependencyFirewallTests(unittest.TestCase):
    def test_package_has_no_forbidden_imports(self) -> None:
        self.assertTrue(PACKAGE_ROOT.is_dir(), f"missing package root: {PACKAGE_ROOT}")
        violations = scan_package(PACKAGE_ROOT)
        self.assertEqual(
            violations,
            [],
            "forbidden import roots detected:\n" + "\n".join(violations),
        )

    def test_firewall_fails_closed_on_forbidden_import(self) -> None:
        planted = textwrap.dedent(
            """\
            import measurement.paired_shadow
            from agents.base_agent import BaseAgent
            from copymoney.orchestration import worker
            """
        )
        hits = forbidden_imports_in_source(planted, filename="planted.py")
        self.assertGreaterEqual(len(hits), 3)
        joined = "\n".join(hits)
        for root in ("measurement", "agents", "copymoney"):
            self.assertIn(root, joined)

    def test_firewall_allows_stdlib_and_relative(self) -> None:
        clean = textwrap.dedent(
            """\
            import ast
            from pathlib import Path
            from . import schema
            """
        )
        self.assertEqual(forbidden_imports_in_source(clean), [])

    def test_scan_package_detects_planted_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "codex_dispatcher"
            root.mkdir()
            (root / "__init__.py").write_text('"""inert"""\n', encoding="utf-8")
            (root / "bad.py").write_text("import trading\n", encoding="utf-8")
            violations = scan_package(root)
            self.assertTrue(any("trading" in item for item in violations))


if __name__ == "__main__":
    unittest.main()
