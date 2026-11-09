from __future__ import annotations

from pathlib import Path

from scripts.lint_architecture_docs import lint_architecture_docs

from .fakes import codes, valid_adr, write, write_valid_tree


def test_new_spec_without_assessment_fails(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(tmp_path, "docs/specs/2026-09-16-new-design.md", "# Design\n")

    assert "ADR007" in codes(tmp_path)


def test_duplicate_assessment_lines_fail(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(
        tmp_path,
        "docs/specs/2026-09-16-dup-design.md",
        (
            "**ADR assessment:** [ADR-0001](../adr/0001-test-decision.md)\n"
            "**ADR assessment:** N/A — вторая строка тоже assessment\n"
        ),
    )

    assert "ADR007" in codes(tmp_path)


def test_historical_spec_before_cutoff_passes_without_assessment(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(tmp_path, "docs/specs/2026-09-14-old-design.md", "# Historical\n")

    violations = lint_architecture_docs(
        tmp_path,
        enforce_spec_from="2026-09-15",
    )

    assert all(item.path.name != "2026-09-14-old-design.md" for item in violations)


def test_new_spec_with_motivated_na_passes(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(
        tmp_path,
        "docs/specs/2026-09-16-na-ok-design.md",
        "**ADR assessment:** N/A — локальное обратимое решение в существующем BC\n",
    )

    assert (
        lint_architecture_docs(
            tmp_path,
            enforce_spec_from="2026-09-15",
        )
        == []
    )


def test_na_without_reason_fails(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(
        tmp_path,
        "docs/specs/2026-09-16-na-design.md",
        "**ADR assessment:** N/A\n",
    )

    assert "ADR008" in codes(tmp_path)


def test_assessment_without_adr_link_or_na_fails(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(
        tmp_path,
        "docs/specs/2026-09-16-text-design.md",
        "**ADR assessment:** spec-only local change\n",
    )

    assert "ADR008" in codes(tmp_path)


def test_broken_adr_link_fails(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(
        tmp_path,
        "docs/specs/2026-09-16-broken-design.md",
        "**ADR assessment:** [ADR-9999](../adr/9999-missing.md)\n",
    )

    assert "ADR009" in codes(tmp_path)


def test_adr_link_target_id_mismatch_fails(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(
        tmp_path,
        "docs/specs/2026-09-16-mismatch-design.md",
        "**ADR assessment:** [ADR-0002](../adr/0001-test-decision.md)\n",
    )

    assert "ADR009" in codes(tmp_path)


def test_multiple_valid_adr_links_pass(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(tmp_path, "docs/adr/0002-second.md", valid_adr(number="0002"))
    write(
        tmp_path,
        "docs/adr/README.md",
        "\n".join(
            (
                "| [ADR-0001](0001-test-decision.md) | Test | accepted |",
                "| [ADR-0002](0002-second.md) | Second | accepted |",
            )
        ),
    )
    write(
        tmp_path,
        "docs/specs/2026-09-16-multiple-design.md",
        (
            "**ADR assessment:** "
            "[ADR-0001](../adr/0001-test-decision.md), "
            "[ADR-0002](../adr/0002-second.md)\n"
        ),
    )

    assert (
        lint_architecture_docs(
            tmp_path,
            enforce_spec_from="2026-09-15",
        )
        == []
    )
