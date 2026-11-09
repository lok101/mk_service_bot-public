from __future__ import annotations

import json
from pathlib import Path

from scripts.agent_doctor_lib import (
    DoctorReport,
    ProbeStatus,
    run_admission,
    run_conformance,
    run_doctor,
)
from scripts.structural_catalog import write_minimal_catalog

_COMPLETE_OVERLAY = """# Overlay

| Слот | Значение |
|------|----------|
| Conformance profile | python |
| Язык ответов | ru |

## Capabilities

| Capability | Command |
|------------|---------|
| lint | echo lint |
| types | echo types |
| unit | echo unit |
| aggregate | echo aggregate |
| structural | echo structural |
"""

_INCOMPLETE_OVERLAY = """# Overlay

| Слот | Значение |
|------|----------|
| Conformance profile | default |

## Capabilities

| Capability | Command |
|------------|---------|
| lint | echo lint |
| types | |
| unit | echo unit |
| aggregate | echo aggregate |
| structural | echo structural |
"""

_NO_MAP_OVERLAY = """# Overlay

| Слот | Значение |
|------|----------|
| Язык ответов | ru |
| Команда проверки | |
"""

_UNKNOWN_ID_OVERLAY = """# Overlay

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
| mystery | echo x |
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_admission_happy_complete_overlay(tmp_path: Path) -> None:
    write_minimal_catalog(tmp_path)
    overlay = _write(tmp_path, "AGENT-OVERLAY.md", _COMPLETE_OVERLAY)
    report = run_admission(workspace=tmp_path, overlay_path=overlay)
    assert report.mode == "admission"
    assert report.platform_on is True
    assert report.overall == ProbeStatus.PASS
    statuses = {p.probe_id: p.status for p in report.probes}
    assert statuses["A05"] == ProbeStatus.NOT_APPLICABLE
    assert statuses["A06"] == ProbeStatus.PASS
    assert all(
        status == ProbeStatus.PASS for probe_id, status in statuses.items() if probe_id != "A05"
    )


def test_admission_edge_no_capability_map_not_applicable(tmp_path: Path) -> None:
    overlay = _write(tmp_path, "AGENT-OVERLAY.md", _NO_MAP_OVERLAY)
    report = run_admission(workspace=tmp_path, overlay_path=overlay)
    assert report.platform_on is False
    assert report.overall == ProbeStatus.NOT_APPLICABLE
    assert report.exit_code == 0


def test_admission_error_incomplete_required(tmp_path: Path) -> None:
    overlay = _write(tmp_path, "AGENT-OVERLAY.md", _INCOMPLETE_OVERLAY)
    report = run_admission(workspace=tmp_path, overlay_path=overlay)
    assert report.platform_on is True
    assert report.overall == ProbeStatus.FAIL
    assert report.exit_code != 0
    assert any(p.probe_id == "A03" and p.status == ProbeStatus.FAIL for p in report.probes)


def test_admission_error_unknown_capability_id(tmp_path: Path) -> None:
    overlay = _write(tmp_path, "AGENT-OVERLAY.md", _UNKNOWN_ID_OVERLAY)
    report = run_admission(workspace=tmp_path, overlay_path=overlay)
    assert report.overall == ProbeStatus.FAIL
    assert any(p.probe_id == "A04" and p.status == ProbeStatus.FAIL for p in report.probes)


def test_conformance_happy_mocked_commands(tmp_path: Path) -> None:
    write_minimal_catalog(tmp_path)
    overlay = _write(tmp_path, "AGENT-OVERLAY.md", _COMPLETE_OVERLAY)

    def runner(command: str) -> int:
        assert command.startswith("echo ")
        assert "structural" not in command
        return 0

    report = run_conformance(
        workspace=tmp_path,
        overlay_path=overlay,
        runner=runner,
        structural_runner=lambda _argv, _cwd: 0,
    )
    assert report.overall == ProbeStatus.PASS
    assert {p.probe_id for p in report.probes} >= {"C01", "C02", "C03", "C04", "C05", "C06"}


def test_conformance_error_red_capability(tmp_path: Path) -> None:
    write_minimal_catalog(tmp_path)
    overlay = _write(tmp_path, "AGENT-OVERLAY.md", _COMPLETE_OVERLAY)

    def runner(command: str) -> int:
        return 1 if "aggregate" in command else 0

    report = run_conformance(
        workspace=tmp_path,
        overlay_path=overlay,
        runner=runner,
        structural_runner=lambda _argv, _cwd: 0,
    )
    assert report.overall == ProbeStatus.FAIL
    assert any(p.probe_id == "C04" and p.status == ProbeStatus.FAIL for p in report.probes)


def test_conformance_error_structural_scan_red(tmp_path: Path) -> None:
    write_minimal_catalog(tmp_path)
    overlay = _write(tmp_path, "AGENT-OVERLAY.md", _COMPLETE_OVERLAY)

    def structural(argv: tuple[str, ...], cwd: Path) -> int:
        del cwd
        return 4 if argv == ("ast-grep", "scan") else 0

    report = run_conformance(
        workspace=tmp_path,
        overlay_path=overlay,
        runner=lambda _cmd: 0,
        structural_runner=structural,
    )
    assert report.overall == ProbeStatus.FAIL
    assert any(p.probe_id == "C05" and p.status == ProbeStatus.FAIL for p in report.probes)
    assert any(p.probe_id == "C06" and p.status == ProbeStatus.PASS for p in report.probes)


def test_run_doctor_all_json_serializable(tmp_path: Path) -> None:
    write_minimal_catalog(tmp_path)
    overlay = _write(tmp_path, "AGENT-OVERLAY.md", _COMPLETE_OVERLAY)
    report = run_doctor(
        workspace=tmp_path,
        overlay_path=overlay,
        mode="all",
        runner=lambda _cmd: 0,
        structural_runner=lambda _argv, _cwd: 0,
    )
    payload = report.to_dict()
    json.dumps(payload)
    assert payload["overall"] == "pass"
    assert isinstance(report, DoctorReport)


def test_admission_missing_overlay_file_not_applicable(tmp_path: Path) -> None:
    report = run_admission(workspace=tmp_path, overlay_path=tmp_path / "missing.md")
    assert report.overall == ProbeStatus.NOT_APPLICABLE
    assert report.exit_code == 0
