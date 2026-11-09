from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.agent_job_lib.manifest_store import (
    ManifestCorruptError,
    ManifestSchemaError,
    append_event,
    load_manifest,
    new_manifest,
    save_manifest,
)
from scripts.agent_job_lib.models import JOB_STATES, JobState
from scripts.agent_job_lib.paths import agent_jobs_root, job_dir


def test_job_states_match_spec_order() -> None:
    assert list(JOB_STATES) == [
        "reserved",
        "lane_ready",
        "designing",
        "planning",
        "implementing",
        "reviewing",
        "verifying",
        "committing",
        "ready_for_closeout",
        "blocked",
        "failed",
        "aborted",
    ]
    assert JobState.RESERVED.value == "reserved"


def test_job_dir_under_git_common_agent_jobs(tmp_path: Path) -> None:
    common = tmp_path / "common.git"
    common.mkdir()
    root = agent_jobs_root(common)
    assert root == common / "agent-jobs"
    path = job_dir(common, "job-deadbeef")
    assert path == common / "agent-jobs" / "job-deadbeef"


def test_job_dir_rejects_empty_id() -> None:
    with pytest.raises(ValueError, match="job_id"):
        job_dir(Path("."), "")


def test_job_dir_rejects_path_traversal() -> None:
    with pytest.raises(ValueError, match="job_id"):
        job_dir(Path("."), "..")
    with pytest.raises(ValueError, match="job_id"):
        job_dir(Path("."), "job-a/b")


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    common = tmp_path / "g"
    common.mkdir()
    m = new_manifest(
        job_id="job-1",
        slug="demo",
        base_ref="abc",
        branch="agent/demo",
        worktree_path=str(tmp_path / "wt"),
    )
    save_manifest(common, m)
    loaded = load_manifest(common, "job-1")
    assert loaded.job_id == "job-1"
    assert loaded.state == JobState.RESERVED
    assert loaded.state_version == 1
    assert (common / "agent-jobs" / "job-1" / "manifest.json").is_file()


def test_save_increments_state_version(tmp_path: Path) -> None:
    common = tmp_path / "g"
    common.mkdir()
    m = new_manifest(
        job_id="job-1",
        slug="demo",
        base_ref="abc",
        branch="agent/demo",
        worktree_path=str(tmp_path / "wt"),
    )
    save_manifest(common, m)
    m2 = load_manifest(common, "job-1")
    m2.state = JobState.LANE_READY
    save_manifest(common, m2)
    assert load_manifest(common, "job-1").state_version == 2


def test_corrupt_manifest_raises(tmp_path: Path) -> None:
    common = tmp_path / "g"
    common.mkdir()
    m = new_manifest(
        job_id="job-1",
        slug="demo",
        base_ref="abc",
        branch="agent/demo",
        worktree_path=str(tmp_path / "wt"),
    )
    save_manifest(common, m)
    path = common / "agent-jobs" / "job-1" / "manifest.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ManifestCorruptError):
        load_manifest(common, "job-1")


def test_newer_schema_version_fail_closed(tmp_path: Path) -> None:
    common = tmp_path / "g"
    common.mkdir()
    m = new_manifest(
        job_id="job-1",
        slug="demo",
        base_ref="abc",
        branch="agent/demo",
        worktree_path=str(tmp_path / "wt"),
    )
    save_manifest(common, m)
    path = common / "agent-jobs" / "job-1" / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema_version"] = 99
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ManifestSchemaError, match="schema"):
        load_manifest(common, "job-1")


def test_append_event_is_append_only(tmp_path: Path) -> None:
    import json

    from scripts.agent_journal_lib.home_paths import default_job_events_path

    common = tmp_path / "g"
    common.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    product = tmp_path / "mk"
    product.mkdir()
    (product / "kernel_ref").write_text(
        json.dumps({"home": str(home), "ref": "t", "mount": {}}),
        encoding="utf-8",
    )
    (product / "AGENT-OVERLAY.md").write_text("# Overlay mk\n", encoding="utf-8")
    m = new_manifest(
        job_id="job-1",
        slug="demo",
        base_ref="abc",
        branch="agent/demo",
        worktree_path=str(tmp_path / "wt"),
    )
    save_manifest(common, m)
    append_event(
        common,
        "job-1",
        {"kind": "state", "state": "reserved"},
        product_root=product,
    )
    append_event(
        common,
        "job-1",
        {"kind": "state", "state": "lane_ready"},
        product_root=product,
    )
    lines = (
        default_job_events_path(product, "job-1")
        .read_text(encoding="utf-8")
        .strip()
        .splitlines()
    )
    assert len(lines) == 2


def test_save_rejects_newer_schema_on_disk(tmp_path: Path) -> None:
    common = tmp_path / "g"
    common.mkdir()
    m = new_manifest(
        job_id="job-1",
        slug="demo",
        base_ref="abc",
        branch="agent/demo",
        worktree_path=str(tmp_path / "wt"),
    )
    save_manifest(common, m)
    path = common / "agent-jobs" / "job-1" / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema_version"] = 99
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ManifestSchemaError, match="schema"):
        save_manifest(common, m)


def test_save_rejects_corrupt_on_disk(tmp_path: Path) -> None:
    common = tmp_path / "g"
    common.mkdir()
    m = new_manifest(
        job_id="job-1",
        slug="demo",
        base_ref="abc",
        branch="agent/demo",
        worktree_path=str(tmp_path / "wt"),
    )
    save_manifest(common, m)
    path = common / "agent-jobs" / "job-1" / "manifest.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ManifestCorruptError):
        save_manifest(common, m)
