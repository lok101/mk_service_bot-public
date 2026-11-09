from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import pytest
from scripts.agent_journal_lib.envelope import JournalEmitError
from scripts.agent_journal_lib.gate_emit import (
    emit_gate_and_probes,
    missing_probe_ids,
)
from scripts.agent_journal_lib.home_paths import (
    JournalStoreUnavailableError,
    default_job_events_path,
)
from scripts.agent_journal_lib.keys import EMITTER_DOCTOR_ADMISSION


class _ProbeStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class _ProbeResult:
    probe_id: str
    status: _ProbeStatus
    message: str


@dataclass(frozen=True, slots=True)
class _DoctorReport:
    mode: str
    platform_on: bool
    overall: _ProbeStatus
    exit_code: int
    probes: tuple[_ProbeResult, ...] = field(default_factory=tuple)
    profile: str | None = None


def _write_kernel_ref(product: Path, home: Path) -> None:
    product.mkdir(parents=True, exist_ok=True)
    (product / "kernel_ref").write_text(
        json.dumps({"home": str(home), "ref": "test", "mount": {}}),
        encoding="utf-8",
    )
    (product / "AGENT-OVERLAY.md").write_text("# Overlay mk_service_bot\n", encoding="utf-8")


def test_emit_gate_and_probes_happy(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    home.mkdir()
    product = tmp_path / "mk"
    _write_kernel_ref(product, home)
    job_id = "job-aabbcc"
    entry = tmp_path / "doctor_wrapper.py"
    entry.write_text("wrapper\n", encoding="utf-8")
    report = _DoctorReport(
        mode="admission",
        platform_on=True,
        overall=_ProbeStatus.PASS,
        exit_code=0,
        probes=(
            _ProbeResult("A01", _ProbeStatus.PASS, "ok"),
            _ProbeResult("A02", _ProbeStatus.PASS, "ok"),
        ),
    )

    emit_gate_and_probes(
        product,
        job_id=job_id,
        gate_name="gate.admission",
        report=report,
        emitter_id=EMITTER_DOCTOR_ADMISSION,
        emitter_path=entry,
    )

    lines = (
        default_job_events_path(product, job_id).read_text(encoding="utf-8").strip().splitlines()
    )
    assert len(lines) == 3
    gate = json.loads(lines[0])
    assert gate["name"] == "gate.admission"
    assert gate["outcome"] == "success"
    assert gate["attrs"]["emitter_id"] == EMITTER_DOCTOR_ADMISSION
    probes = [json.loads(line) for line in lines[1:]]
    assert [p["name"] for p in probes] == ["check.probe", "check.probe"]
    assert {p["attrs"]["probe_id"] for p in probes} == {"A01", "A02"}
    assert all(p["attrs"]["status"] == "pass" for p in probes)


def test_missing_probe_ids_edge_detects_hole(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    home.mkdir()
    product = tmp_path / "mk"
    _write_kernel_ref(product, home)
    job_id = "job-ccddee"
    entry = tmp_path / "doctor_wrapper.py"
    entry.write_text("wrapper\n", encoding="utf-8")
    report = _DoctorReport(
        mode="admission",
        platform_on=True,
        overall=_ProbeStatus.PASS,
        exit_code=0,
        probes=(
            _ProbeResult("A01", _ProbeStatus.PASS, "ok"),
            _ProbeResult("A03", _ProbeStatus.PASS, "ok"),
        ),
    )
    emit_gate_and_probes(
        product,
        job_id=job_id,
        gate_name="gate.admission",
        report=_DoctorReport(
            mode="admission",
            platform_on=True,
            overall=_ProbeStatus.PASS,
            exit_code=0,
            probes=(_ProbeResult("A01", _ProbeStatus.PASS, "ok"),),
        ),
        emitter_id=EMITTER_DOCTOR_ADMISSION,
        emitter_path=entry,
    )
    holes = missing_probe_ids(product, job_id=job_id, report=report)
    assert holes == ["A03"]


def test_emit_gate_fail_closed_home_down(tmp_path: Path) -> None:
    product = tmp_path / "bare"
    product.mkdir()
    entry = tmp_path / "doctor_wrapper.py"
    entry.write_text("wrapper\n", encoding="utf-8")
    report = _DoctorReport(
        mode="admission",
        platform_on=True,
        overall=_ProbeStatus.PASS,
        exit_code=0,
        probes=(_ProbeResult("A01", _ProbeStatus.PASS, "ok"),),
    )
    with pytest.raises((JournalStoreUnavailableError, JournalEmitError, OSError)):
        emit_gate_and_probes(
            product,
            job_id="job-ff0011",
            gate_name="gate.admission",
            report=report,
            emitter_id=EMITTER_DOCTOR_ADMISSION,
            emitter_path=entry,
        )


def test_emit_gate_fail_closed_unknown_gate_name(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    home.mkdir()
    product = tmp_path / "mk"
    _write_kernel_ref(product, home)
    entry = tmp_path / "doctor_wrapper.py"
    entry.write_text("wrapper\n", encoding="utf-8")
    report = _DoctorReport(
        mode="admission",
        platform_on=True,
        overall=_ProbeStatus.FAIL,
        exit_code=1,
        probes=(),
    )
    with pytest.raises(JournalEmitError, match="unknown event name"):
        emit_gate_and_probes(
            product,
            job_id="job-112233",
            gate_name="gate.notreal",
            report=report,
            emitter_id=EMITTER_DOCTOR_ADMISSION,
            emitter_path=entry,
        )


def test_host_require_admission_emits_when_job_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "agent_platform"
    home.mkdir()
    product = tmp_path / "mk"
    _write_kernel_ref(product, home)
    job_id = "job-445566"

    class _FakeMod:
        ProbeStatus = _ProbeStatus

        class DoctorGateError(RuntimeError):
            def __init__(self, report: Any) -> None:
                super().__init__("denied")
                self.report = report

        @staticmethod
        def require_admission(
            *, workspace: Path, overlay_path: Path | None = None
        ) -> _DoctorReport:
            return _DoctorReport(
                mode="admission",
                platform_on=True,
                overall=_ProbeStatus.PASS,
                exit_code=0,
                probes=(_ProbeResult("A01", _ProbeStatus.PASS, "ok"),),
            )

    monkeypatch.setattr(
        "scripts.agent_doctor_lib.load_home_doctor_module",
        lambda *, workspace=None: _FakeMod(),
    )
    from scripts.agent_doctor_lib import require_admission

    report = require_admission(workspace=product, job_id=job_id)
    assert report.overall == _ProbeStatus.PASS
    lines = (
        default_job_events_path(product, job_id).read_text(encoding="utf-8").strip().splitlines()
    )
    names = [json.loads(line)["name"] for line in lines]
    assert names[0] == "gate.admission"
    assert "check.probe" in names
