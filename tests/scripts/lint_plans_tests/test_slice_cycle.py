from __future__ import annotations

from pathlib import Path

from .fakes import _codes, _pack_readme, _valid_fragment, _write


def _with_slice_marker(body: str) -> str:
    return body.replace(
        "# Plan pack: Gates\n",
        "# Plan pack: Gates\n\n**Цикл:** slice\n",
        1,
    )


def test_slice_cycle_missing_fragment_register_row_passes(tmp_path: Path) -> None:
    root = tmp_path
    body = _with_slice_marker(
        _pack_readme(
            pack_dir_date="2026-09-30",
            fragment_rows="| `01-later.md` | later | — | не написан | — |",
            invariant_rows="| pending slice | `01-later.md` | `test_slice_pending` |",
        )
    )
    readme = _write(root, "docs/plans/2026-09-30-slice-pack/README.md", body)
    assert _codes(root, readme) == set()


def test_pack_without_slice_marker_missing_fragment_register_is_pln013(tmp_path: Path) -> None:
    root = tmp_path
    body = _pack_readme(
        pack_dir_date="2026-09-30",
        fragment_rows="| `01-later.md` | later | — | не написан | — |",
        invariant_rows="| pending slice | `01-later.md` | `test_slice_pending` |",
    )
    readme = _write(root, "docs/plans/2026-09-30-plain-pack/README.md", body)
    assert "PLN013" in _codes(root, readme)


def test_slice_cycle_present_fragment_without_test_id_is_pln013(tmp_path: Path) -> None:
    root = tmp_path
    body = _with_slice_marker(
        _pack_readme(
            pack_dir_date="2026-09-30",
            fragment_rows="| `01-later.md` | later | — | ⏳ | — |",
            invariant_rows="| written slice | `01-later.md` | `test_slice_written` |",
        )
    )
    readme = _write(root, "docs/plans/2026-09-30-slice-written/README.md", body)
    _write(root, "docs/plans/2026-09-30-slice-written/01-later.md", _valid_fragment())
    assert "PLN013" in _codes(root, readme)


def test_slice_cycle_present_fragment_with_test_id_passes(tmp_path: Path) -> None:
    root = tmp_path
    body = _with_slice_marker(
        _pack_readme(
            pack_dir_date="2026-09-30",
            fragment_rows="| `01-later.md` | later | — | ⏳ | — |",
            invariant_rows="| written slice | `01-later.md` | `test_slice_written` |",
        )
    )
    readme = _write(root, "docs/plans/2026-09-30-slice-ok/README.md", body)
    _write(
        root,
        "docs/plans/2026-09-30-slice-ok/01-later.md",
        _valid_fragment() + "\n`test_slice_written`\n",
    )
    assert "PLN013" not in _codes(root, readme)


def test_slice_contour_single_plan_without_tasks_skips_finished_plan_rules(
    tmp_path: Path,
) -> None:
    root = tmp_path
    body = """# План реализации: Contour

**Цикл:** slice

**Нарезка:** ждёт

**Спек:** [docs/specs/2026-09-30-plan-slice-cycle-design.md]

## Routing Gate

| Критерий | Значение | Решение |
|----------|----------|---------|
| Слои | 1: docs | single plan |

**Формат плана:** single plan
**Причина:** контур до задач.

## Контур

Карта файлов, исход линтера и имена будущих задач. Заголовка задачи нет.
"""
    path = _write(root, "docs/plans/2026-09-30-slice-contour.md", body)
    assert _codes(root, path) == set()
