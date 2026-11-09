from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (_ROOT / relative_path).read_text(encoding="utf-8")


def test_brainstorming_requires_adr_assessment_before_full_design() -> None:
    skill = _read(".cursor/skills/brainstorming/SKILL.md")
    picture = _read(".cursor/skills/brainstorming/references/application-picture.md")
    diagram = _read(".cursor/skills/brainstorming/references/process-diagram.md")

    assert "references/adr-assessment.md" in skill
    assert skill.index("ADR assessment gate") < skill.index("Представить дизайн")
    assert picture.index("ADR assessment") < picture.index("Полный дизайн")
    assert "сразу ADR assessment" in picture
    assert "ADR assessment" in diagram
    assert '"ADR assessment" -> "Представить дизайн"' in diagram


def test_spec_template_requires_adr_assessment_metadata() -> None:
    template = _read(".cursor/skills/brainstorming/references/spec-template.md")

    assert "**ADR assessment:**" in template
    assert "N/A — <содержательная причина>" in template
    assert "../adr/NNNN-" in template


def test_orchestrator_routes_adr_gate_through_brainstorming() -> None:
    orchestrator = _read(".cursor/skills/skill-orchestrator/SKILL.md")

    assert "ADR assessment gate" in orchestrator
    assert "отдельный ADR skill" in orchestrator
    assert "proposed" in orchestrator
    assert "останавливает" in orchestrator


def test_plan_quality_checks_linked_adr_status_and_consistency() -> None:
    checklist = _read(".cursor/skills/planner/references/quality-checklist.md")

    assert "linked ADR" in checklist.lower() or "Linked ADR" in checklist
    assert "`proposed`" in checklist
    assert "противореч" in checklist


def test_doc_sync_tracks_adr_index_without_copying_design() -> None:
    checklist = _read(".cursor/skills/update-agents-md/references/doc-sync-checklist.md")

    assert "docs/adr/README.md" in checklist
    assert "ADR assessment" in checklist
    assert "не копир" in checklist
