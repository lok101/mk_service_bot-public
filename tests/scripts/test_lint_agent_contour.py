from __future__ import annotations

from pathlib import Path

from scripts.lint_agent_contour import main


def _write_skill(
    root: Path,
    name: str,
    *,
    change_gate: bool | None = None,
    body: str = "Skill body.\n",
    stub: bool = False,
) -> None:
    skill_dir = root / ".cursor" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    front: list[str] = ["---", f"name: {name}"]
    if stub:
        front.append("disable-model-invocation: true")
    if change_gate is True:
        front.append("change_gate: true")
    elif change_gate is False:
        front.append("change_gate: false")
    front.append("---")
    if stub:
        body = "Stub → other skill.\n" + body
    (skill_dir / "SKILL.md").write_text("\n".join(front) + "\n\n" + body, encoding="utf-8")


def _write_registry(
    root: Path,
    *,
    change_gate_skills: list[str],
    route_optional_skills: list[str] | None = None,
    om_canon_writer: str = "om-canon-write",
    om_canon_non_writers: list[str] | None = None,
    non_writer_markers: dict[str, list[str]] | None = None,
) -> None:
    verification = root / "verification"
    verification.mkdir(parents=True, exist_ok=True)
    lines = [
        "change_gate_skills = [",
        *[f'  "{name}",' for name in change_gate_skills],
        "]",
        "route_optional_skills = [",
        *[f'  "{name}",' for name in (route_optional_skills or [])],
        "]",
        f'om_canon_writer = "{om_canon_writer}"',
        "om_canon_non_writers = [",
        *[f'  "{name}",' for name in (om_canon_non_writers or [])],
        "]",
    ]
    if non_writer_markers:
        lines.append("")
        lines.append("[om_canon_non_writer_markers]")
        for skill, patterns in non_writer_markers.items():
            joined = ", ".join(f'"{p}"' for p in patterns)
            lines.append(f'"{skill}" = [{joined}]')
    (verification / "agent-contour.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_prose_anchors(root: Path, gate_skills: list[str]) -> None:
    joined = ", ".join(gate_skills)
    (root / "AGENTS.md").write_text(
        f"# Agents\n\n**`change_gate`:** стартовый набор: {joined}.\n",
        encoding="utf-8",
    )
    orch = root / ".cursor" / "skills" / "skill-orchestrator"
    orch.mkdir(parents=True, exist_ok=True)
    (orch / "SKILL.md").write_text(
        "---\nname: skill-orchestrator\n---\n\n"
        f"## change_gate\n\nСтартовый набор `true`: {joined}.\n",
        encoding="utf-8",
    )
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "glossary.md").write_text(
        f"| **`change_gate`** | process | Стартовый набор: {joined}. |\n",
        encoding="utf-8",
    )
    refs = orch / "references"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "route-map.md").write_text("# route\n\n", encoding="utf-8")
    (refs / "skill-flow.md").write_text("# flow\n\n", encoding="utf-8")


def _write_om_skeleton(root: Path, *, broken_link: bool = False) -> None:
    om = root / "docs" / "company-operating-model"
    om.mkdir(parents=True, exist_ok=True)
    target = "capabilities.md"
    (om / target).write_text("# Capabilities\n", encoding="utf-8")
    link = "missing.md" if broken_link else target
    (om / "README.md").write_text(
        f"## Представления модели\n\n- [Capabilities]({link}) — capabilities.\n",
        encoding="utf-8",
    )


def _route(root: Path, *skill_names: str) -> None:
    refs = root / ".cursor" / "skills" / "skill-orchestrator" / "references"
    names = " ".join(f"`{name}`" for name in skill_names)
    (refs / "route-map.md").write_text(f"# route\n\nSkills: {names}\n", encoding="utf-8")
    (refs / "skill-flow.md").write_text(f"# flow\n\n{names}\n", encoding="utf-8")


def _run(root: Path, capsys: object) -> tuple[int, str]:
    code = main(["--root", str(root)])
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    return code, captured.out + captured.err  # type: ignore[no-any-return]


def test_happy_aligned_tree_passes(tmp_path: Path, capsys: object) -> None:
    gates = ["brainstorming", "om-canon-write"]
    _write_registry(
        tmp_path,
        change_gate_skills=gates,
        route_optional_skills=["author-plan"],
        om_canon_non_writers=["brainstorming"],
        non_writer_markers={"brainstorming": [r"канон OM не писать"]},
    )
    _write_skill(tmp_path, "brainstorming", change_gate=True, body="канон OM не писать напрямую.\n")
    _write_skill(tmp_path, "om-canon-write", change_gate=True, body="Writes OM canon.\n")
    _write_skill(tmp_path, "author-plan", stub=True)
    _write_skill(tmp_path, "skill-orchestrator", body="Router.\n")
    _write_prose_anchors(tmp_path, gates)
    _route(tmp_path, "brainstorming", "om-canon-write", "skill-orchestrator")
    _write_om_skeleton(tmp_path)

    code, out = _run(tmp_path, capsys)
    assert code == 0, out
    assert "OK" in out


def test_ac01_change_gate_drift_fails(tmp_path: Path, capsys: object) -> None:
    _write_registry(tmp_path, change_gate_skills=["brainstorming"])
    _write_skill(tmp_path, "brainstorming", change_gate=True)
    _write_skill(tmp_path, "code-audit", change_gate=True)
    _write_skill(tmp_path, "skill-orchestrator")
    _write_prose_anchors(tmp_path, ["brainstorming"])
    _route(tmp_path, "brainstorming", "code-audit", "skill-orchestrator")
    _write_om_skeleton(tmp_path)

    code, out = _run(tmp_path, capsys)
    assert code != 0
    assert "AC01" in out


def test_ac02_unmapped_live_skill_fails(tmp_path: Path, capsys: object) -> None:
    gates = ["brainstorming"]
    _write_registry(tmp_path, change_gate_skills=gates)
    _write_skill(tmp_path, "brainstorming", change_gate=True)
    _write_skill(tmp_path, "orphan-live", body="I am live.\n")
    _write_skill(tmp_path, "skill-orchestrator")
    _write_prose_anchors(tmp_path, gates)
    _route(tmp_path, "brainstorming", "skill-orchestrator")
    _write_om_skeleton(tmp_path)

    code, out = _run(tmp_path, capsys)
    assert code != 0
    assert "AC02" in out


def test_ac03_missing_non_writer_marker_fails(tmp_path: Path, capsys: object) -> None:
    gates = ["brainstorming", "om-canon-write"]
    _write_registry(
        tmp_path,
        change_gate_skills=gates,
        om_canon_non_writers=["brainstorming"],
        non_writer_markers={"brainstorming": [r"канон OM не писать"]},
    )
    _write_skill(tmp_path, "brainstorming", change_gate=True, body="No forbid marker here.\n")
    _write_skill(tmp_path, "om-canon-write", change_gate=True)
    _write_skill(tmp_path, "skill-orchestrator")
    _write_prose_anchors(tmp_path, gates)
    _route(tmp_path, "brainstorming", "om-canon-write", "skill-orchestrator")
    _write_om_skeleton(tmp_path)

    code, out = _run(tmp_path, capsys)
    assert code != 0
    assert "AC03" in out


def test_ac05_broken_om_link_fails(tmp_path: Path, capsys: object) -> None:
    gates = ["om-canon-write"]
    _write_registry(tmp_path, change_gate_skills=gates)
    _write_skill(tmp_path, "om-canon-write", change_gate=True)
    _write_skill(tmp_path, "skill-orchestrator")
    _write_prose_anchors(tmp_path, gates)
    _route(tmp_path, "om-canon-write", "skill-orchestrator")
    _write_om_skeleton(tmp_path, broken_link=True)

    code, out = _run(tmp_path, capsys)
    assert code != 0
    assert "AC05" in out or "AC04" in out


def test_ac10_agents_over_budget_warns_exit_zero(tmp_path: Path, capsys: object) -> None:
    gates = ["om-canon-write"]
    _write_registry(tmp_path, change_gate_skills=gates)
    _write_skill(tmp_path, "om-canon-write", change_gate=True)
    _write_skill(tmp_path, "skill-orchestrator")
    _write_prose_anchors(tmp_path, gates)
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        "# Agents\n\n**`change_gate`:** стартовый набор: om-canon-write.\n" + ("x\n" * 220),
        encoding="utf-8",
    )
    _route(tmp_path, "om-canon-write", "skill-orchestrator")
    _write_om_skeleton(tmp_path)

    code, out = _run(tmp_path, capsys)
    assert code == 0, out
    assert "AC10" in out
    assert "WARN" in out
