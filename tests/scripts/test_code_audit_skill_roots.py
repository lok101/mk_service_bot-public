from __future__ import annotations

import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _ROOT / ".cursor/skills/code-audit/SKILL.md"
_CHECK = _ROOT / ".cursor/skills/code-audit/references/audit-checklist.md"


def _application_root_count() -> int:
    data = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = data["tool"]["importlinter"]["contracts"]
    forbidden = next(
        item for item in contracts if item["name"] == "Application package internals are private"
    )
    return sum(
        1 for module in forbidden["source_modules"] if str(module).startswith("src.application.")
    )


def test_code_audit_skill_root_count_matches_pyproject() -> None:
    count = _application_root_count()
    needle = f"{count} корн"
    skill = _SKILL.read_text(encoding="utf-8")
    check = _CHECK.read_text(encoding="utf-8")
    assert needle in skill
    assert needle in check
    assert "22 корн" not in skill
    assert "22 корн" not in check
