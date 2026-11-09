from __future__ import annotations

from pathlib import Path

import pytest
from scripts.agent_doctor_lib import (
    DoctorGateError,
    ProbeStatus,
    require_admission,
    require_conformance,
)
from scripts.agent_job_lib.launcher import AdmissionDeniedError, start_job
from scripts.agent_job_lib.manifest_store import new_manifest, save_manifest
from scripts.agent_job_lib.model_check_commands import begin_implementation
from scripts.agent_job_lib.model_check_models import OMC_ADMISSION, ModelCheckError
from scripts.agent_job_lib.models import JobState, Manifest
from scripts.agent_job_lib.root_handoff import RootMoveOutcome
from scripts.structural_catalog import write_minimal_catalog

_COMPLETE = """# Overlay

| Слот | Значение |
|------|----------|
| Conformance profile | default |

## Capabilities

| Capability | Command |
|------------|---------|
| lint | echo lint |
| types | echo types |
| unit | echo unit |
| aggregate | echo aggregate |
| structural | echo structural |
"""

_INCOMPLETE = """# Overlay

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
"""

_NO_MAP = """# Overlay

| Слот | Значение |
|------|----------|
| Язык ответов | ru |
"""


def _write_overlay(root: Path, text: str) -> None:
    (root / "AGENT-OVERLAY.md").write_text(text, encoding="utf-8")


def test_require_admission_edge_not_applicable(tmp_path: Path) -> None:
    _write_overlay(tmp_path, _NO_MAP)
    report = require_admission(workspace=tmp_path)
    assert report.overall == ProbeStatus.NOT_APPLICABLE


def test_require_admission_error_incomplete(tmp_path: Path) -> None:
    _write_overlay(tmp_path, _INCOMPLETE)
    with pytest.raises(DoctorGateError):
        require_admission(workspace=tmp_path)


def test_require_conformance_happy(tmp_path: Path) -> None:
    write_minimal_catalog(tmp_path)
    _write_overlay(tmp_path, _COMPLETE)
    report = require_conformance(
        workspace=tmp_path,
        runner=lambda _cmd: 0,
        structural_runner=lambda _argv, _cwd: 0,
    )
    assert report.overall == ProbeStatus.PASS


def test_require_conformance_error_red(tmp_path: Path) -> None:
    _write_overlay(tmp_path, _COMPLETE)
    with pytest.raises(DoctorGateError):
        require_conformance(workspace=tmp_path, runner=lambda _cmd: 1)


def test_start_job_error_incomplete_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    _write_overlay(primary, _INCOMPLETE)
    common = tmp_path / "git-common"
    common.mkdir()

    class _WT:
        def add_lane(self, _primary: Path, *, slug: str, base: str | None = None) -> Path:
            raise AssertionError("must not create lane after admission fail")

    def _root_move(_path: Path) -> RootMoveOutcome:
        raise AssertionError("unreachable")

    with pytest.raises(AdmissionDeniedError):
        start_job(
            primary=primary,
            git_common_dir=common,
            slug="doc-gate-bad",
            base_ref="HEAD",
            worktree=_WT(),
            root_move=_root_move,
            dirty_paths=[],
        )


def test_start_job_calls_admission_before_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    _write_overlay(primary, _NO_MAP)
    calls: list[Path] = []

    def _fake_require(*, workspace: Path, overlay_path: Path | None = None) -> object:
        calls.append(workspace)
        from scripts.agent_doctor_lib import DoctorReport, ProbeStatus

        return DoctorReport(
            mode="admission",
            platform_on=False,
            overall=ProbeStatus.NOT_APPLICABLE,
            exit_code=0,
        )

    monkeypatch.setattr("scripts.agent_job_lib.launcher.require_admission", _fake_require)

    def _claim(*_a: object, **_k: object) -> None:
        raise RuntimeError("stop-after-admission")

    monkeypatch.setattr("scripts.agent_job_lib.launcher.claim_slug", _claim)

    class _WT:
        def add_lane(self, _primary: Path, *, slug: str, base: str | None = None) -> Path:
            raise AssertionError("unreachable")

    with pytest.raises(RuntimeError, match="stop-after-admission"):
        start_job(
            primary=primary,
            git_common_dir=tmp_path / "git-common",
            slug="doc-gate-ok",
            base_ref="HEAD",
            worktree=_WT(),
            root_move=lambda _p: RootMoveOutcome.PENDING,
            dirty_paths=[],
        )
    assert calls == [primary]


def test_begin_implementation_error_admission(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _write_overlay(workspace, _INCOMPLETE)
    common = tmp_path / "git-common"
    common.mkdir()
    job_id = "job-" + ("a" * 32)
    manifest = new_manifest(
        job_id=job_id,
        slug="doctor-adm",
        base_ref="HEAD",
        branch="agent/doctor-adm",
        worktree_path=str(workspace),
    )
    planning = Manifest(
        schema_version=manifest.schema_version,
        job_id=manifest.job_id,
        slug=manifest.slug,
        base_ref=manifest.base_ref,
        branch=manifest.branch,
        worktree_path=manifest.worktree_path,
        state=JobState.PLANNING,
        state_version=manifest.state_version,
        authorizations=dict(manifest.authorizations),
        resources=dict(manifest.resources),
    )
    save_manifest(common, planning)

    with pytest.raises(ModelCheckError) as caught:
        begin_implementation(
            git_common_dir=common,
            workspace=workspace,
            job_id=job_id,
        )
    assert caught.value.code == OMC_ADMISSION
