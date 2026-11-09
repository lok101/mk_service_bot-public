from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from scripts.agent_job import main
from scripts.agent_job_lib.manifest_store import load_manifest, save_manifest
from scripts.agent_job_lib.model_check_commands import (
    approve_report,
    begin_implementation,
    model_check_status,
    record_report,
)
from scripts.agent_job_lib.model_check_models import (
    ILLEGAL_TRANSITION,
    OMC_CONFLICT,
    OMC_CORRUPT,
    OMC_FINDINGS,
    OMC_MISSING,
    OMC_SCHEMA,
    OMC_STALE,
    OMC_UNAVAILABLE,
    ModelCheckError,
)
from scripts.agent_job_lib.model_check_store import checks_root
from scripts.agent_job_lib.models import JOB_STATES, JobState, Manifest

_JOB_ID = "job-abc"
_REPORT_ID = "omc-11111111-1111-1111-1111-111111111111"
_OTHER_REPORT_ID = "omc-22222222-2222-2222-2222-222222222222"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    common = tmp_path / "common"
    repo.mkdir()
    common.mkdir()
    model = repo / "docs" / "company-operating-model"
    model.mkdir(parents=True)
    (model / "roles.md").write_text("role alpha\n", encoding="utf-8")
    (repo / "docs" / "specs").mkdir()
    (repo / "docs" / "specs" / "design.md").write_text("spec\n", encoding="utf-8")
    (repo / "docs" / "plans").mkdir()
    (repo / "docs" / "plans" / "plan.md").write_text("plan\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.email", "model-check@example.com")
    _git(repo, "config", "user.name", "model-check")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    return repo, common


def _seed(common: Path, repo: Path, *, state: JobState = JobState.PLANNING) -> None:
    manifest = Manifest(
        schema_version=1,
        job_id=_JOB_ID,
        slug="case",
        base_ref="abc",
        branch="agent/case",
        worktree_path=str(repo),
        state=state,
        state_version=0,
        authorizations={},
        resources={},
    )
    save_manifest(common, manifest)


def _body(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "analysis_result": "clear",
        "findings": [],
        "retained_findings": [],
        "used_stable_ids": ["role.technician"],
    }
    payload.update(overrides)
    return payload


def _record(
    repo: Path,
    common: Path,
    *,
    body: dict[str, object] | None = None,
    report_id: str | None = _REPORT_ID,
    mode: str = "agent",
) -> dict[str, object]:
    return record_report(
        git_common_dir=common,
        workspace=repo,
        job_id=_JOB_ID,
        spec="docs/specs/design.md",
        plan="docs/plans/plan.md",
        body=body if body is not None else _body(),
        mode=mode,
        report_id=report_id,
    )


def _report_files(common: Path) -> list[Path]:
    root = checks_root(common) / "reports"
    if not root.exists():
        return []
    return list(root.rglob("*.json"))


def test_job_states_still_include_implementing() -> None:
    assert "implementing" in JOB_STATES


def test_record_clear_report_roundtrip(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo)
    stored = _record(repo, common)
    assert stored["report_id"] == _REPORT_ID
    assert stored["analysis_result"] == "clear"
    assert stored["mode"] == "agent"
    assert "transcript" not in stored
    manifest = load_manifest(common, _JOB_ID)
    block = manifest.authorizations["model_check"]
    assert block["verdict"] == "pending"
    assert block["authorization_id"] is None
    assert block["inputs_digest"] == stored["inputs_digest"]


def test_record_same_id_and_payload_is_idempotent(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo)
    first = _record(repo, common)
    second = _record(repo, common)
    assert second["report_id"] == first["report_id"]
    assert len(_report_files(common)) == 1


def test_record_same_body_returns_existing_id(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo)
    first = _record(repo, common, report_id=_REPORT_ID)
    second = _record(repo, common, report_id=_OTHER_REPORT_ID)
    assert second["report_id"] == first["report_id"]
    assert len(_report_files(common)) == 1


def test_record_same_id_different_payload_conflicts(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo)
    _record(repo, common)
    changed = _body(
        analysis_result="blocked",
        findings=[{"stable_id": "gap.slot", "kind": "gap", "summary": "hole"}],
    )
    with pytest.raises(ModelCheckError) as caught:
        _record(repo, common, body=changed)
    assert caught.value.code == OMC_CONFLICT
    assert len(_report_files(common)) == 1


def test_record_rejects_unknown_field(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo)
    with pytest.raises(ModelCheckError) as caught:
        _record(repo, common, body={**_body(), "transcript": "chat"})
    assert caught.value.code == OMC_SCHEMA
    assert _report_files(common) == []


def test_record_manual_mode_same_contract(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo)
    stored = _record(repo, common, mode="manual")
    assert stored["mode"] == "manual"
    assert stored["schema_version"] == 1
    assert set(stored) >= {"findings", "inputs_digest", "used_stable_ids"}


def test_record_missing_declared_path_writes_nothing(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo)
    (repo / "docs" / "plans" / "plan.md").unlink()
    with pytest.raises(ModelCheckError) as caught:
        _record(repo, common)
    assert caught.value.code == OMC_MISSING
    assert _report_files(common) == []


def test_begin_clear_ok_opens_implementing(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo)
    report = _record(repo, common)
    approve_report(
        git_common_dir=common,
        workspace=repo,
        job_id=_JOB_ID,
        report_id=str(report["report_id"]),
        decision="ok",
        reason="owner accepted",
    )
    opened = begin_implementation(git_common_dir=common, workspace=repo, job_id=_JOB_ID)
    assert opened["state"] == "implementing"
    manifest = load_manifest(common, _JOB_ID)
    assert manifest.state is JobState.IMPLEMENTING
    assert manifest.authorizations["model_check"]["verdict"] == "ok"


def test_begin_not_applicable_opens_implementing(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo)
    report = _record(repo, common)
    approve_report(
        git_common_dir=common,
        workspace=repo,
        job_id=_JOB_ID,
        report_id=str(report["report_id"]),
        decision="not_applicable",
        reason="process job",
    )
    opened = begin_implementation(git_common_dir=common, workspace=repo, job_id=_JOB_ID)
    assert opened["state"] == "implementing"
    assert load_manifest(common, _JOB_ID).authorizations["model_check"]["verdict"] == (
        "not_applicable"
    )


def test_approve_same_decision_is_idempotent(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo)
    report = _record(repo, common)
    kwargs = {
        "git_common_dir": common,
        "workspace": repo,
        "job_id": _JOB_ID,
        "report_id": str(report["report_id"]),
        "decision": "ok",
        "reason": "owner accepted",
    }
    first = approve_report(**kwargs)
    second = approve_report(**kwargs)
    assert second["authorization_id"] == first["authorization_id"]
    root = checks_root(common) / "authorizations"
    assert len(list(root.rglob("*.json"))) == 1


def test_begin_missing_report_blocks_without_implementing(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo)
    with pytest.raises(ModelCheckError) as caught:
        begin_implementation(git_common_dir=common, workspace=repo, job_id=_JOB_ID)
    assert caught.value.code == OMC_MISSING
    manifest = load_manifest(common, _JOB_ID)
    assert manifest.state is JobState.BLOCKED
    assert manifest.authorizations["block_reason"] == "model_check_required"


def test_approve_ok_on_blocked_report_writes_no_authorization(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo)
    report = _record(
        repo,
        common,
        body=_body(
            analysis_result="blocked",
            findings=[{"stable_id": "gap.slot", "kind": "gap", "summary": "hole"}],
        ),
    )
    with pytest.raises(ModelCheckError) as caught:
        approve_report(
            git_common_dir=common,
            workspace=repo,
            job_id=_JOB_ID,
            report_id=str(report["report_id"]),
            decision="ok",
            reason="ignore holes",
        )
    assert caught.value.code == OMC_FINDINGS
    assert not (checks_root(common) / "authorizations").exists()
    manifest = load_manifest(common, _JOB_ID)
    assert manifest.state is JobState.BLOCKED
    assert manifest.authorizations["block_reason"] == "model_check_findings"
    assert manifest.state is not JobState.IMPLEMENTING


def test_stale_model_file_blocks_begin(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo)
    report = _record(repo, common)
    approve_report(
        git_common_dir=common,
        workspace=repo,
        job_id=_JOB_ID,
        report_id=str(report["report_id"]),
        decision="ok",
        reason="owner accepted",
    )
    model = repo / "docs" / "company-operating-model" / "roles.md"
    model.write_text("role beta\n", encoding="utf-8")
    status = model_check_status(git_common_dir=common, workspace=repo, job_id=_JOB_ID)
    assert status["stale"] is True
    with pytest.raises(ModelCheckError) as caught:
        begin_implementation(git_common_dir=common, workspace=repo, job_id=_JOB_ID)
    assert caught.value.code == OMC_STALE
    manifest = load_manifest(common, _JOB_ID)
    assert manifest.state is JobState.BLOCKED
    assert manifest.authorizations["block_reason"] == "model_check_stale"


def test_corrupt_index_is_fail_closed(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo)
    root = checks_root(common)
    root.mkdir()
    (root / "index.jsonl").write_text(
        json.dumps(
            {
                "kind": "report",
                "id": _REPORT_ID,
                "path": "reports/2026-10-16/missing.json",
                "inputs_digest": "abc",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ModelCheckError) as caught:
        model_check_status(git_common_dir=common, workspace=repo, job_id=_JOB_ID)
    assert caught.value.code == OMC_CORRUPT
    with pytest.raises(ModelCheckError):
        begin_implementation(git_common_dir=common, workspace=repo, job_id=_JOB_ID)
    manifest = load_manifest(common, _JOB_ID)
    assert manifest.state is JobState.BLOCKED
    assert manifest.authorizations["block_reason"] == "model_check_corrupt"
    assert manifest.state is not JobState.IMPLEMENTING


def test_store_unavailable_when_root_is_file(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo)
    (common / "operating-model-checks").write_text("not a directory", encoding="utf-8")
    with pytest.raises(ModelCheckError) as caught:
        _record(repo, common)
    assert caught.value.code == OMC_UNAVAILABLE
    with pytest.raises(ModelCheckError):
        begin_implementation(git_common_dir=common, workspace=repo, job_id=_JOB_ID)
    assert load_manifest(common, _JOB_ID).state is not JobState.IMPLEMENTING


def test_begin_from_lane_ready_does_not_change_state(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo, state=JobState.LANE_READY)
    with pytest.raises(ModelCheckError) as caught:
        begin_implementation(git_common_dir=common, workspace=repo, job_id=_JOB_ID)
    assert caught.value.code == ILLEGAL_TRANSITION
    assert load_manifest(common, _JOB_ID).state is JobState.LANE_READY


def test_approve_does_not_clear_foreign_block_reason(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo, state=JobState.BLOCKED)
    manifest = load_manifest(common, _JOB_ID)
    manifest.authorizations["block_reason"] = "blocked_dirty_gate"
    save_manifest(common, manifest)
    report = _record(repo, common)
    approve_report(
        git_common_dir=common,
        workspace=repo,
        job_id=_JOB_ID,
        report_id=str(report["report_id"]),
        decision="ok",
        reason="owner accepted",
    )
    updated = load_manifest(common, _JOB_ID)
    assert updated.state is JobState.BLOCKED
    assert updated.authorizations["block_reason"] == "blocked_dirty_gate"
    assert updated.authorizations["model_check"]["verdict"] == "ok"


def test_status_require_implementing_rejects_planning(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo)
    report = _record(repo, common)
    approve_report(
        git_common_dir=common,
        workspace=repo,
        job_id=_JOB_ID,
        report_id=str(report["report_id"]),
        decision="ok",
        reason="owner accepted",
    )
    with pytest.raises(ModelCheckError) as caught:
        model_check_status(
            git_common_dir=common,
            workspace=repo,
            job_id=_JOB_ID,
            require_implementing=True,
        )
    assert caught.value.code == OMC_MISSING
    assert load_manifest(common, _JOB_ID).state is JobState.PLANNING


def test_cli_record_prints_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo)
    monkeypatch.setenv("AGENT_JOB_GIT_COMMON_DIR", str(common))
    monkeypatch.chdir(repo)
    code = main(
        [
            "model-check",
            "record",
            "--job-id",
            _JOB_ID,
            "--spec",
            "docs/specs/design.md",
            "--plan",
            "docs/plans/plan.md",
            "--body",
            json.dumps(_body()),
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert str(payload["report_id"]).startswith("omc-")


def test_require_implementing_rejects_missing_authorization(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo, state=JobState.IMPLEMENTING)
    with pytest.raises(ModelCheckError) as caught:
        model_check_status(
            git_common_dir=common,
            workspace=repo,
            job_id=_JOB_ID,
            require_implementing=True,
        )
    assert caught.value.code == OMC_MISSING


def test_require_implementing_accepts_fresh_ok(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo)
    report = _record(repo, common)
    approve_report(
        git_common_dir=common,
        workspace=repo,
        job_id=_JOB_ID,
        report_id=str(report["report_id"]),
        decision="ok",
        reason="owner accepted",
    )
    begin_implementation(git_common_dir=common, workspace=repo, job_id=_JOB_ID)
    status = model_check_status(
        git_common_dir=common,
        workspace=repo,
        job_id=_JOB_ID,
        require_implementing=True,
    )
    assert status["ok"] is True
    assert status["stale"] is False


def test_begin_blocked_report_without_approval_is_findings(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo)
    _record(
        repo,
        common,
        body=_body(
            analysis_result="blocked",
            findings=[{"stable_id": "gap.slot", "kind": "gap", "summary": "hole"}],
        ),
    )
    with pytest.raises(ModelCheckError) as caught:
        begin_implementation(git_common_dir=common, workspace=repo, job_id=_JOB_ID)
    assert caught.value.code == OMC_FINDINGS
    manifest = load_manifest(common, _JOB_ID)
    assert manifest.state is JobState.BLOCKED
    assert manifest.authorizations["block_reason"] == "model_check_findings"


def test_same_id_conflicting_body_does_not_reuse_other_report(tmp_path: Path) -> None:
    repo, common = _init_repo(tmp_path)
    _seed(common, repo)
    _record(repo, common, report_id=_REPORT_ID)
    blocked = _body(
        analysis_result="blocked",
        findings=[{"stable_id": "gap.slot", "kind": "gap", "summary": "hole"}],
    )
    _record(repo, common, report_id=_OTHER_REPORT_ID, body=blocked)
    with pytest.raises(ModelCheckError) as caught:
        _record(repo, common, report_id=_REPORT_ID, body=blocked)
    assert caught.value.code == OMC_CONFLICT
    assert len(_report_files(common)) == 2
    assert load_manifest(common, _JOB_ID).authorizations["model_check"]["report_id"] == (
        _OTHER_REPORT_ID
    )
