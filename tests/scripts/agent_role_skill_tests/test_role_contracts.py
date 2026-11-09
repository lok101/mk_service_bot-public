from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
SKILLS = ROOT / ".cursor" / "skills"


def _read(name: str, file: str = "ROLE_CONTRACT.md") -> str:
    return (SKILLS / name / file).read_text(encoding="utf-8")


def _yaml_fence(text: str) -> str:
    match = re.search(r"```ya?ml\s*\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if match is None:
        return ""
    return match.group(1)


def _extract_allowlist(text: str) -> str:
    """Return write_allowlist block text from ROLE_CONTRACT YAML fence."""
    yaml_body = _yaml_fence(text)
    if not yaml_body:
        return ""
    # Line-oriented: do not let DOTALL make `.` cross list item boundaries.
    match = re.search(
        r"write_allowlist\s*:\s*(?:\[([^\]]*)\]|(?:\n(?:[ \t]+- [^\n]+\n?)+))",
        yaml_body,
    )
    if match is None:
        return ""
    if match.group(1) is not None:
        return match.group(1).strip()
    return match.group(0).split(":", 1)[1].strip()


def _allowlist_empty_or_no_src(text: str) -> bool:
    allowlist = _extract_allowlist(text)
    if not allowlist or allowlist == "[]":
        return True
    return "src/" not in allowlist


def test_autonomous_job_contract_forbids_product_code_writes() -> None:
    text = _read("autonomous-job")
    assert "role: supervisor" in text or "role: autonomous-job" in text
    assert "product code" in text.lower() or "src/" in text
    assert "write_allowlist" in text
    # supervisor may touch manifests/docs process paths, not product src
    assert "src/" not in _extract_allowlist(text) or _allowlist_empty_or_no_src(text)


def test_autonomous_job_skill_owns_manifest_and_handoff() -> None:
    skill = _read("autonomous-job", "SKILL.md")
    for needle in ("manifest", "root handoff", "Linear", "retry", "report"):
        assert needle.lower() in skill.lower()


def test_planner_modes_author_and_quality() -> None:
    skill = _read("planner", "SKILL.md")
    assert "author" in skill.lower()
    assert "quality" in skill.lower()
    contract = _read("planner")
    assert "author" in contract.lower() and "quality" in contract.lower()


def _planner_mode_allowlist(mode: str) -> str:
    """Parse modes.<mode>.write_allowlist from planner ROLE_CONTRACT YAML fence only."""
    yaml_body = _yaml_fence(_read("planner"))
    if not yaml_body.strip():
        return ""
    data: Any = yaml.safe_load(yaml_body)
    if not isinstance(data, dict):
        return ""
    modes = data.get("modes")
    if not isinstance(modes, dict):
        return ""
    mode_cfg = modes.get(mode)
    if not isinstance(mode_cfg, dict):
        return ""
    allow = mode_cfg.get("write_allowlist")
    if allow is None:
        return ""
    if allow == []:
        return "[]"
    if isinstance(allow, list):
        return "\n".join(str(item) for item in allow)
    return str(allow)


def test_planner_quality_write_allowlist_empty() -> None:
    allow = _planner_mode_allowlist("quality").replace(" ", "")
    assert allow in {"[]", ""}


def test_planner_author_allowlist_is_design_plan_only() -> None:
    allow = _planner_mode_allowlist("author")
    assert "docs/plans/" in allow or "tasks/" in allow
    assert "src/" not in allow


def test_executor_embeds_happy_edge_error_checklist() -> None:
    skill = _read("executor", "SKILL.md")
    low = skill.lower()
    assert "happy" in low and "edge" in low and "error" in low
    assert "tdd" in low or "red" in low


def test_executor_contract_protects_approved_spec_adr() -> None:
    contract = _read("executor")
    low = contract.lower()
    assert "protected" in low
    assert "spec" in low and "adr" in low


def test_reviewer_modes_and_empty_write_allowlist() -> None:
    skill = _read("reviewer", "SKILL.md")
    low = skill.lower()
    assert "plan" in low and "code" in low and "ad-hoc" in low
    contract = _read("reviewer")
    # global or every mode: empty write allowlist
    # after space-strip needle loses its space; accept either form
    assert "write_allowlist:[]" in contract.replace(" ", "") or ("write_allowlist: []" in contract)


def test_legacy_pipeline_skills_removed() -> None:
    for name in (
        "author-plan",
        "execute-plan",
        "plan-code-review",
        "plan-quality-review",
        "unit-test-writer",
        "spec-clarification",
        "code-review",
        "linear-issue",
        "negotiation-canvas",
    ):
        assert not (SKILLS / name).exists()
    assert (SKILLS / "skill-orchestrator" / "SKILL.md").is_file()
    orch = (SKILLS / "skill-orchestrator" / "SKILL.md").read_text(encoding="utf-8")
    assert len(orch.splitlines()) <= 120


def test_reviewer_mentions_branch_diff_final_review() -> None:
    skill = _read("reviewer", "SKILL.md")
    assert "branch diff" in skill.lower() or "branch-diff" in skill.lower()


def test_planner_mentions_high_risk_checkpoint() -> None:
    skill = _read("planner", "SKILL.md")
    assert "risk: high" in skill.lower() or "risk high" in skill.lower()
    assert "checkpoint" in skill.lower()
