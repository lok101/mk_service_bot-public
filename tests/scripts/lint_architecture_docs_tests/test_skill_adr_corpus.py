from __future__ import annotations

from pathlib import Path

import pytest
from scripts.lint_architecture_docs import lint_architecture_docs

from .fakes import codes, write, write_valid_tree


def _valid_skill_adr(*, number: str = "0007", status: str = "accepted") -> str:
    return f"""# SKILL-ADR-{number}: Message block

**Статус:** {status}
**Дата:** 2026-10-23
**Связанный design:** [design](../specs/2026-10-23-skill-message-blocks-design.md)

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


def test_skill_adr_record_with_index_passes(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(tmp_path, "docs/skill-adr/0007-options.md", _valid_skill_adr())
    write(tmp_path, "docs/skill-adr/README.md", "(0007-options.md)\n")

    assert lint_architecture_docs(tmp_path, enforce_spec_from="2026-09-15") == []


def test_same_number_as_architectural_adr_passes(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(tmp_path, "docs/skill-adr/0001-options.md", _valid_skill_adr(number="0001"))
    write(tmp_path, "docs/skill-adr/README.md", "(0001-options.md)\n")

    assert "ADR002" not in codes(tmp_path)
    assert lint_architecture_docs(tmp_path, enforce_spec_from="2026-09-15") == []


@pytest.mark.parametrize(
    "heading",
    [
        "# ADR-0007: Wrong series\n",
        "# UI-ADR-0007: Wrong series\n",
    ],
)
def test_foreign_heading_in_skill_adr_fails(tmp_path: Path, heading: str) -> None:
    # self-check: ADR heading in skill-adr fails
    write_valid_tree(tmp_path)
    body = _valid_skill_adr().replace("# SKILL-ADR-0007: Message block\n", heading)
    write(tmp_path, "docs/skill-adr/0007-options.md", body)
    write(tmp_path, "docs/skill-adr/README.md", "(0007-options.md)\n")

    assert "ADR001" in codes(tmp_path)


def test_duplicate_skill_adr_id_fails(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(tmp_path, "docs/skill-adr/0007-options.md", _valid_skill_adr())
    write(tmp_path, "docs/skill-adr/0007-other.md", _valid_skill_adr())
    write(
        tmp_path,
        "docs/skill-adr/README.md",
        "(0007-options.md)\n(0007-other.md)\n",
    )

    assert "ADR002" in codes(tmp_path)


def test_superseded_skill_adr_requires_replacement_link(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(
        tmp_path,
        "docs/skill-adr/0007-options.md",
        _valid_skill_adr(status="superseded"),
    )
    write(tmp_path, "docs/skill-adr/README.md", "(0007-options.md)\n")

    assert "ADR005" in codes(tmp_path)

    replaced = _valid_skill_adr(status="superseded").replace(
        "**Статус:** superseded\n",
        "**Статус:** superseded\n**Заменён:** [SKILL-ADR-0008](0008-next.md)\n",
    )
    write(tmp_path, "docs/skill-adr/0007-options.md", replaced)

    assert "ADR005" not in codes(tmp_path)
