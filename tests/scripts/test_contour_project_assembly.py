from __future__ import annotations

from pathlib import Path

from scripts.contour_project_assembly import assemble_big_bang_contour
from scripts.tracker_issue_lib.store import list_issues, list_projects, read_issue


def test_non_big_bang_creates_nothing(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    result = assemble_big_bang_contour(
        root,
        rollout="incremental",
        title="Fridge",
        line_titles=["Line A"],
        discovery_link="docs/discovery/demo",
    )
    assert result.skipped is True
    assert result.project_id is None
    assert not root.exists()


def test_big_bang_creates_project_lines_and_gate(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    result = assemble_big_bang_contour(
        root,
        rollout="big-bang",
        title="Fridge contour",
        line_titles=["Loading spine", "Ops accept"],
        discovery_link="docs/discovery/fridge",
        operating_case="operating_cases.micromarket_loading_case",
    )
    assert result.skipped is False
    assert result.project_id is not None
    assert result.project_id.startswith("PRJ-")
    assert len(result.line_ids) == 2
    assert result.gate_id is not None
    assert result.created_project is True
    assert result.created_lines == 2
    assert result.created_gate is True

    projects = list_projects(root)
    assert len(projects) == 1
    assert projects[0].links.get("discovery") == "docs/discovery/fridge"
    assert projects[0].operating_case == "operating_cases.micromarket_loading_case"

    issues = list_issues(root)
    assert len(issues) == 3
    for issue in issues:
        assert issue.project == result.project_id
        assert issue.status == "open"
    gate = read_issue(root, result.gate_id)
    assert gate.title.startswith("Contour gate:")
    assert "lane Final Gate" in gate.body
    assert "operating_cases.micromarket_loading_case" in gate.body


def test_big_bang_assembly_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "queue"
    kwargs = {
        "rollout": "big-bang",
        "title": "Fridge contour",
        "line_titles": ["Loading spine", "Ops accept"],
        "discovery_link": "docs/discovery/fridge",
        "operating_case": "operating_cases.micromarket_loading_case",
    }
    first = assemble_big_bang_contour(root, **kwargs)  # type: ignore[arg-type]
    second = assemble_big_bang_contour(root, **kwargs)  # type: ignore[arg-type]
    assert second.skipped is False
    assert second.project_id == first.project_id
    assert second.line_ids == first.line_ids
    assert second.gate_id == first.gate_id
    assert second.created_project is False
    assert second.created_lines == 0
    assert second.created_gate is False
    assert len(list_projects(root)) == 1
    assert len(list_issues(root)) == 3
