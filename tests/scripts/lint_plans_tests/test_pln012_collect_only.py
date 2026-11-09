from __future__ import annotations

from pathlib import Path

from .fakes import _codes, _single_plan_dated, _write


def test_pln012_delete_without_collect_only_fails(tmp_path: Path) -> None:
    root = tmp_path
    plan = _write(
        root,
        "docs/plans/2026-07-20-pln012-fail.md",
        _single_plan_dated(
            "2026-07-20",
            """## Задача 1: Удалить legacy port

**Файлы:**
- Удалить: `src/application/example/ms_inventory_ports.py`

- [ ] **Шаг 1:** delete legacy module
""",
        ),
    )
    assert "PLN012" in _codes(root, plan)


def test_pln012_delete_with_collect_only_passes(tmp_path: Path) -> None:
    root = tmp_path
    plan = _write(
        root,
        "docs/plans/2026-07-20-pln012-ok.md",
        _single_plan_dated(
            "2026-07-20",
            """## Задача 1: Удалить legacy port

**Файлы:**
- Удалить: `src/application/example/ms_inventory_ports.py`

- [ ] **Шаг 1:** delete legacy module

## Проверки качества

- [ ] `uv run pytest --collect-only -q` → no collection errors
""",
        ),
    )
    assert "PLN012" not in _codes(root, plan)


def test_pln012_not_enforced_before_2026_07_20(tmp_path: Path) -> None:
    root = tmp_path
    plan = _write(
        root,
        "docs/plans/2026-07-19-pln012-old.md",
        _single_plan_dated(
            "2026-07-19",
            """## Задача 1: Удалить legacy port

- [ ] **Шаг 1:** delete legacy module `ms_inventory_ports`
""",
        ),
    )
    assert "PLN012" not in _codes(root, plan)
