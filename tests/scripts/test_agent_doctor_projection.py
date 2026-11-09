"""Admission A05 RO process projection probe (ADR-0082)."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from scripts.agent_doctor_lib import ProbeStatus, run_admission
from scripts.agent_platform_mount import mount_process_skills
from scripts.structural_catalog import write_minimal_catalog


def _overlay(product: Path) -> None:
    (product / "AGENT-OVERLAY.md").write_text(
        """# Overlay

| Слот | Значение |
|------|----------|
| Conformance profile | python |

## Capabilities

| Capability | Command |
|------------|---------|
| lint | echo lint |
| types | echo types |
| unit | echo unit |
| aggregate | echo aggregate |
| structural | echo structural |
""",
        encoding="utf-8",
    )


def test_admission_pass_on_ro_projection(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    skill = home / "cursor" / "skills" / "brainstorming"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# x\n", encoding="utf-8")
    product = tmp_path / "product"
    product.mkdir()
    _overlay(product)
    (product / "kernel_ref").write_text(
        json.dumps({"home": str(home), "ref": "deadbeef", "mount": {"mode": "split"}}),
        encoding="utf-8",
    )
    mount_process_skills(product_root=product)
    write_minimal_catalog(product)
    report = run_admission(workspace=product)
    assert report.overall is ProbeStatus.PASS
    a05 = next(p for p in report.probes if p.probe_id == "A05")
    assert a05.status is ProbeStatus.PASS


def test_admission_fail_on_writable_projection(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    skill = home / "cursor" / "skills" / "brainstorming"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# x\n", encoding="utf-8")
    product = tmp_path / "product"
    product.mkdir()
    _overlay(product)
    (product / "kernel_ref").write_text(
        json.dumps({"home": str(home), "ref": "deadbeef", "mount": {"mode": "split"}}),
        encoding="utf-8",
    )
    mount_process_skills(product_root=product)
    proj = product / ".cursor" / "skills" / "brainstorming" / "SKILL.md"
    proj.chmod(proj.stat().st_mode | stat.S_IWRITE)
    assert os.access(proj, os.W_OK)
    report = run_admission(workspace=product)
    assert report.overall is ProbeStatus.FAIL
    a05 = next(p for p in report.probes if p.probe_id == "A05")
    assert a05.status is ProbeStatus.FAIL
    assert "writable" in a05.message
