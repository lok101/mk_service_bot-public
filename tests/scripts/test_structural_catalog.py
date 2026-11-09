from __future__ import annotations

from pathlib import Path

from scripts.structural_catalog import (
    CatalogYamlError,
    assess_structural_catalog,
    parse_yaml_subset,
    write_minimal_catalog,
)


def test_catalog_happy_minimal(tmp_path: Path) -> None:
    write_minimal_catalog(tmp_path)
    report = assess_structural_catalog(tmp_path)
    assert report.ok is True
    assert "1 error rule" in report.message


def test_catalog_edge_hint_rule_does_not_count(tmp_path: Path) -> None:
    write_minimal_catalog(tmp_path)
    rule = tmp_path / "structural-rules" / "golden-nonempty.yml"
    text = rule.read_text(encoding="utf-8").replace("severity: error", "severity: hint")
    rule.write_text(text, encoding="utf-8")
    report = assess_structural_catalog(tmp_path)
    assert report.ok is False
    assert report.message == "no error-severity rule"


def test_catalog_error_missing_config(tmp_path: Path) -> None:
    report = assess_structural_catalog(tmp_path)
    assert report.ok is False
    assert report.message == "sgconfig.yml missing"


def test_catalog_error_missing_invalid(tmp_path: Path) -> None:
    write_minimal_catalog(tmp_path)
    test_file = tmp_path / "structural-rule-tests" / "golden-nonempty.yml"
    test_file.write_text('id: golden-nonempty\nvalid:\n  - "x = 1"\n', encoding="utf-8")
    report = assess_structural_catalog(tmp_path)
    assert report.ok is False
    assert "without invalid test" in report.message


def test_catalog_repo_tree_ok() -> None:
    root = Path(__file__).resolve().parents[2]
    report = assess_structural_catalog(root)
    assert report.ok is True


def test_parse_yaml_subset_error_flow_list() -> None:
    try:
        parse_yaml_subset("ruleDirs: []\n")
    except CatalogYamlError as exc:
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("flow list must fail closed")
