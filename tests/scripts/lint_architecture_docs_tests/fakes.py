from __future__ import annotations

from pathlib import Path

from scripts.lint_architecture_docs import lint_architecture_docs


def write(root: Path, relative_path: str, content: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def valid_adr(*, number: str = "0001", status: str = "accepted") -> str:
    return _valid_record(prefix="ADR", number=number, status=status)


def valid_ui_adr(*, number: str = "0001", status: str = "accepted") -> str:
    return _valid_record(prefix="UI-ADR", number=number, status=status)


def _valid_record(*, prefix: str, number: str, status: str) -> str:
    return f"""# {prefix}-{number}: Test decision

**Статус:** {status}
**Дата:** 2026-09-15
**Связанный design:** [design](../specs/2026-09-15-test-design.md)

## Контекст и архитектурный вопрос
Context.
## Критерии решения
Criteria.
## Рассмотренные варианты
### A. First
Useful.
### B. Second
Useful.
## Решение
Choose A.
## Последствия
### Положительные
Benefit.
### Отрицательные
Cost.
## Проверка решения
Pilot.
## Условия пересмотра
Trigger.
## Enforcement
Check.
"""


def write_valid_tree(root: Path) -> None:
    write(
        root,
        "docs/adr/README.md",
        "| [ADR-0001](0001-test-decision.md) | Test | accepted |\n",
    )
    write(root, "docs/adr/0001-test-decision.md", valid_adr())
    write(
        root,
        "docs/specs/2026-09-15-test-design.md",
        "**ADR assessment:** [ADR-0001](../adr/0001-test-decision.md)\n",
    )


def codes(root: Path) -> set[str]:
    return {
        violation.code
        for violation in lint_architecture_docs(
            root,
            enforce_spec_from="2026-09-15",
        )
    }
