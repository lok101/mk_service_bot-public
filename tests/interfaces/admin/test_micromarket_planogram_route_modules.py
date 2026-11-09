from __future__ import annotations

from pathlib import Path

_ROUTES = Path("src/interfaces/admin/routes")
_MODULES = (
    "micromarket_planogram.py",
    "micromarket_planogram_parse.py",
    "micromarket_planogram_rows.py",
    "micromarket_planogram_access.py",
    "micromarket_planogram_context.py",
    "micromarket_planogram_mutations.py",
    "micromarket_planogram_publish.py",
)
_SOFT_BUDGET = 350


def _physical_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _editor_sources() -> list[Path]:
    facade = _ROUTES / "micromarket_planogram.py"
    siblings = sorted(_ROUTES.glob("micromarket_planogram_*.py"))
    return [facade, *siblings]


def test_planogram_editor_modules_exist_within_soft_budget() -> None:
    # happy: семь модулей редактора, каждый в бюджете 350 physical lines
    for name in _MODULES:
        path = _ROUTES / name
        assert path.is_file(), name
        assert _physical_lines(path) <= _SOFT_BUDGET, (name, _physical_lines(path))


def test_planogram_facade_reexports_parse_access_and_tab_context() -> None:
    # happy: список и загрузка продолжают импортировать три имени с фасада
    from src.interfaces.admin.routes.micromarket_planogram import (
        _parse_planogram_form,
        _path_allowed_codes,
        _planogram_tab_context,
    )
    from src.interfaces.admin.routes.micromarket_planogram_access import (
        _path_allowed_codes as access_codes,
    )
    from src.interfaces.admin.routes.micromarket_planogram_context import (
        _planogram_tab_context as tab_context,
    )
    from src.interfaces.admin.routes.micromarket_planogram_parse import (
        _parse_planogram_form as parse_form,
    )

    assert _parse_planogram_form is parse_form
    assert _path_allowed_codes is access_codes
    assert _planogram_tab_context is tab_context


def test_planogram_editor_sources_omit_product_base_template() -> None:
    # edge: запрет GetProductBaseTemplate на фасаде и на вынесенных модулях
    sources = _editor_sources()
    assert len(sources) >= 2
    for path in sources:
        assert path.is_file()
        assert "GetProductBaseTemplate" not in path.read_text(encoding="utf-8")
