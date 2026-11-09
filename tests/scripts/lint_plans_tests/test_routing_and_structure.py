from __future__ import annotations

from pathlib import Path

from scripts.lint_plans import lint_plan_paths

from .fakes import _codes, _valid_fragment, _valid_single_plan, _write


def test_valid_single_plan_passes(tmp_path: Path) -> None:
    root = tmp_path
    plan = _write(root, "docs/plans/valid.md", _valid_single_plan())

    assert lint_plan_paths(root, paths=(plan,)) == []


def test_missing_routing_gate_fails(tmp_path: Path) -> None:
    root = tmp_path
    plan = _write(
        root,
        "docs/plans/missing-routing.md",
        """# План реализации: Missing

**Спек:** [docs/specs/test-design.md]

## Покрытие спека

| Требование | Задача |
|------------|--------|
| Test | 1 |

## Задача 1: Test

- [ ] **Шаг 1:** test

## Самопроверка

- [ ] checked
""",
    )

    assert "PLN001" in _codes(root, plan)


def test_enforce_from_skips_older_plans(tmp_path: Path) -> None:
    root = tmp_path
    old_plan = _write(root, "docs/plans/2026-07-08-old.md", "# Old plan\n")
    new_plan = _write(root, "docs/plans/2026-07-09-new.md", "# New plan\n")

    violations = lint_plan_paths(root, paths=(old_plan, new_plan), enforce_from="2026-07-09")

    assert {violation.path.name for violation in violations} == {"2026-07-09-new.md"}
    assert {violation.code for violation in violations} >= {"PLN001"}


def test_single_plan_with_hard_trigger_fails(tmp_path: Path) -> None:
    root = tmp_path
    plan = _write(root, "docs/plans/large.md", _valid_single_plan(tasks=9))

    assert "PLN002" in _codes(root, plan)


def test_pack_readme_with_task_fails(tmp_path: Path) -> None:
    root = tmp_path
    readme = _write(
        root,
        "docs/plans/pack/README.md",
        """# Plan pack: Test

## Routing Gate

**Формат плана:** plan pack
**Причина:** hard triggers.

## Фрагменты

| Фрагмент | Scope | Зависит от | Статус | Ревью |
|----------|-------|------------|--------|-------|
| `01-domain.md` | domain | — | ⏳ | — |

## Задача 1: Must not be here
""",
    )

    assert "PLN003" in _codes(root, readme)


def test_fragment_missing_required_pack_fields_fails(tmp_path: Path) -> None:
    root = tmp_path
    fragment = _write(
        root,
        "docs/plans/pack/01-domain.md",
        """# План-фрагмент 01: Test

**Спек:** [docs/specs/test-design.md]

## Routing Gate

**Формат плана:** plan pack

## Покрытие спека

| Требование | Задача |
|------------|--------|
| Test | 1 |

## Задача 1: Test

- [ ] **Шаг 1:** test

## Самопроверка фрагмента

- [ ] checked
""",
    )

    assert "PLN004" in _codes(root, fragment)


def test_fragment_too_wide_fails_without_exception(tmp_path: Path) -> None:
    root = tmp_path
    task_blocks = "\n\n".join(f"## Задача {index}: Test\n" for index in range(1, 10))
    fragment = _write(
        root,
        "docs/plans/pack/01-domain.md",
        _valid_fragment().replace("## Задача 1: Test task", task_blocks),
    )

    assert "PLN005" in _codes(root, fragment)


def test_post_review_success_with_warning_marker_fails(tmp_path: Path) -> None:
    root = tmp_path
    plan = _write(
        root,
        "docs/plans/review-warning.md",
        _valid_single_plan()
        + """
**Статус post-review:** ✅ все post-review задачи закрыты

> Ревью: ⚠️ 2026-07-09 · working tree
""",
    )

    assert "PLN006" in _codes(root, plan)


def test_pack_readme_fragment_success_with_open_fragment_fails(tmp_path: Path) -> None:
    root = tmp_path
    readme = _write(
        root,
        "docs/plans/pack/README.md",
        """# Plan pack: Test

## Routing Gate

**Формат плана:** plan pack
**Причина:** hard triggers.

## Фрагменты

| Фрагмент | Scope | Зависит от | Статус | Ревью |
|----------|-------|------------|--------|-------|
| `01-domain.md` | domain | — | ✅ | ✅ |

## Cross-Pack Final Gate

- [ ] all checked
""",
    )
    _write(root, "docs/plans/pack/01-domain.md", _valid_fragment())

    assert "PLN007" in _codes(root, readme)


def test_pln007_review_check_with_open_checkbox_does_not_fail(tmp_path: Path) -> None:
    root = tmp_path
    readme = _write(
        root,
        "docs/plans/pack/README.md",
        """# Plan pack: Test

## Routing Gate

**Формат плана:** plan pack
**Причина:** hard triggers.

## Фрагменты

| Фрагмент | Scope | Зависит от | Статус | Ревью |
|----------|-------|------------|--------|-------|
| `01-domain.md` | domain | — | ⏳ | ✅ |

## Cross-Pack Final Gate

- [ ] all checked
""",
    )
    _write(root, "docs/plans/pack/01-domain.md", _valid_fragment())

    assert "PLN007" not in _codes(root, readme)


def test_missing_self_check_and_spec_coverage_fail(tmp_path: Path) -> None:
    root = tmp_path
    plan = _write(
        root,
        "docs/plans/no-checks.md",
        """# План реализации: No checks

**Спек:** [docs/specs/test-design.md]

## Routing Gate

**Формат плана:** single plan
**Причина:** small.

## Задача 1: Test

- [ ] **Шаг 1:** test
""",
    )

    assert {"PLN008", "PLN009"} <= _codes(root, plan)


def test_placeholders_fail(tmp_path: Path) -> None:
    root = tmp_path
    plan = _write(
        root,
        "docs/plans/placeholders.md",
        _valid_single_plan()
        + """
## Примечания

TODO: добавить тесты для edge cases
""",
    )

    assert "PLN010" in _codes(root, plan)
