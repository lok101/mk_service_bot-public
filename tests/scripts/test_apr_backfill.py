from __future__ import annotations

import json
from pathlib import Path

from scripts.agent_process_report_lib.backfill import backfill_host_to_home
from scripts.agent_process_report_lib.home_paths import home_process_reports_root
from scripts.agent_process_report_lib.models import ReportKind, ReportOutcome, new_report
from scripts.agent_process_report_lib.store import create_report, load_report


def test_backfill_copies_then_skips(tmp_path: Path) -> None:
    common = tmp_path / "common.git"
    common.mkdir()
    home = tmp_path / "agent_platform"
    home.mkdir()

    report = new_report(
        kind=ReportKind.PROCESS_SCRIPT_FAILURE,
        outcome=ReportOutcome.FAILED,
        surface="t",
        operation="o",
        signature="s",
        expected="e",
        actual="a",
        evidence={},
    )
    create_report(common, report)

    first = backfill_host_to_home(
        git_common_dir=common,
        home=home,
        product_id="mk",
    )
    assert first.reports_copied == 1
    assert first.reports_skipped == 0
    home_root = home_process_reports_root(home)
    loaded = load_report(common, report.report_id, reports_root=home_root)
    assert loaded.product_id == "mk"

    second = backfill_host_to_home(
        git_common_dir=common,
        home=home,
        product_id="mk",
    )
    assert second.reports_copied == 0
    assert second.reports_skipped == 1


def test_backfill_copies_permits(tmp_path: Path) -> None:
    common = tmp_path / "common.git"
    common.mkdir()
    home = tmp_path / "agent_platform"
    home.mkdir()
    src = common / "agent-recovery-permits" / "active"
    src.mkdir(parents=True)
    permit_id = "arp-deadbeef-0000-0000-0000-000000000001"
    (src / f"{permit_id}.json").write_text(
        json.dumps({"schema_version": 1, "permit_id": permit_id}),
        encoding="utf-8",
    )
    result = backfill_host_to_home(git_common_dir=common, home=home, product_id="mk")
    assert result.permits_copied == 1
    dst = home / "var" / "recovery-permits" / "active" / f"{permit_id}.json"
    assert dst.is_file()
    again = backfill_host_to_home(git_common_dir=common, home=home, product_id="mk")
    assert again.permits_skipped == 1
    assert again.permits_copied == 0
