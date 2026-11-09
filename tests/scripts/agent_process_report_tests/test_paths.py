from __future__ import annotations

from pathlib import Path

import pytest
from scripts.agent_process_report_lib.paths import (
    agent_process_reports_root,
    index_path,
    report_file_path,
    reports_dir,
)


def test_report_roots_under_git_common_dir(tmp_path: Path) -> None:
    common = tmp_path / "common.git"
    common.mkdir()
    root = agent_process_reports_root(common)
    assert root == common / "agent-process-reports"
    assert reports_dir(root) == root / "reports"
    assert index_path(root) == root / "index.jsonl"


def test_report_file_path_uses_date_and_id(tmp_path: Path) -> None:
    root = tmp_path / "process-reports"
    root.mkdir()
    path = report_file_path(
        root,
        report_id="apr-deadbeef-0000-0000-0000-000000000001",
        occurred_date="2026-10-13",
    )
    assert path == (
        root / "reports" / "2026-10-13" / "apr-deadbeef-0000-0000-0000-000000000001.json"
    )


def test_report_file_path_rejects_unsafe_id(tmp_path: Path) -> None:
    root = tmp_path / "process-reports"
    root.mkdir()
    with pytest.raises(ValueError, match="report_id"):
        report_file_path(root, report_id="../evil", occurred_date="2026-10-13")
    with pytest.raises(ValueError, match="report_id"):
        report_file_path(root, report_id="not-apr", occurred_date="2026-10-13")
