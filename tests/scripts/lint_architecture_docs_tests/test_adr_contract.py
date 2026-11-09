from __future__ import annotations

from pathlib import Path

import pytest
from scripts.lint_architecture_docs import lint_architecture_docs

from .fakes import codes, valid_adr, write, write_valid_tree


def test_valid_accepted_adr_and_index_pass(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)

    assert (
        lint_architecture_docs(
            tmp_path,
            enforce_spec_from="2026-09-15",
        )
        == []
    )


@pytest.mark.parametrize(
    ("relative_path", "content", "expected_code"),
    [
        ("docs/adr/0002-wrong.md", valid_adr(number="0003"), "ADR001"),
        ("docs/adr/0001-other.md", valid_adr(), "ADR002"),
        (
            "docs/adr/0001-test-decision.md",
            valid_adr(status="unknown"),
            "ADR003",
        ),
        (
            "docs/adr/0001-test-decision.md",
            valid_adr().replace("## Enforcement\nCheck.\n", ""),
            "ADR004",
        ),
    ],
)
def test_invalid_adr_contract_reports_expected_code(
    tmp_path: Path,
    relative_path: str,
    content: str,
    expected_code: str,
) -> None:
    write_valid_tree(tmp_path)
    write(tmp_path, relative_path, content)

    assert expected_code in codes(tmp_path)


def test_superseded_adr_without_replacement_fails(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(
        tmp_path,
        "docs/adr/0001-test-decision.md",
        valid_adr(status="superseded"),
    )

    assert "ADR005" in codes(tmp_path)


def test_adr_missing_from_index_fails(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(tmp_path, "docs/adr/README.md", "# Empty index\n")

    assert "ADR006" in codes(tmp_path)
