from __future__ import annotations

from pathlib import Path

_ROUTES = Path("src/interfaces/admin/routes")
_MODULES = (
    "master_data_profile.py",
    "master_data_profile_settings.py",
    "master_data_profile_workspace.py",
    "master_data_profile_layout.py",
)
_SOFT_BUDGET = 350


def _physical_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_master_data_profile_modules_exist_within_soft_budget() -> None:
    # happy: четыре модуля, каждый в бюджете 350 physical lines
    for name in _MODULES:
        path = _ROUTES / name
        assert path.is_file(), name
        assert _physical_lines(path) <= _SOFT_BUDGET, (name, _physical_lines(path))


def test_master_data_profile_facade_reexports_workspace_render() -> None:
    # happy: snack_planograms продолжает импортировать render с фасада
    from src.interfaces.admin.routes.master_data_profile import (
        render_machine_planogram_workspace,
    )
    from src.interfaces.admin.routes.master_data_profile_workspace import (
        render_machine_planogram_workspace as workspace_render,
    )

    assert render_machine_planogram_workspace is workspace_render
