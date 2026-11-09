from __future__ import annotations

from pathlib import Path

from .fakes import _codes, _valid_fragment, _valid_single_plan, _write


def test_fragment_touching_src_without_lint_imports_gate_fails(tmp_path: Path) -> None:
    root = tmp_path
    fragment = _write(
        root,
        "docs/plans/pack/01-domain.md",
        _valid_fragment().replace("- [ ] `uv run lint-imports --no-cache` → 0 broken\n", ""),
    )

    assert "PLN011" in _codes(root, fragment)


def test_fragment_with_lint_imports_gate_passes(tmp_path: Path) -> None:
    root = tmp_path
    fragment = _write(root, "docs/plans/pack/01-domain.md", _valid_fragment())

    assert "PLN011" not in _codes(root, fragment)


def test_docs_only_plan_does_not_require_lint_imports_gate(tmp_path: Path) -> None:
    root = tmp_path
    plan = _write(root, "docs/plans/docs-only.md", _valid_single_plan())

    assert "PLN011" not in _codes(root, plan)


def test_single_plan_touching_src_without_lint_imports_gate_fails(tmp_path: Path) -> None:
    root = tmp_path
    plan = _write(
        root,
        "docs/plans/src-plan.md",
        _valid_single_plan(extra_files="- `src/application/example/use_cases.py` — role"),
    )

    assert "PLN011" in _codes(root, plan)


def test_lint_imports_gate_not_enforced_for_plans_before_2026_07_15(tmp_path: Path) -> None:
    root = tmp_path
    plan = _write(
        root,
        "docs/plans/2026-07-14-old-plan.md",
        _valid_single_plan(extra_files="- `src/application/example/use_cases.py` — role"),
    )
    fragment = _write(
        root,
        "docs/plans/2026-07-14-old-pack/01-domain.md",
        _valid_fragment().replace("- [ ] `uv run lint-imports --no-cache` → 0 broken\n", ""),
    )

    assert "PLN011" not in _codes(root, plan, fragment)
