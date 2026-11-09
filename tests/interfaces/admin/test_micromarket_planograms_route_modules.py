from __future__ import annotations

from pathlib import Path

_ROUTES = Path("src/interfaces/admin/routes")
_MODULES = (
    "micromarket_planograms.py",
    "micromarket_planograms_list.py",
    "micromarket_planograms_workspace.py",
    "micromarket_planograms_orders.py",
)
_SOFT_BUDGET = 350


def _physical_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_planograms_list_modules_exist_within_soft_budget() -> None:
    # happy: четыре модуля списка, каждый в бюджете 350 physical lines
    for name in _MODULES:
        path = _ROUTES / name
        assert path.is_file(), name
        assert _physical_lines(path) <= _SOFT_BUDGET, (name, _physical_lines(path))


def test_planograms_facade_reexports_workspace_and_live_need() -> None:
    # happy: соседи и тесты продолжают импортировать два имени с фасада
    from src.interfaces.admin.routes.micromarket_planograms import (
        _live_need_machine,
        _render_fridge_workspace,
    )
    from src.interfaces.admin.routes.micromarket_planograms_list import (
        _live_need_machine as list_live_need,
    )
    from src.interfaces.admin.routes.micromarket_planograms_workspace import (
        _render_fridge_workspace as workspace_render,
    )

    assert _render_fridge_workspace is workspace_render
    assert _live_need_machine is list_live_need
