from __future__ import annotations

from pathlib import Path

from scripts.agent_process_report_lib.models import ReportKind, ReportOutcome
from scripts.agent_process_report_lib.record import record_script_failure
from scripts.agent_process_report_lib.store import load_report
from scripts.agent_recovery_permit_lib.paths import active_permits_dir


def test_record_script_failure_writes_report(tmp_path: Path) -> None:
    common = tmp_path / "g"
    common.mkdir()
    report = record_script_failure(
        common,
        surface="agent_worktree.remove",
        operation="remove_lane",
        signature="lane_dirty",
        expected="clean porcelain",
        actual="dirty",
        evidence={"exit_code": 1, "command_family": "agent_worktree"},
        lane_slug="shelves",
    )
    loaded = load_report(common, report.report_id)
    assert loaded.kind is ReportKind.PROCESS_SCRIPT_FAILURE
    assert loaded.outcome is ReportOutcome.FAILED
    assert loaded.lane_slug == "shelves"
    assert not active_permits_dir(common).exists()
