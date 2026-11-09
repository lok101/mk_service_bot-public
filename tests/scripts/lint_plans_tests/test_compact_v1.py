from __future__ import annotations

from pathlib import Path

from scripts.lint_plans import lint_plan_paths
from scripts.lint_plans_lib.compact import lint_compact_document

from .fakes import _codes, _valid_single_plan, _write

FIXTURES = Path(__file__).parent / "fixtures" / "compact"


def test_compact_happy_passes() -> None:
    doc = (FIXTURES / "happy.md").read_text(encoding="utf-8")
    assert lint_compact_document(doc) == []


def test_compact_missing_risk_pln() -> None:
    doc = (FIXTURES / "missing_risk.md").read_text(encoding="utf-8")
    codes = {v.code for v in lint_compact_document(doc)}
    assert "PLN020" in codes or any(c.startswith("PLN02") for c in codes)


def test_compact_without_marker_returns_empty() -> None:
    doc = "# Legacy plan\n\n## Задача 1: Whatever\n\n- [ ] step\n"
    assert lint_compact_document(doc) == []


def test_inline_marker_mention_does_not_activate_compact() -> None:
    doc = (
        "# План\n\n"
        "Happy fixture содержит `**Формат:** compact-v1` inline.\n\n"
        "## Задача 1: Legacy steps\n\n- [ ] step\n"
    )
    assert lint_compact_document(doc) == []


def test_legacy_plan_without_marker_skips_compact_rules(tmp_path: Path) -> None:
    root = tmp_path
    plan = _write(root, "docs/plans/legacy.md", _valid_single_plan())
    codes = _codes(root, plan)
    assert not any(code.startswith("PLN02") for code in codes)
    assert lint_plan_paths(root, paths=(plan,)) == []


def test_slice_contour_compact_missing_risk_is_pln020(tmp_path: Path) -> None:
    root = tmp_path
    body = """# План реализации: Contour compact

**Цикл:** slice

**Формат:** compact-v1

**Спек:** [docs/specs/test-design.md]

## Routing Gate

| Критерий | Значение | Решение |
|----------|----------|---------|
| Слои | 1: docs | single plan |

**Формат плана:** single plan
**Причина:** контур до задач.

## Outcome 1: Missing risk on slice contour

**Acceptance:** compact rules must run before slice early-return
**Files:** `scripts/lint_plans_lib/structure.py`
**Tests:** happy, edge, error
**Verification:**
- `uv run pytest tests/scripts/lint_plans_tests/test_compact_v1.py -q`

- [ ] Outcome delivered
"""
    plan = _write(root, "docs/plans/2026-10-06-slice-compact.md", body)
    codes = _codes(root, plan)
    assert "PLN020" in codes
