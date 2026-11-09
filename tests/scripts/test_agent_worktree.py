from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from scripts.agent_worktree import LaneSlugError, validate_lane_slug


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_primary(tmp_path: Path) -> Path:
    primary = tmp_path / "mk_service_bot"
    primary.mkdir()
    _git(primary, "init")
    _git(primary, "config", "user.email", "lane@example.invalid")
    _git(primary, "config", "user.name", "Lane Test")
    (primary / "tracked.txt").write_text("ok\n", encoding="utf-8")
    _git(primary, "add", "tracked.txt")
    _git(primary, "commit", "-m", "base")
    return primary


@pytest.mark.parametrize(
    "slug",
    ["", "A", "ab_c", "-ab", "a" * 42, "Has Capitals"],
)
def test_validate_lane_slug_rejects_invalid(slug: str) -> None:
    with pytest.raises(LaneSlugError):
        validate_lane_slug(slug)


def test_validate_lane_slug_accepts_ok() -> None:
    assert validate_lane_slug("shelves") == "shelves"
    assert validate_lane_slug("lok-274") == "lok-274"


def test_add_creates_lane_from_head_without_primary_dirty(tmp_path: Path) -> None:
    from scripts.agent_worktree import add_lane

    primary = _init_primary(tmp_path)
    (primary / "dirty.txt").write_text("secret\n", encoding="utf-8")
    head = _git(primary, "rev-parse", "HEAD").stdout.strip()
    lane = add_lane(primary, slug="shelves")
    assert lane.is_dir()
    assert lane.name == "shelves"
    assert lane.parent.name == "mk_service_bot-wt"
    assert not (lane / "dirty.txt").exists()
    assert (lane / "tracked.txt").read_text(encoding="utf-8") == "ok\n"
    branch = _git(lane, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert branch == "agent/shelves"
    assert _git(lane, "rev-parse", "HEAD").stdout.strip() == head


def test_add_rejects_existing_path_or_branch(tmp_path: Path) -> None:
    from scripts.agent_worktree import LaneExistsError, add_lane

    primary = _init_primary(tmp_path)
    add_lane(primary, slug="shelves")
    with pytest.raises(LaneExistsError):
        add_lane(primary, slug="shelves")


def test_add_rejects_non_commit_base(tmp_path: Path) -> None:
    from scripts.agent_worktree import LaneBaseError, add_lane

    primary = _init_primary(tmp_path)
    with pytest.raises(LaneBaseError):
        add_lane(primary, slug="xy", base="not-a-commit")


def test_add_rejects_detached_head_without_base(tmp_path: Path) -> None:
    from scripts.agent_worktree import LaneBaseError, add_lane

    primary = _init_primary(tmp_path)
    _git(primary, "checkout", "--detach")
    with pytest.raises(LaneBaseError, match="--base"):
        add_lane(primary, slug="shelves")
    assert not (primary.parent / "mk_service_bot-wt" / "shelves").exists()


def test_status_marks_agent_branches(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts.agent_worktree import add_lane, status_lanes

    primary = _init_primary(tmp_path)
    add_lane(primary, slug="shelves")
    code = status_lanes(primary)
    assert code == 0
    out = capsys.readouterr().out
    assert "agent/shelves" in out
    assert "[lane]" in out


def test_remove_rejects_dirty_lane(tmp_path: Path) -> None:
    from scripts.agent_worktree import LaneDirtyError, add_lane, remove_lane

    primary = _init_primary(tmp_path)
    lane = add_lane(primary, slug="shelves")
    (lane / "extra.txt").write_text("x\n", encoding="utf-8")
    with pytest.raises(LaneDirtyError, match="commit|dirty"):
        remove_lane(primary, slug="shelves")
    assert lane.is_dir()
    ok = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/agent/shelves"],
        cwd=primary,
        check=False,
    )
    assert ok.returncode == 0


def test_remove_failure_without_residue_has_no_permit(tmp_path: Path) -> None:
    from scripts.agent_recovery_permit_lib.paths import active_permits_dir
    from scripts.agent_worktree import LaneDirtyError, add_lane, remove_lane

    primary = _init_primary(tmp_path)
    lane = add_lane(primary, slug="shelves")
    (lane / "extra.txt").write_text("x\n", encoding="utf-8")
    with pytest.raises(LaneDirtyError):
        remove_lane(primary, slug="shelves")
    common = subprocess.run(
        ["git", "-C", str(primary), "rev-parse", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    )
    raw = Path(common.stdout.strip())
    git_common = raw if raw.is_absolute() else (primary / raw).resolve()
    assert not active_permits_dir(git_common).exists() or not any(
        active_permits_dir(git_common).glob("arp-*.json")
    )
    reports_root = git_common / "agent-process-reports" / "reports"
    assert reports_root.is_dir()
    assert any(reports_root.glob("*/*.json"))


def test_remove_clean_lane(tmp_path: Path) -> None:
    from scripts.agent_worktree import add_lane, remove_lane

    primary = _init_primary(tmp_path)
    lane = add_lane(primary, slug="shelves")
    remove_lane(primary, slug="shelves")
    assert not lane.exists()
    missing = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/agent/shelves"],
        cwd=primary,
        check=False,
    )
    assert missing.returncode != 0


def test_remove_cleans_orphan_unregistered_residue_under_permit(tmp_path: Path) -> None:
    from scripts.agent_recovery_permit_lib.paths import active_permits_dir
    from scripts.agent_worktree import add_lane, remove_lane

    primary = _init_primary(tmp_path)
    lane = add_lane(primary, slug="shelves")
    _git(primary, "worktree", "remove", "--force", str(lane))
    assert not lane.exists()
    lane.mkdir()
    (lane / "leftover.txt").write_text("x\n", encoding="utf-8")
    remove_lane(primary, slug="shelves")
    assert not lane.exists()
    common = subprocess.run(
        ["git", "-C", str(primary), "rev-parse", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    )
    raw = Path(common.stdout.strip())
    git_common = raw if raw.is_absolute() else (primary / raw).resolve()
    assert not any(active_permits_dir(git_common).glob("arp-*.json"))
    missing = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/agent/shelves"],
        cwd=primary,
        check=False,
    )
    assert missing.returncode != 0


def test_remove_defers_residue_when_worker_dir_holds_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.agent_worktree import LaneResidueDeferred, add_lane, main, remove_lane

    primary = _init_primary(tmp_path)
    lane = add_lane(primary, slug="shelves")
    _git(primary, "worktree", "remove", "--force", str(lane))
    lane.mkdir()
    (lane / "leftover.txt").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr("scripts.agent_worktree._worker_dir_holds_path", lambda _p: True)

    with pytest.raises(LaneResidueDeferred) as caught:
        remove_lane(primary, slug="shelves")
    err = caught.value
    assert err.report_id.startswith("apr-")
    assert err.permit_id.startswith("arp-")
    assert lane.is_dir()

    capsys.readouterr()
    code = main(["remove", "--slug", "shelves"], primary=primary)
    assert code == 0
    stderr = capsys.readouterr().err
    assert "status=residue_deferred" in stderr
    assert "ISS-385" in stderr


def test_worker_dir_hold_parsing_matches_exact_path(tmp_path: Path) -> None:
    from scripts.agent_worktree import _worker_dir_holds_path_from_lines

    target = tmp_path / "mk_service_bot-wt" / "shelves"
    target.mkdir(parents=True)
    cmd = f'cursor-agent-worker.exe --worker-dir "{target}"'
    assert _worker_dir_holds_path_from_lines(target, (cmd,)) is True
    assert _worker_dir_holds_path_from_lines(target, ("other --worker-dir elsewhere",)) is False


def test_branch_is_merged_when_lane_branch_already_gone(tmp_path: Path) -> None:
    from scripts.agent_worktree import _branch_is_merged

    primary = _init_primary(tmp_path)
    assert _branch_is_merged(primary, "shelves") is True


def test_residue_sweep_skips_hold_and_deletes_when_clear(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.agent_worktree import LaneResidueError, add_lane, main, remove_lane, residue_sweep

    primary = _init_primary(tmp_path)
    lane = add_lane(primary, slug="shelves")
    _git(primary, "worktree", "remove", "--force", str(lane))
    lane.mkdir()
    (lane / "leftover.txt").write_text("x\n", encoding="utf-8")
    holds = {"v": False}

    def _hold(path: object) -> bool:
        return holds["v"]

    monkeypatch.setattr("scripts.agent_worktree._worker_dir_holds_path", _hold)

    from scripts.agent_process_apr_lib import residue_delete as rd
    from scripts.agent_process_apr_lib.residue_delete import ResidueDeleteError

    real_delete = rd.exact_residue_delete

    def _locked(_path: object, **_kwargs: object) -> None:
        raise ResidueDeleteError("locked after retry")

    monkeypatch.setattr(rd, "exact_residue_delete", _locked)
    with pytest.raises(LaneResidueError):
        remove_lane(primary, slug="shelves")
    monkeypatch.setattr(rd, "exact_residue_delete", real_delete)

    holds["v"] = True

    counts = residue_sweep(primary)
    assert counts["skipped_hold"] == 1
    assert counts["deleted"] == 0
    assert lane.is_dir()

    holds["v"] = False
    counts = residue_sweep(primary)
    assert counts["deleted"] == 1
    assert not lane.is_dir()

    code = main(["residue-sweep"], primary=primary)
    assert code == 0
    out = capsys.readouterr().out
    assert "deleted=0" in out or "deleted=" in out


def test_residue_sweep_skips_registered_worktree(tmp_path: Path) -> None:
    from scripts.agent_worktree import add_lane, residue_sweep

    primary = _init_primary(tmp_path)
    add_lane(primary, slug="shelves")
    counts = residue_sweep(primary, slug="shelves")
    assert counts["skipped_registered"] == 1
    assert counts["deleted"] == 0


def test_remove_locked_residue_prints_report_permit_and_next_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.agent_process_apr_lib.residue_delete import ResidueDeleteError
    from scripts.agent_worktree import LaneResidueError, add_lane, main, remove_lane

    primary = _init_primary(tmp_path)
    lane = add_lane(primary, slug="shelves")
    _git(primary, "worktree", "remove", "--force", str(lane))
    lane.mkdir()
    (lane / "leftover.txt").write_text("x\n", encoding="utf-8")

    def _locked(_path: object, **_kwargs: object) -> None:
        raise ResidueDeleteError("locked after retry")

    monkeypatch.setattr(
        "scripts.agent_process_apr_lib.residue_delete.exact_residue_delete",
        _locked,
    )
    with pytest.raises(LaneResidueError) as caught:
        remove_lane(primary, slug="shelves")
    err = caught.value
    assert err.report_id.startswith("apr-")
    assert err.permit_id.startswith("arp-")
    assert "Remove-Item -LiteralPath" in err.next_command
    assert str(lane.resolve()) in err.next_command or str(lane) in err.next_command

    code = main(["remove", "--slug", "shelves"], primary=primary)
    assert code == 1
    stderr = capsys.readouterr().err
    assert err.report_id in stderr or "report_id=" in stderr
    assert "permit_id=" in stderr
    assert "next: Remove-Item -LiteralPath" in stderr


def test_remove_deletes_branch_when_path_already_gone(tmp_path: Path) -> None:
    from scripts.agent_worktree import add_lane, remove_lane

    primary = _init_primary(tmp_path)
    lane = add_lane(primary, slug="shelves")
    _git(primary, "worktree", "remove", str(lane))
    assert not lane.exists()
    remove_lane(primary, slug="shelves")
    missing = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/agent/shelves"],
        cwd=primary,
        check=False,
    )
    assert missing.returncode != 0


def test_add_succeeds_after_remove_deletes_branch(tmp_path: Path) -> None:
    from scripts.agent_worktree import add_lane, remove_lane

    primary = _init_primary(tmp_path)
    lane = add_lane(primary, slug="shelves")
    remove_lane(primary, slug="shelves")
    assert not lane.exists()
    lane2 = add_lane(primary, slug="shelves")
    assert lane2.is_dir()


def test_remove_cli_has_no_force_flag() -> None:
    parser_help = subprocess.run(
        [sys.executable, "scripts/agent_worktree.py", "remove", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert parser_help.returncode == 0
    assert "--force" not in parser_help.stdout


def test_main_add_prints_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts.agent_worktree import main

    primary = _init_primary(tmp_path)
    code = main(["add", "--slug", "shelves"], primary=primary)
    assert code == 0
    out = capsys.readouterr().out.strip()
    assert out.endswith("mk_service_bot-wt\\shelves") or out.endswith("mk_service_bot-wt/shelves")


def test_wrappers_invoke_python_only() -> None:
    ps1 = Path("scripts/agent_worktree.ps1").read_text(encoding="utf-8")
    sh = Path("scripts/agent_worktree.sh").read_text(encoding="utf-8")
    assert "uv run python" in ps1 and "agent_worktree.py" in ps1
    assert "uv run python" in sh and "agent_worktree.py" in sh
    assert "git worktree" not in ps1
    assert "git worktree" not in sh


def test_remove_skips_auto_delete_when_branch_unmerged(
    tmp_path: Path,
) -> None:
    from scripts.agent_recovery_permit_lib.paths import active_permits_dir
    from scripts.agent_worktree import LaneResidueError, add_lane, remove_lane

    primary = _init_primary(tmp_path)
    lane = add_lane(primary, slug="shelves")
    (lane / "extra.txt").write_text("unmerged\n", encoding="utf-8")
    _git(lane, "add", "extra.txt")
    _git(lane, "commit", "-m", "lane-only commit")
    _git(primary, "worktree", "remove", "--force", str(lane))
    lane.mkdir()
    (lane / "leftover.txt").write_text("x\n", encoding="utf-8")
    with pytest.raises(LaneResidueError) as caught:
        remove_lane(primary, slug="shelves")
    assert lane.is_dir()
    assert caught.value.permit_id.startswith("arp-")
    common = subprocess.run(
        ["git", "-C", str(primary), "rev-parse", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    )
    raw = Path(common.stdout.strip())
    git_common = raw if raw.is_absolute() else (primary / raw).resolve()
    assert any(active_permits_dir(git_common).glob("arp-*.json"))


def test_remove_skips_auto_delete_when_tracked_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.agent_recovery_permit_lib.paths import active_permits_dir
    from scripts.agent_worktree import LaneResidueError, add_lane, remove_lane

    primary = _init_primary(tmp_path)
    lane = add_lane(primary, slug="shelves")
    _git(primary, "worktree", "remove", "--force", str(lane))
    lane.mkdir()
    (lane / "leftover.txt").write_text("x\n", encoding="utf-8")

    monkeypatch.setattr(
        "scripts.agent_worktree._path_has_tracked_content",
        lambda _primary, _path: True,
    )
    with pytest.raises(LaneResidueError) as caught:
        remove_lane(primary, slug="shelves")
    assert lane.is_dir()
    assert caught.value.permit_id.startswith("arp-")
    common = subprocess.run(
        ["git", "-C", str(primary), "rev-parse", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    )
    raw = Path(common.stdout.strip())
    git_common = raw if raw.is_absolute() else (primary / raw).resolve()
    assert any(active_permits_dir(git_common).glob("arp-*.json"))


def test_remove_lane_leaves_cwd_outside_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.agent_worktree import add_lane, remove_lane

    primary = _init_primary(tmp_path)
    lane = add_lane(primary, slug="shelves")
    lane_resolved = lane.resolve()
    monkeypatch.chdir(lane)
    assert Path.cwd().resolve() == lane_resolved
    remove_lane(primary, slug="shelves")
    assert not lane.exists()
    cwd = Path.cwd().resolve()
    with pytest.raises(ValueError):
        cwd.relative_to(lane_resolved)
    assert cwd == primary.resolve()


def test_remove_already_absent_branch_succeeds_without_apr(tmp_path: Path) -> None:
    from scripts.agent_worktree import add_lane, remove_lane

    primary = _init_primary(tmp_path)
    lane = add_lane(primary, slug="shelves")
    _git(primary, "worktree", "remove", str(lane))
    assert not lane.exists()
    _git(primary, "branch", "-d", "agent/shelves")
    missing = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/agent/shelves"],
        cwd=primary,
        check=False,
    )
    assert missing.returncode != 0
    remove_lane(primary, slug="shelves")
    common = subprocess.run(
        ["git", "-C", str(primary), "rev-parse", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    )
    raw = Path(common.stdout.strip())
    git_common = raw if raw.is_absolute() else (primary / raw).resolve()
    reports_root = git_common / "agent-process-reports" / "reports"
    if reports_root.exists():
        reports = list(reports_root.glob("*/*.json"))
        assert not any("branch_delete_failed" in p.read_text(encoding="utf-8") for p in reports)


def test_remove_branch_in_use_reports_branch_delete_failed(tmp_path: Path) -> None:
    from scripts.agent_worktree import LaneBranchDeleteError, add_lane, remove_lane

    primary = _init_primary(tmp_path)
    lane = add_lane(primary, slug="shelves")
    _git(primary, "worktree", "remove", str(lane))
    assert not lane.exists()
    other = tmp_path / "other-checkout"
    _git(primary, "worktree", "add", str(other), "agent/shelves")
    with pytest.raises(
        LaneBranchDeleteError, match="branch_delete_failed|in use|refuse.*-D"
    ) as caught:
        remove_lane(primary, slug="shelves")
    message = str(caught.value)
    assert "agent/shelves" in message
    assert "-D" not in message or "refuse" in message.lower()
    still = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/agent/shelves"],
        cwd=primary,
        check=False,
    )
    assert still.returncode == 0
    common = subprocess.run(
        ["git", "-C", str(primary), "rev-parse", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    )
    raw = Path(common.stdout.strip())
    git_common = raw if raw.is_absolute() else (primary / raw).resolve()
    reports = list((git_common / "agent-process-reports" / "reports").glob("*/*.json"))
    assert any("branch_delete_failed" in p.read_text(encoding="utf-8") for p in reports)


def test_remove_unmerged_branch_reports_branch_delete_failed_without_force(
    tmp_path: Path,
) -> None:
    from scripts.agent_worktree import LaneBranchDeleteError, add_lane, remove_lane

    primary = _init_primary(tmp_path)
    lane = add_lane(primary, slug="shelves")
    (lane / "extra.txt").write_text("unmerged\n", encoding="utf-8")
    _git(lane, "add", "extra.txt")
    _git(lane, "commit", "-m", "lane-only commit")
    with pytest.raises(LaneBranchDeleteError, match="not merged|refuse") as caught:
        remove_lane(primary, slug="shelves")
    assert "refuse" in str(caught.value).lower() or "not merged" in str(caught.value).lower()
    assert "-D" not in str(caught.value) or "refuse" in str(caught.value).lower()
    still = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/agent/shelves"],
        cwd=primary,
        check=False,
    )
    assert still.returncode == 0


def test_remove_lane_retries_permission_denied_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import agent_worktree as aw

    primary = _init_primary(tmp_path)
    lane = aw.add_lane(primary, slug="shelves")
    calls = {"n": 0}
    real_run_git = aw._run_git

    def _flaky(cwd: Path, *args: str, check: bool = True):  # type: ignore[no-untyped-def]
        if args[:2] == ("worktree", "remove"):
            calls["n"] += 1
            if calls["n"] < 3:
                raise subprocess.CalledProcessError(
                    128,
                    ["git", *args],
                    output="",
                    stderr=f"error: failed to delete '{lane}': Permission denied\n",
                )
        return real_run_git(cwd, *args, check=check)

    monkeypatch.setattr(aw, "_run_git", _flaky)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    aw.remove_lane(primary, slug="shelves")
    assert calls["n"] == 3
    assert not lane.exists()


def test_remove_lane_non_lock_error_does_not_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import agent_worktree as aw

    primary = _init_primary(tmp_path)
    lane = aw.add_lane(primary, slug="shelves")
    calls = {"n": 0}
    real_run_git = aw._run_git

    def _once(cwd: Path, *args: str, check: bool = True):  # type: ignore[no-untyped-def]
        if args[:2] == ("worktree", "remove"):
            calls["n"] += 1
            raise subprocess.CalledProcessError(
                128,
                ["git", *args],
                output="",
                stderr=f"fatal: '{lane}' is not a working tree\n",
            )
        return real_run_git(cwd, *args, check=check)

    monkeypatch.setattr(aw, "_run_git", _once)
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(float(s)))
    with pytest.raises(subprocess.CalledProcessError):
        aw.remove_lane(primary, slug="shelves")
    assert calls["n"] == 1
    assert sleeps == []


def test_remove_lane_exhausted_lock_retries_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import agent_worktree as aw

    primary = _init_primary(tmp_path)
    lane = aw.add_lane(primary, slug="shelves")
    calls = {"n": 0}
    real_run_git = aw._run_git

    def _always_locked(cwd: Path, *args: str, check: bool = True):  # type: ignore[no-untyped-def]
        if args[:2] == ("worktree", "remove"):
            calls["n"] += 1
            raise subprocess.CalledProcessError(
                128,
                ["git", *args],
                output="",
                stderr="error: failed to delete: WinError 32\n",
            )
        return real_run_git(cwd, *args, check=check)

    monkeypatch.setattr(aw, "_run_git", _always_locked)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    with pytest.raises(subprocess.CalledProcessError):
        aw.remove_lane(primary, slug="shelves")
    assert calls["n"] == 3
    assert lane.exists()
