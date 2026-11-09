from __future__ import annotations

from pathlib import Path

from scripts.lint_plans import lint_plan_paths


def _write(root: Path, relative_path: str, content: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _codes(root: Path, *paths: Path) -> set[str]:
    return {violation.code for violation in lint_plan_paths(root, paths=paths)}


def _valid_single_plan(*, tasks: int = 1, extra_files: str = "") -> str:
    task_blocks = "\n\n".join(
        f"""## Задача {index}: Test task

**Файлы:**
- Тест: `tests/test_{index}.py`

- [ ] **Шаг 1:** test
"""
        for index in range(1, tasks + 1)
    )
    return f"""# План реализации: Test

**Спек:** [docs/specs/test-design.md]

## Routing Gate

| Критерий | Значение | Решение |
|----------|----------|---------|
| Слои | 1: docs | single plan |

**Формат плана:** single plan
**Причина:** hard/soft triggers не сработали.

## Покрытие спека

| Требование / решение из спека | Задача |
|-------------------------------|--------|
| Test requirement | 1 |

## Карта файлов

**Создать:**
{extra_files}

{task_blocks}

## Самопроверка

- [ ] Test requirement checked
"""


def _valid_fragment() -> str:
    return """# План-фрагмент 01: Test

**Pack:** [README.md](README.md)

**Scope фрагмента:** domain

**Не входит:** infra

**Глобальные инварианты из pack:** invariant one

**Спек:** [docs/specs/test-design.md]

## Покрытие спека

| Требование / решение из спека | Задача |
|-------------------------------|--------|
| Test requirement | 1 |

## Карта файлов

**Создать:**
- `src/domain/example.py` — role

## Задача 1: Test task

**Файлы:**
- Создать: `src/domain/example.py`
- Тест: `tests/domain/test_example.py`

- [ ] **Шаг 1:** test

## Проверки качества фрагмента

- [ ] `uv run lint-imports --no-cache` → 0 broken

## Самопроверка фрагмента

- [ ] Scope checked
"""


def _single_plan_dated(_date: str, body: str) -> str:
    return f"""# План реализации: Gate test

**Спек:** [docs/specs/test-design.md]

## Routing Gate

| Критерий | Значение | Решение |
|----------|----------|---------|
| Слои | 1: docs | single plan |

**Формат плана:** single plan
**Причина:** hard/soft triggers не сработали.

## Покрытие спека

| Требование / решение из спека | Задача |
|-------------------------------|--------|
| Gate | 1 |

## Карта файлов

**Создать:**
- `docs/notes.md` — note

{body}

## Самопроверка

- [ ] checked
"""


def _pack_readme(
    *,
    pack_dir_date: str,
    fragment_rows: str,
    invariant_rows: str,
) -> str:
    del pack_dir_date  # date comes from pack directory name in path
    return f"""# Plan pack: Gates

## Routing Gate

**Формат плана:** plan pack
**Причина:** test.

## Invariant Register

| Инвариант | Фрагмент | Проверка |
|-----------|----------|----------|
{invariant_rows}

## Фрагменты

| Фрагмент | Scope | Зависит от | Статус | Ревью |
|----------|-------|------------|--------|-------|
{fragment_rows}

## Cross-Pack Final Gate

- [ ] done
"""
