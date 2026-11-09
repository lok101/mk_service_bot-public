from __future__ import annotations

from pathlib import Path

from scripts.agent_process_apr_lib import (
    APR001,
    APR002,
    APR004,
    APR005,
    record_hard_boundary_attempt,
    try_permit_recovery_allow,
)
from scripts.agent_process_report_lib.models import ReportKind, ReportOutcome
from scripts.agent_process_report_lib.store import list_reports, load_report
from scripts.agent_recovery_permit_lib.models import PermitOperation, new_permit
from scripts.agent_recovery_permit_lib.paths import active_permits_dir, consumed_permits_dir
from scripts.agent_recovery_permit_lib.store import issue_permit, load_active_permit


def _layout(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    common = tmp_path / "git-common"
    common.mkdir()
    primary = tmp_path / "mk_service_bot"
    primary.mkdir()
    wt_root = tmp_path / "mk_service_bot-wt"
    wt_root.mkdir()
    lane = wt_root / "residue-lane"
    lane.mkdir()
    return common, primary, wt_root, lane


def test_hard_deny_writes_report_keeps_deny(tmp_path: Path) -> None:
    common, _, _, _ = _layout(tmp_path)
    decision = record_hard_boundary_attempt(
        common,
        surface="aec.hook",
        operation="git_reset_hard",
        signature="agt007",
        expected="lane isolation",
        actual="git reset --hard",
        evidence={"command_family": "git_destructive"},
        conversation_id="conv-hard",
    )
    assert decision.allow is False
    assert decision.code == APR001
    assert decision.report_id is not None
    report = load_report(common, decision.report_id)
    assert report.kind is ReportKind.HARD_BOUNDARY_ATTEMPT
    assert report.outcome is ReportOutcome.BLOCKED


def test_report_store_down_apr004(tmp_path: Path) -> None:
    # Non-writable / non-dir path as git_common_dir forces create failure.
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("x", encoding="utf-8")
    decision = record_hard_boundary_attempt(
        blocked,
        surface="aec.hook",
        operation="write_protected",
        signature="agt005",
        expected="deny",
        actual="write",
        evidence={},
    )
    assert decision.allow is False
    assert decision.code == APR004
    assert decision.report_id is None


def test_missing_permit_apr002(tmp_path: Path) -> None:
    common, primary, wt_root, lane = _layout(tmp_path)
    command = f"Remove-Item -LiteralPath {lane}"
    decision = try_permit_recovery_allow(
        common,
        command=command,
        conversation_id="conv-1",
        primary_repo=primary,
        worktrees_root=wt_root,
        worktree_list_porcelain="",
        branch_merged=True,
        has_tracked_content=False,
    )
    assert decision is not None
    assert decision.allow is False
    assert decision.code == APR002


def test_permit_allow_writes_report_and_consumes(tmp_path: Path) -> None:
    common, primary, wt_root, lane = _layout(tmp_path)
    source = "apr-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    permit = new_permit(
        issuer="agent_worktree.remove",
        source_report_id=source,
        operation=PermitOperation.REMOVE_UNREGISTERED_LANE_RESIDUE,
        target_paths=(str(lane.resolve()),),
        preconditions=("unregistered", "branch_merged"),
        conversation_id="conv-ok",
        job_id="job-ok",
        permit_id="arp-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    )
    issue_permit(common, permit)
    command = f"Remove-Item -LiteralPath {lane.resolve()}"
    decision = try_permit_recovery_allow(
        common,
        command=command,
        conversation_id="conv-ok",
        job_id="job-ok",
        primary_repo=primary,
        worktrees_root=wt_root,
        worktree_list_porcelain="worktree /other\n",
        branch_merged=True,
        has_tracked_content=False,
    )
    assert decision is not None
    assert decision.allow is True
    assert decision.code == APR005
    assert decision.report_id is not None
    report = load_report(common, decision.report_id)
    assert report.kind is ReportKind.PERMITTED_RECOVERY
    assert report.outcome is ReportOutcome.RECOVERED
    assert report.permit_id == permit.permit_id
    assert not (active_permits_dir(common) / f"{permit.permit_id}.json").exists()
    assert (consumed_permits_dir(common) / f"{permit.permit_id}.json").is_file()
    with __import__("pytest").raises(Exception):
        load_active_permit(common, permit.permit_id)


def test_precondition_fail_apr003(tmp_path: Path) -> None:
    common, primary, wt_root, lane = _layout(tmp_path)
    permit = new_permit(
        issuer="agent_worktree.remove",
        source_report_id="apr-cccccccc-cccc-cccc-cccc-cccccccccccc",
        operation=PermitOperation.REMOVE_UNREGISTERED_LANE_RESIDUE,
        target_paths=(str(lane.resolve()),),
        preconditions=(),
        conversation_id="conv-pre",
        permit_id="arp-dddddddd-dddd-dddd-dddd-dddddddddddd",
    )
    issue_permit(common, permit)
    command = f"Remove-Item -LiteralPath {lane.resolve()}"
    # Registered worktree in porcelain → precondition fail.
    porcelain = f"worktree {lane.resolve()}\nHEAD abc\n"
    from scripts.agent_process_apr_lib import APR003

    decision = try_permit_recovery_allow(
        common,
        command=command,
        conversation_id="conv-pre",
        primary_repo=primary,
        worktrees_root=wt_root,
        worktree_list_porcelain=porcelain,
        branch_merged=True,
        has_tracked_content=False,
    )
    assert decision is not None
    assert decision.allow is False
    assert decision.code == APR003
    assert list_reports(common)
