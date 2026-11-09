"""Cutover helpers: split mount + host/process partition (AGT-009)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from scripts.agent_platform_mount import (
    HOST_SKILLS,
    LinkMode,
    load_kernel_ref,
    mount_process_skills,
    process_skill_names,
    resolve_home,
)


def test_host_skills_allowlist_stable() -> None:
    assert "update-agents-md" in HOST_SKILLS
    assert "om-canon-write" in HOST_SKILLS
    assert "brainstorming" not in HOST_SKILLS
    assert "platform-kernel-audit" not in HOST_SKILLS


def test_load_kernel_ref_and_home(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    (home / "cursor" / "skills" / "brainstorming").mkdir(parents=True)
    (home / "cursor" / "skills" / "update-agents-md").mkdir(parents=True)
    product = tmp_path / "product"
    product.mkdir()
    (product / "kernel_ref").write_text(
        json.dumps({"home": str(home), "ref": "deadbeef", "mount": {"mode": "split"}}),
        encoding="utf-8",
    )
    kr = load_kernel_ref(product)
    resolved = resolve_home(product, kr)
    assert resolved == home.resolve()
    names = process_skill_names(resolved)
    assert "brainstorming" in names
    assert "update-agents-md" not in names


def test_mount_idempotent_and_missing_home_errors(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    skill = home / "cursor" / "skills" / "brainstorming"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# x\n", encoding="utf-8")
    product = tmp_path / "product"
    (product / ".cursor" / "skills").mkdir(parents=True)
    (product / "kernel_ref").write_text(
        json.dumps({"home": str(home), "ref": "deadbeef", "mount": {"mode": "split"}}),
        encoding="utf-8",
    )
    first = mount_process_skills(product_root=product, link_mode=LinkMode.HARDLINK)
    assert "brainstorming" in first
    second = mount_process_skills(product_root=product, link_mode=LinkMode.HARDLINK)
    assert "brainstorming" in second
    link = product / ".cursor" / "skills" / "brainstorming"
    assert link.is_dir()
    assert not link.is_symlink()
    assert (link / "SKILL.md").read_text(encoding="utf-8") == "# x\n"


def test_hardlink_replaces_existing_junction(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    skill = home / "cursor" / "skills" / "brainstorming"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# x\n", encoding="utf-8")
    product = tmp_path / "product"
    (product / ".cursor" / "skills").mkdir(parents=True)
    (product / "kernel_ref").write_text(
        json.dumps({"home": str(home), "ref": "deadbeef", "mount": {"mode": "split"}}),
        encoding="utf-8",
    )
    mount_process_skills(product_root=product, link_mode=LinkMode.JUNCTION)
    link = product / ".cursor" / "skills" / "brainstorming"
    assert link.resolve() == skill.resolve()
    mount_process_skills(product_root=product, link_mode=LinkMode.HARDLINK)
    assert link.is_dir()
    assert (link / "SKILL.md").read_text(encoding="utf-8") == "# x\n"
    if sys.platform == "win32":
        assert os.path.normcase(str(link)) == os.path.normcase(str(link.resolve()))


def test_mount_junction_mode(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    skill = home / "cursor" / "skills" / "brainstorming"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# x\n", encoding="utf-8")
    product = tmp_path / "product"
    (product / ".cursor" / "skills").mkdir(parents=True)
    (product / "kernel_ref").write_text(
        json.dumps({"home": str(home), "ref": "deadbeef", "mount": {"mode": "split"}}),
        encoding="utf-8",
    )
    mount_process_skills(product_root=product, link_mode=LinkMode.JUNCTION)
    link = product / ".cursor" / "skills" / "brainstorming"
    assert link.exists()
    assert link.resolve() == skill.resolve()

    bad = tmp_path / "bad_product"
    bad.mkdir()
    (bad / "kernel_ref").write_text(
        json.dumps({"home": str(tmp_path / "missing"), "ref": "x", "mount": {}}),
        encoding="utf-8",
    )
    with pytest.raises(FileNotFoundError):
        mount_process_skills(product_root=bad)
