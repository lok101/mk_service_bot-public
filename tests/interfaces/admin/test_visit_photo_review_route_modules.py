from __future__ import annotations

from pathlib import Path

_ROUTES = Path("src/interfaces/admin/routes")
_MODULES = (
    "visit_photo_review.py",
    "visit_photo_review_support.py",
    "visit_photo_review_filters.py",
    "visit_photo_review_http.py",
    "visit_photo_review_group_editor.py",
    "visit_photo_review_list.py",
    "visit_photo_review_queries.py",
    "visit_photo_review_mutations.py",
    "visit_photo_review_mutation_groups.py",
    "visit_photo_review_mutation_blocks.py",
)
_SOFT_BUDGET = 350


def _physical_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_visit_photo_review_modules_exist_within_soft_budget() -> None:
    # happy: модули среза существуют и каждый ≤350 physical lines
    for name in _MODULES:
        path = _ROUTES / name
        assert path.is_file(), name
        assert _physical_lines(path) <= _SOFT_BUDGET, (name, _physical_lines(path))


def test_visit_photo_review_facade_reexports_editor_helpers() -> None:
    # happy: monkeypatch-поверхность facade сохранена
    from src.interfaces.admin.routes import visit_photo_review as facade
    from src.interfaces.admin.routes.visit_photo_review_group_editor import (
        find_editor_group,
    )
    from src.interfaces.admin.routes.visit_photo_review_http import (
        review_submit_action,
    )

    assert facade._find_editor_group is find_editor_group
    assert facade.review_submit_action is review_submit_action


def test_visit_photo_review_support_barrel_reexports_key_names() -> None:
    # happy: queries/mutations продолжают импортировать имена из support
    from src.interfaces.admin.routes import visit_photo_review_support as support
    from src.interfaces.admin.routes.visit_photo_review_filters import (
        Filters,
        filters_from_request,
    )
    from src.interfaces.admin.routes.visit_photo_review_group_editor import (
        find_editor_group,
    )

    assert support.Filters is Filters
    assert support.filters_from_request is filters_from_request
    assert support.find_editor_group is find_editor_group
    assert support.LOGGER.name == "src.interfaces.admin.routes.visit_photo_review"
    assert support.LIST_PATH == "/admin/visit-photo-review"
