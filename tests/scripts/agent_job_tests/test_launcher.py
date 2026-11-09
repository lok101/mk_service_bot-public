from __future__ import annotations

from pathlib import Path

import pytest
from scripts.agent_job import main as agent_job_main
from scripts.agent_job_lib.launcher import (
    DuplicateJobError,
    JobNotFoundError,
    abort_job,
    block_job,
    resume_job,
    start_job,
    status_job,
)
from scripts.agent_job_lib.manifest_store import load_manifest
from scripts.agent_job_lib.models import JobState
from scripts.agent_job_lib.resources import claim_slug
from scripts.agent_job_lib.root_handoff import RootMoveOutcome, default_root_move


class _FakeWorktree:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.calls: list[tuple[str, str | None]] = []

    def add_lane(self, primary: Path, *, slug: str, base: str | None = None) -> Path:
        self.calls.append((slug, base))
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path


def test_start_job_creates_manifest_and_lane(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    common = tmp_path / "common.git"
    common.mkdir()
    wt = _FakeWorktree(tmp_path / "lane")
    result = start_job(
        primary=primary,
        git_common_dir=common,
        slug="demo-job",
        base_ref="abc123",
        worktree=wt,
        root_move=lambda path: RootMoveOutcome.OK,
        dirty_paths=[],
    )
    assert result["slug"] == "demo-job"
    assert result["branch"] == "agent/demo-job"
    assert Path(result["worktree_path"]) == wt.path
    assert "job_id" in result
    assert result["root_handoff"] == RootMoveOutcome.OK.value
    m = load_manifest(common, result["job_id"])
    assert m.state is JobState.LANE_READY
    assert m.base_ref == "abc123"
    assert m.resources["compose_project"].startswith("mk_service_bot_")
    assert wt.calls == [("demo-job", "abc123")]


def test_start_job_rejects_duplicate_slug(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    common = tmp_path / "common.git"
    common.mkdir()
    wt = _FakeWorktree(tmp_path / "lane")
    start_job(
        primary=primary,
        git_common_dir=common,
        slug="dup",
        base_ref="abc",
        worktree=wt,
        root_move=lambda path: RootMoveOutcome.OK,
        dirty_paths=[],
    )
    with pytest.raises(DuplicateJobError, match="slug"):
        start_job(
            primary=primary,
            git_common_dir=common,
            slug="dup",
            base_ref="abc",
            worktree=_FakeWorktree(tmp_path / "lane2"),
            root_move=lambda path: RootMoveOutcome.OK,
            dirty_paths=[],
        )


def test_start_job_default_root_move_pending(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    common = tmp_path / "common.git"
    common.mkdir()
    wt_path = tmp_path / "lane"
    wt = _FakeWorktree(wt_path)
    result = start_job(
        primary=primary,
        git_common_dir=common,
        slug="pending-handoff",
        base_ref="abc",
        worktree=wt,
        root_move=default_root_move,
        dirty_paths=[],
    )
    assert result["state"] == JobState.LANE_READY.value
    assert result["root_handoff"] == RootMoveOutcome.PENDING.value
    assert "block_reason" not in result
    m = load_manifest(common, result["job_id"])
    assert m.state is JobState.LANE_READY
    assert m.authorizations["root_handoff"] == RootMoveOutcome.PENDING.value


def test_root_handoff_failed_blocks(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    common = tmp_path / "common.git"
    common.mkdir()
    wt_path = tmp_path / "lane"
    wt = _FakeWorktree(wt_path)
    result = start_job(
        primary=primary,
        git_common_dir=common,
        slug="handoff",
        base_ref="abc",
        worktree=wt,
        root_move=lambda path: RootMoveOutcome.FAILED,
        dirty_paths=[],
    )
    assert result["state"] == JobState.BLOCKED.value
    assert result["block_reason"] == "blocked_root_handoff"
    assert result["worktree_path"] == str(wt_path)
    m = load_manifest(common, result["job_id"])
    assert m.state is JobState.BLOCKED


def test_status_resume_abort(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    common = tmp_path / "common.git"
    common.mkdir()
    wt = _FakeWorktree(tmp_path / "lane")
    started = start_job(
        primary=primary,
        git_common_dir=common,
        slug="flow",
        base_ref="abc",
        worktree=wt,
        root_move=lambda path: RootMoveOutcome.FAILED,
        dirty_paths=[],
    )
    st = status_job(common, started["job_id"])
    assert st["state"] == JobState.BLOCKED.value
    resumed = resume_job(
        common,
        started["job_id"],
        resume_to=JobState.LANE_READY,
        worktree_exists=True,
    )
    assert resumed["state"] == JobState.LANE_READY.value
    aborted = abort_job(common, started["job_id"], reason="stop")
    assert aborted["state"] == JobState.ABORTED.value
    with pytest.raises(JobNotFoundError):
        status_job(common, "job-missing000000000000000000000000")


def test_abort_job_from_blocked_root_handoff(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    common = tmp_path / "common.git"
    common.mkdir()
    wt = _FakeWorktree(tmp_path / "lane")
    started = start_job(
        primary=primary,
        git_common_dir=common,
        slug="abort-me",
        base_ref="abc",
        worktree=wt,
        root_move=lambda path: RootMoveOutcome.FAILED,
        dirty_paths=[],
    )
    assert started["state"] == JobState.BLOCKED.value
    aborted = abort_job(common, started["job_id"], reason="give-up")
    assert aborted["state"] == JobState.ABORTED.value
    # slug reclaimable after abort
    claim_slug(common, "abort-me", job_id="job-other000000000000000000000000")


def test_block_job_root_handoff(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    common = tmp_path / "common.git"
    common.mkdir()
    wt = _FakeWorktree(tmp_path / "lane")
    started = start_job(
        primary=primary,
        git_common_dir=common,
        slug="block-me",
        base_ref="abc",
        worktree=wt,
        root_move=default_root_move,
        dirty_paths=[],
    )
    assert started["state"] == JobState.LANE_READY.value
    blocked = block_job(common, started["job_id"], reason="blocked_root_handoff")
    assert blocked["state"] == JobState.BLOCKED.value
    assert blocked["block_reason"] == "blocked_root_handoff"
    m = load_manifest(common, started["job_id"])
    assert m.state is JobState.BLOCKED
    assert m.authorizations["root_handoff"] == RootMoveOutcome.FAILED.value


def test_block_job_rejects_unknown_reason(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    common = tmp_path / "common.git"
    common.mkdir()
    wt = _FakeWorktree(tmp_path / "lane")
    started = start_job(
        primary=primary,
        git_common_dir=common,
        slug="bad-reason",
        base_ref="abc",
        worktree=wt,
        root_move=default_root_move,
        dirty_paths=[],
    )
    with pytest.raises(ValueError, match="unsupported block reason"):
        block_job(common, started["job_id"], reason="blocked_dirty_gate")


def test_cli_status_missing_returns_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    common = tmp_path / "g"
    common.mkdir()
    monkeypatch.setenv("AGENT_JOB_GIT_COMMON_DIR", str(common))
    code = agent_job_main(["status", "--job-id", "job-deadbeefcafebabe0123456789abcdef"])
    assert code != 0


def test_start_job_adopts_ui_preview_into_lane(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    common = tmp_path / "common.git"
    common.mkdir()
    demo = "docs/ui-demos/2026-10-09-x/index.html"
    path = primary / demo
    path.parent.mkdir(parents=True)
    path.write_bytes(b"<html>preview</html>")
    wt = _FakeWorktree(tmp_path / "lane")

    result = start_job(
        primary=primary,
        git_common_dir=common,
        slug="adopt-demo",
        base_ref="abc",
        worktree=wt,
        root_move=lambda path: RootMoveOutcome.OK,
        dirty_paths=[demo],
        is_untracked=lambda _p: True,
        head_blob_reader=lambda _p: None,
    )

    assert result["state"] == JobState.LANE_READY.value
    assert (wt.path / demo).read_bytes() == b"<html>preview</html>"
    assert not path.exists()


def test_start_job_dirty_gate_blocks_and_leaves_lane(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    common = tmp_path / "common.git"
    common.mkdir()
    leftover = "docs/specs/leftover-design.md"
    path = primary / leftover
    path.parent.mkdir(parents=True)
    path.write_bytes(b"# leftover\n")
    wt_path = tmp_path / "lane"
    wt = _FakeWorktree(wt_path)

    result = start_job(
        primary=primary,
        git_common_dir=common,
        slug="dirty-gate",
        base_ref="abc",
        worktree=wt,
        root_move=lambda path: RootMoveOutcome.OK,
        dirty_paths=[leftover],
        is_untracked=lambda _p: True,
        head_blob_reader=lambda _p: None,
    )

    assert result["state"] == JobState.BLOCKED.value
    assert result["block_reason"] == "blocked_dirty_gate"
    assert leftover in result["dirty_paths"]
    assert wt_path.is_dir()
    assert path.exists()
    m = load_manifest(common, result["job_id"])
    assert m.state is JobState.BLOCKED
    # slug still claimed (lane left in place)
    with pytest.raises(DuplicateJobError):
        start_job(
            primary=primary,
            git_common_dir=common,
            slug="dirty-gate",
            base_ref="abc",
            worktree=_FakeWorktree(tmp_path / "lane2"),
            root_move=lambda path: RootMoveOutcome.OK,
            dirty_paths=[],
        )
