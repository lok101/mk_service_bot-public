from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.agent_doctor_lib import ProbeStatus, run_doctor
from scripts.agent_platform_bootstrap import (
    emit_golden_path,
    resolve_default_home,
    scaffold_home,
)


def test_scaffold_home_capability_samples_nonempty(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    scaffold_home(home)
    overlay = (home / "OVERLAY.template.md").read_text(encoding="utf-8")
    expected = {
        "lint": "uv run ruff check …",
        "types": "uv run mypy …",
        "unit": "uv run pytest … -q",
        "aggregate": "full repo check script",
        "structural": "uv run python scripts/structural_scan.py",
    }
    for cap, command in expected.items():
        assert f"| {cap} | {command} |" in overlay
    assert "Sample-команды" in overlay
    assert "не замена product check" in overlay


def test_scaffold_home_happy_layout(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    result = scaffold_home(home)
    assert result.created is True
    assert (home / "README.md").is_file()
    assert (home / "OVERLAY.template.md").is_file()
    assert (home / "profiles" / "default.md").is_file()
    assert (home / "profiles" / "python.md").is_file()
    assert (home / "cursor" / "skills" / ".gitkeep").is_file()
    assert (home / "bootstrap" / "__main__.py").is_file()
    assert (home / ".git").exists()
    # no dump of living product skills tree
    assert not (home / "cursor" / "skills" / "executor").exists()


def test_scaffold_home_edge_idempotent(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    first = scaffold_home(home)
    second = scaffold_home(home)
    assert first.created is True
    assert second.created is False
    assert second.already_exists is True


def test_golden_path_happy_doctor_green(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    scaffold_home(home)
    target = tmp_path / "fixture_product"
    emit_golden_path(home=home, target=target, profile="python")
    assert (target / "AGENT-OVERLAY.md").is_file()
    assert (target / "kernel_ref").is_file()
    for name in ("lint", "types", "unit", "aggregate", "structural"):
        stub = target / "stubs" / f"{name}.py"
        assert stub.is_file()
        assert subprocess.run([sys.executable, str(stub)], check=False).returncode == 0
    report = run_doctor(
        workspace=target,
        mode="all",
        structural_runner=lambda _argv, _cwd: 0,
    )
    assert report.platform_on is True
    assert report.overall == ProbeStatus.PASS
    assert report.exit_code == 0
    assert (target / "sgconfig.yml").is_file()
    assert (target / "structural-rules" / "golden-nonempty.yml").is_file()
    overlay = (target / "AGENT-OVERLAY.md").read_text(encoding="utf-8")
    assert "ruff" not in overlay.lower()
    assert "mypy" not in overlay.lower()


def test_golden_path_error_incomplete_admission_fails(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    scaffold_home(home)
    target = tmp_path / "broken"
    emit_golden_path(home=home, target=target, profile="default")
    overlay = target / "AGENT-OVERLAY.md"
    overlay.write_text(
        """# Overlay

| Слот | Значение |
|------|----------|
| Conformance profile | default |

## Capabilities

| Capability | Command |
|------------|---------|
| lint | python stubs/lint.py |
| types | |
| unit | python stubs/unit.py |
| aggregate | python stubs/aggregate.py |
""",
        encoding="utf-8",
    )
    report = run_doctor(workspace=target, mode="admission")
    assert report.overall == ProbeStatus.FAIL
    assert any(p.probe_id == "A03" and p.status == ProbeStatus.FAIL for p in report.probes)


def test_resolve_default_home_primary_and_worktree(tmp_path: Path) -> None:
    primary = tmp_path / "mk_service_bot"
    primary.mkdir()
    assert resolve_default_home(primary) == tmp_path / "agent_platform"
    wt_root = tmp_path / "mk_service_bot-wt"
    lane = wt_root / "agt-008-bootstrap-home"
    lane.mkdir(parents=True)
    assert resolve_default_home(lane) == tmp_path / "agent_platform"


def test_kernel_ref_json_shape(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    scaffold_home(home)
    target = tmp_path / "prod"
    emit_golden_path(home=home, target=target, profile="default")
    payload = json.loads((target / "kernel_ref").read_text(encoding="utf-8"))
    assert payload["home"]
    assert payload["ref"]
    assert "mount" in payload
