from __future__ import annotations

import re
from pathlib import Path


def test_architecture_mentions_product_identity_edge() -> None:
    """Context-map edges live in architecture (AGENTS router no longer lists them)."""
    architecture = Path("docs/architecture.md").read_text(encoding="utf-8")
    edge = next(
        line for line in architecture.splitlines() if "`inventory_reconciliation` →" in line
    )
    assert "`product_identity`" in edge
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    forbidden = pyproject.split('name = "Application package internals are private"', 1)[1]
    forbidden = forbidden.split("[[tool.importlinter.contracts]]", 1)[0]
    source = forbidden.split("source_modules = [", 1)[1].split("]", 1)[0]
    names = re.findall(r'"src\.application\.([a-z0-9_]+)"', source)
    assert "product_identity" in names
    for name in ("product_identity", "visit_photo_review", "visit_photo_grouping"):
        assert name in names
    assert "source_modules" in architecture or "pyproject.toml" in architecture
