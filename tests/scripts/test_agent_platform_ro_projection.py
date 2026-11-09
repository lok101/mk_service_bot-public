"""RO copy projection for process skills (ADR-0082 / AGT-015)."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from scripts.agent_platform_mount import LinkMode, mount_process_skills


def _product_with_home(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "agent_platform"
    skill = home / "cursor" / "skills" / "brainstorming"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# process\n", encoding="utf-8")
    product = tmp_path / "product"
    (product / ".cursor" / "skills" / "om-canon-write").mkdir(parents=True)
    (product / ".cursor" / "skills" / "om-canon-write" / "SKILL.md").write_text(
        "# host\n",
        encoding="utf-8",
    )
    (product / "kernel_ref").write_text(
        json.dumps({"home": str(home), "ref": "deadbeef", "mount": {"mode": "split"}}),
        encoding="utf-8",
    )
    return product, home


def test_default_mount_is_readonly_copy(tmp_path: Path) -> None:
    product, _home = _product_with_home(tmp_path)
    mounted = mount_process_skills(product_root=product)
    assert "brainstorming" in mounted
    proj = product / ".cursor" / "skills" / "brainstorming" / "SKILL.md"
    assert proj.read_text(encoding="utf-8") == "# process\n"
    assert not os.access(proj, os.W_OK)
    host = product / ".cursor" / "skills" / "om-canon-write" / "SKILL.md"
    assert host.read_text(encoding="utf-8") == "# host\n"
    # host must remain writable for product authoring
    host.chmod(host.stat().st_mode | stat.S_IWRITE)
    assert os.access(host, os.W_OK)


def test_copy_mount_idempotent_keeps_readonly(tmp_path: Path) -> None:
    product, _home = _product_with_home(tmp_path)
    mount_process_skills(product_root=product, link_mode=LinkMode.COPY)
    mount_process_skills(product_root=product, link_mode=LinkMode.COPY)
    proj = product / ".cursor" / "skills" / "brainstorming" / "SKILL.md"
    assert not os.access(proj, os.W_OK)
