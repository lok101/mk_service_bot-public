from __future__ import annotations

from pathlib import Path

from scripts.lint_architecture_docs import lint_architecture_docs

from .fakes import codes, valid_adr, valid_ui_adr, write, write_valid_tree


def test_ui_adr_full_record_with_index_passes(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(tmp_path, "docs/ui-adr/0008-ui-rule.md", valid_ui_adr(number="0008"))
    write(tmp_path, "docs/ui-adr/README.md", "(0008-ui-rule.md)\n")

    assert (
        lint_architecture_docs(
            tmp_path,
            enforce_spec_from="2026-09-15",
        )
        == []
    )


def test_ui_adr_missing_required_section_fails(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    broken = valid_ui_adr(number="0008").replace("## Enforcement\nCheck.\n", "")
    write(tmp_path, "docs/ui-adr/0008-ui-rule.md", broken)
    write(tmp_path, "docs/ui-adr/README.md", "(0008-ui-rule.md)\n")

    assert "ADR004" in codes(tmp_path)


def test_ui_adr_missing_from_own_index_fails(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(tmp_path, "docs/ui-adr/0008-ui-rule.md", valid_ui_adr(number="0008"))
    write(tmp_path, "docs/ui-adr/README.md", "# UI index\n")

    assert "ADR006" in codes(tmp_path)


def test_same_number_across_adr_and_ui_adr_passes(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(tmp_path, "docs/ui-adr/0001-ui-rule.md", valid_ui_adr(number="0001"))
    write(tmp_path, "docs/ui-adr/README.md", "(0001-ui-rule.md)\n")

    assert "ADR002" not in codes(tmp_path)
    assert (
        lint_architecture_docs(
            tmp_path,
            enforce_spec_from="2026-09-15",
        )
        == []
    )


def test_ui_adr_with_arch_prefix_heading_fails(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(tmp_path, "docs/ui-adr/0008-ui-rule.md", valid_adr(number="0008"))
    write(tmp_path, "docs/ui-adr/README.md", "(0008-ui-rule.md)\n")

    assert "ADR001" in codes(tmp_path)


def _pointer(*, number: str, status: str = "accepted") -> str:
    return (
        f"# ADR-{number}: Moved rule\n"
        "\n"
        f"**Статус:** {status}\n"
        "**Дата:** 2026-09-29\n"
        f"**Перенесён:** [UI-ADR-{number}](../ui-adr/{number}-moved.md)\n"
    )


def _write_moved_pair(root: Path, *, status: str = "accepted") -> None:
    write_valid_tree(root)
    write(root, "docs/adr/0008-moved.md", _pointer(number="0008", status=status))
    write(root, "docs/ui-adr/0008-moved.md", valid_ui_adr(number="0008"))
    write(root, "docs/ui-adr/README.md", "(0008-moved.md)\n")


def test_moved_record_without_sections_passes(tmp_path: Path) -> None:
    _write_moved_pair(tmp_path)

    assert (
        lint_architecture_docs(
            tmp_path,
            enforce_spec_from="2026-09-15",
        )
        == []
    )


def test_full_record_and_moved_pointer_same_id_pass(tmp_path: Path) -> None:
    _write_moved_pair(tmp_path)

    assert "ADR002" not in codes(tmp_path)


def test_moved_record_rejects_status_other_than_accepted(tmp_path: Path) -> None:
    _write_moved_pair(tmp_path, status="proposed")

    assert "ADR003" in codes(tmp_path)


def test_assessment_link_to_moved_record_passes(tmp_path: Path) -> None:
    _write_moved_pair(tmp_path)
    write(
        tmp_path,
        "docs/specs/2026-09-16-moved-design.md",
        "**ADR assessment:** [ADR-0008](../adr/0008-moved.md)\n",
    )

    assert (
        lint_architecture_docs(
            tmp_path,
            enforce_spec_from="2026-09-15",
        )
        == []
    )


def test_ui_adr_moved_marker_still_requires_full_template(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(tmp_path, "docs/ui-adr/0009-moved.md", _pointer(number="0009"))
    write(tmp_path, "docs/ui-adr/README.md", "(0009-moved.md)\n")

    assert "ADR004" in codes(tmp_path)


def test_assessment_link_to_missing_file_still_fails(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(
        tmp_path,
        "docs/specs/2026-09-16-missing-design.md",
        "**ADR assessment:** [ADR-9999](../adr/9999-missing.md)\n",
    )

    assert "ADR009" in codes(tmp_path)


def test_assessment_ui_adr_link_only_passes(tmp_path: Path) -> None:
    write_valid_tree(tmp_path)
    write(tmp_path, "docs/ui-adr/0018-header.md", valid_ui_adr(number="0018"))
    write(tmp_path, "docs/ui-adr/README.md", "(0018-header.md)\n")
    write(
        tmp_path,
        "docs/specs/2026-09-16-ui-only-design.md",
        "**ADR assessment:** [UI-ADR-0018](../ui-adr/0018-header.md)\n",
    )

    assert (
        lint_architecture_docs(
            tmp_path,
            enforce_spec_from="2026-09-15",
        )
        == []
    )
