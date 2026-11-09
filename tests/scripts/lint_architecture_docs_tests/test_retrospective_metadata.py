from __future__ import annotations

from pathlib import Path

import scripts.lint_architecture_docs as lint_mod

from .fakes import codes, valid_adr, write, write_valid_tree


def _retrospective_adr(extra: str) -> str:
    needle = "**Связанный design:** [design](../specs/2026-09-15-test-design.md)\n"
    return valid_adr().replace(needle, needle + extra, 1)


def test_retrospective_adr_missing_sources_fails(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(
        tmp_path,
        "docs/adr/0001-test-decision.md",
        _retrospective_adr("**Характер:** retrospective\n**Действует с:** 2026-01-15\n"),
    )

    assert "ADR010" in codes(tmp_path)


def test_retrospective_adr_missing_effective_date_fails(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(
        tmp_path,
        "docs/adr/0001-test-decision.md",
        _retrospective_adr(
            "**Характер:** retrospective\n"
            "**Источники:** [design](../specs/2026-09-15-test-design.md)\n"
        ),
    )

    assert "ADR010" in codes(tmp_path)


def test_retrospective_adr_invalid_effective_date_fails(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(
        tmp_path,
        "docs/adr/0001-test-decision.md",
        _retrospective_adr(
            "**Характер:** retrospective\n"
            "**Действует с:** 2026/01/15\n"
            "**Источники:** [design](../specs/2026-09-15-test-design.md)\n"
        ),
    )

    assert "ADR010" in codes(tmp_path)


def test_retrospective_adr_unknown_effective_date_passes(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(
        tmp_path,
        "docs/adr/0001-test-decision.md",
        _retrospective_adr(
            "**Характер:** retrospective\n"
            "**Действует с:** не установлено\n"
            "**Источники:** [design](../specs/2026-09-15-test-design.md)\n"
        ),
    )

    assert codes(tmp_path) == set()


def test_retrospective_adr_with_sources_and_date_passes(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(
        tmp_path,
        "docs/adr/0001-test-decision.md",
        _retrospective_adr(
            "**Характер:** retrospective\n"
            "**Действует с:** 2026-01-15\n"
            "**Источники:** [design](../specs/2026-09-15-test-design.md)\n"
        ),
    )

    assert codes(tmp_path) == set()


def test_retrospective_metadata_does_not_read_code(tmp_path: Path) -> None:
    body = _retrospective_adr(
        "**Характер:** retrospective\n"
        "**Действует с:** 2026-01-15\n"
        "**Источники:** [design](../specs/2026-09-15-test-design.md)\n"
    ).replace("Choose A.", "См. missing.py; файла в дереве нет.")
    write_valid_tree(tmp_path)
    write(tmp_path, "docs/adr/0001-test-decision.md", body)

    assert codes(tmp_path) == set()
    assert not (tmp_path / "missing.py").exists()


def test_copied_adr_template_is_not_retrospective(tmp_path: Path) -> None:
    template = (Path(__file__).resolve().parents[3] / "docs" / "adr" / "template.md").read_text(
        encoding="utf-8"
    )
    filled = (
        template.replace(
            "# ADR-NNNN: Краткое название решения",
            "# ADR-0001: Test decision",
        )
        .replace("**Статус:** proposed", "**Статус:** accepted")
        .replace(
            "[название](../specs/YYYY-MM-DD-name-design.md)",
            "[design](../specs/2026-09-15-test-design.md)",
        )
        .replace("YYYY-MM-DD", "2026-09-15")
    )
    write_valid_tree(tmp_path)
    write(tmp_path, "docs/adr/0001-test-decision.md", filled)

    assert lint_mod._RETROSPECTIVE_MARK_RE.search(filled) is None
    assert codes(tmp_path) == set()
