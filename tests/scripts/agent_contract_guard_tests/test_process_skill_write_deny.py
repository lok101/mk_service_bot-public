"""Process skill projection paths are builtin-protected (ADR-0082)."""

from __future__ import annotations

from scripts.agent_contract_guard_lib.paths import (
    HOST_SKILL_NAMES,
    path_is_builtin_protected,
    path_is_process_skill_projection,
)
from scripts.agent_platform_mount import HOST_SKILLS


def test_host_skill_names_match_mount_allowlist() -> None:
    assert HOST_SKILL_NAMES == HOST_SKILLS


def test_process_projection_denied_host_allowed() -> None:
    assert path_is_process_skill_projection(".cursor/skills/executor/SKILL.md")
    assert path_is_process_skill_projection(".cursor/skills/brainstorming/")
    assert path_is_builtin_protected(".cursor/skills/planner/ROLE_CONTRACT.md")
    assert not path_is_process_skill_projection(".cursor/skills/om-canon-write/SKILL.md")
    assert not path_is_process_skill_projection(".cursor/skills/update-agents-md/x")
    assert not path_is_builtin_protected(".cursor/skills/om-canon-write/SKILL.md")
