from __future__ import annotations

import json
from pathlib import Path

from scripts.agent_journal_lib.envelope import build_envelope
from scripts.agent_journal_lib.home_paths import default_job_events_path
from scripts.agent_journal_lib.store import list_event_ids_for_job, write_event
from scripts.agent_process_report_lib.home_paths import (
    default_process_reports_root,
    default_product_id,
)
from scripts.agent_process_report_lib.models import (
    ReportKind,
    ReportOutcome,
    new_report,
    report_from_dict,
    report_to_dict,
)
from scripts.agent_process_report_lib.store import create_report


def _product_with_home(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "agent_platform"
    home.mkdir()
    product = tmp_path / "mk"
    product.mkdir()
    (product / "kernel_ref").write_text(
        json.dumps({"home": str(home), "ref": "test", "mount": {}}),
        encoding="utf-8",
    )
    (product / "AGENT-OVERLAY.md").write_text("# Overlay mk_service_bot\n", encoding="utf-8")
    return product, home


def test_new_report_related_event_ids_default_empty() -> None:
    report = new_report(
        kind=ReportKind.PROCESS_SCRIPT_FAILURE,
        outcome=ReportOutcome.FAILED,
        surface="test",
        operation="op",
        signature="sig",
        expected="ok",
        actual="fail",
        evidence={},
    )
    assert report.related_event_ids == ()
    payload = report_to_dict(report)
    assert payload["related_event_ids"] == []


def test_report_from_dict_legacy_without_related_event_ids() -> None:
    report = new_report(
        kind=ReportKind.PROCESS_SCRIPT_FAILURE,
        outcome=ReportOutcome.FAILED,
        surface="test",
        operation="op",
        signature="sig",
        expected="ok",
        actual="fail",
        evidence={},
        report_id="apr-legacy",
    )
    payload = report_to_dict(report)
    del payload["related_event_ids"]
    loaded = report_from_dict(payload)
    assert loaded.related_event_ids == ()


def test_create_report_fills_related_event_ids_from_journal(tmp_path: Path) -> None:
    product, _home = _product_with_home(tmp_path)
    git_common = tmp_path / "git"
    git_common.mkdir()
    job_id = "job-abc123def456"
    write_event(
        product,
        job_id,
        build_envelope(
            name="job.phase",
            outcome="success",
            trace_id=job_id,
            job_id=job_id,
            attrs={"to_state": "reserved"},
            event_id="evt-a",
        ),
    )
    write_event(
        product,
        job_id,
        build_envelope(
            name="job.phase",
            outcome="success",
            trace_id=job_id,
            job_id=job_id,
            attrs={"to_state": "lane_ready"},
            event_id="evt-b",
        ),
    )
    events = default_job_events_path(product, job_id)
    assert list_event_ids_for_job(events) == ["evt-a", "evt-b"]
    before_last = events.read_text(encoding="utf-8").strip().splitlines()[-1]

    report = new_report(
        kind=ReportKind.PROCESS_SCRIPT_FAILURE,
        outcome=ReportOutcome.FAILED,
        surface="test",
        operation="op",
        signature="sig",
        expected="ok",
        actual="fail",
        evidence={},
        job_id=job_id,
        report_id="apr-11111111-1111-1111-1111-111111111111",
        product_id=default_product_id(product),
    )
    created = create_report(
        git_common,
        report,
        reports_root=default_process_reports_root(product),
        journal_product_root=product,
    )
    assert created.related_event_ids == ("evt-a", "evt-b")
    lines = events.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    assert lines[1] == before_last
    link = json.loads(lines[-1])
    assert "apr-11111111-1111-1111-1111-111111111111" in link["attrs"].get(
        "related_report_ids", []
    )
    assert link["attrs"]["linked_event_id"] == "evt-b"


def test_create_report_without_events_keeps_empty_related(tmp_path: Path) -> None:
    product, _home = _product_with_home(tmp_path)
    git_common = tmp_path / "git"
    git_common.mkdir()
    report = new_report(
        kind=ReportKind.PROCESS_SCRIPT_FAILURE,
        outcome=ReportOutcome.FAILED,
        surface="test",
        operation="op",
        signature="sig",
        expected="ok",
        actual="fail",
        evidence={},
        job_id="job-abcdef012345",
        report_id="apr-22222222-2222-2222-2222-222222222222",
        product_id=default_product_id(product),
    )
    created = create_report(
        git_common,
        report,
        reports_root=default_process_reports_root(product),
        journal_product_root=product,
    )
    assert created.related_event_ids == ()
