from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from scripts.agent_process_report_lib.models import (
    ReportKind,
    ReportOutcome,
    new_report,
)
from scripts.agent_process_report_lib.store import (
    ReportConflictError,
    ReportCorruptError,
    ReportSchemaError,
    create_report,
    load_report,
    rebuild_index,
)


def _common(tmp_path: Path) -> Path:
    common = tmp_path / "g"
    common.mkdir()
    return common


def test_create_report_atomic_roundtrip(tmp_path: Path) -> None:
    common = _common(tmp_path)
    report = new_report(
        kind=ReportKind.PROCESS_SCRIPT_FAILURE,
        outcome=ReportOutcome.FAILED,
        surface="agent_worktree",
        operation="remove",
        signature="worktree.remove.residue",
        expected="clean remove",
        actual="residue left",
        evidence={"command_family": "agent_worktree remove", "exit_code": 1},
        report_id="apr-11111111-1111-1111-1111-111111111111",
        occurred_at=datetime(2026, 10, 13, 12, 0, tzinfo=UTC),
    )
    created = create_report(common, report)
    loaded = load_report(common, created.report_id)
    assert loaded.report_id == created.report_id
    assert loaded.kind == ReportKind.PROCESS_SCRIPT_FAILURE
    assert loaded.outcome == ReportOutcome.FAILED
    assert loaded.surface == "agent_worktree"
    report_path = (
        common / "agent-process-reports" / "reports" / "2026-10-13" / f"{created.report_id}.json"
    )
    assert report_path.is_file()
    index = (common / "agent-process-reports" / "index.jsonl").read_text(encoding="utf-8")
    assert created.report_id in index


def test_same_id_rejects_divergent_payload(tmp_path: Path) -> None:
    common = _common(tmp_path)
    report = new_report(
        kind=ReportKind.HARD_BOUNDARY_ATTEMPT,
        outcome=ReportOutcome.BLOCKED,
        surface="hook",
        operation="Write",
        signature="hard.write",
        expected="deny",
        actual="attempt",
        evidence={"command_family": "Write"},
        report_id="apr-22222222-2222-2222-2222-222222222222",
        occurred_at=datetime(2026, 10, 13, 12, 0, tzinfo=UTC),
    )
    create_report(common, report)
    again = create_report(common, report)
    assert again.report_id == report.report_id
    divergent = new_report(
        kind=ReportKind.HARD_BOUNDARY_ATTEMPT,
        outcome=ReportOutcome.BLOCKED,
        surface="hook",
        operation="Write",
        signature="hard.write.other",
        expected="deny",
        actual="attempt",
        evidence={"command_family": "Write"},
        report_id=report.report_id,
        occurred_at=datetime(2026, 10, 13, 12, 0, tzinfo=UTC),
    )
    with pytest.raises(ReportConflictError):
        create_report(common, divergent)


def test_corrupt_report_fail_closed(tmp_path: Path) -> None:
    common = _common(tmp_path)
    report = new_report(
        kind=ReportKind.PROCESS_SCRIPT_FAILURE,
        outcome=ReportOutcome.FAILED,
        surface="cli",
        operation="gc",
        signature="cli.gc",
        expected="ok",
        actual="fail",
        evidence={},
        report_id="apr-33333333-3333-3333-3333-333333333333",
        occurred_at=datetime(2026, 10, 13, 12, 0, tzinfo=UTC),
    )
    create_report(common, report)
    path = common / "agent-process-reports" / "reports" / "2026-10-13" / f"{report.report_id}.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ReportCorruptError):
        load_report(common, report.report_id)


def test_newer_schema_fail_closed(tmp_path: Path) -> None:
    common = _common(tmp_path)
    report = new_report(
        kind=ReportKind.PROCESS_SCRIPT_FAILURE,
        outcome=ReportOutcome.FAILED,
        surface="cli",
        operation="list",
        signature="cli.list",
        expected="ok",
        actual="fail",
        evidence={},
        report_id="apr-44444444-4444-4444-4444-444444444444",
        occurred_at=datetime(2026, 10, 13, 12, 0, tzinfo=UTC),
    )
    create_report(common, report)
    path = common / "agent-process-reports" / "reports" / "2026-10-13" / f"{report.report_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = 99
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    with pytest.raises(ReportSchemaError):
        load_report(common, report.report_id)


def test_rebuild_index_from_report_files(tmp_path: Path) -> None:
    common = _common(tmp_path)
    r1 = new_report(
        kind=ReportKind.PROCESS_SCRIPT_FAILURE,
        outcome=ReportOutcome.FAILED,
        surface="a",
        operation="op",
        signature="sig.a",
        expected="e",
        actual="a",
        evidence={},
        report_id="apr-55555555-5555-5555-5555-555555555555",
        occurred_at=datetime(2026, 10, 13, 12, 0, tzinfo=UTC),
    )
    r2 = new_report(
        kind=ReportKind.PERMITTED_RECOVERY,
        outcome=ReportOutcome.RECOVERED,
        surface="b",
        operation="op",
        signature="sig.b",
        expected="e",
        actual="a",
        evidence={},
        report_id="apr-66666666-6666-6666-6666-666666666666",
        occurred_at=datetime(2026, 10, 14, 12, 0, tzinfo=UTC),
    )
    create_report(common, r1)
    create_report(common, r2)
    index = common / "agent-process-reports" / "index.jsonl"
    index.write_text("corrupt\n", encoding="utf-8")
    lines = rebuild_index(common)
    assert {row["report_id"] for row in lines} == {r1.report_id, r2.report_id}
    rebuilt = index.read_text(encoding="utf-8").strip().splitlines()
    assert len(rebuilt) == 2
    assert "corrupt" not in index.read_text(encoding="utf-8")


def test_unicode_windows_path_in_evidence(tmp_path: Path) -> None:
    common = _common(tmp_path)
    report = new_report(
        kind=ReportKind.PROCESS_SCRIPT_FAILURE,
        outcome=ReportOutcome.FAILED,
        surface="closeout",
        operation="remove",
        signature="closeout.remove",
        expected="gone",
        actual="left",
        evidence={
            "target_paths": [r"C:\Users\тест\mk_service_bot-wt\lane-slug"],
        },
        report_id="apr-77777777-7777-7777-7777-777777777777",
        occurred_at=datetime(2026, 10, 13, 12, 0, tzinfo=UTC),
    )
    create_report(common, report)
    loaded = load_report(common, report.report_id)
    assert "тест" in str(loaded.evidence["target_paths"][0])


def test_occurred_at_recent_default_id(tmp_path: Path) -> None:
    common = _common(tmp_path)
    report = new_report(
        kind=ReportKind.ANALYSIS_MISSING,
        outcome=ReportOutcome.DEGRADED,
        surface="stop",
        operation="followup",
        signature="analysis.missing",
        expected="enriched",
        actual="missing",
        evidence={},
    )
    created = create_report(common, report)
    assert created.report_id.startswith("apr-")
    assert created.occurred_at <= datetime.now(UTC) + timedelta(seconds=1)
