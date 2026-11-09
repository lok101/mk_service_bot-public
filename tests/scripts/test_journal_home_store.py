from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.agent_journal_lib.envelope import build_envelope
from scripts.agent_journal_lib.home_paths import (
    JournalStoreUnavailableError,
    default_job_events_path,
    home_job_events_path,
    load_platform_home,
)
from scripts.agent_journal_lib.store import (
    append_related_report_link,
    list_event_ids_for_job,
    write_event,
)
from scripts.agent_process_report_lib.home_paths import default_product_id


def _write_kernel_ref(product: Path, home: Path) -> None:
    product.mkdir(parents=True, exist_ok=True)
    (product / "kernel_ref").write_text(
        json.dumps({"home": str(home), "ref": "test", "mount": {}}),
        encoding="utf-8",
    )
    (product / "AGENT-OVERLAY.md").write_text("# Overlay mk_service_bot\n", encoding="utf-8")


def test_write_event_under_home_process_journal(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    home.mkdir()
    product = tmp_path / "mk"
    _write_kernel_ref(product, home)
    job_id = "job-abc123"
    event = build_envelope(
        name="job.phase",
        outcome="success",
        trace_id=job_id,
        job_id=job_id,
        attrs={"to_state": "reserved"},
        event_id="evt-1",
    )
    write_event(product, job_id, event)
    path = default_job_events_path(product, job_id)
    assert path == home_job_events_path(
        home,
        product_id=default_product_id(product),
        job_id=job_id,
    )
    assert "agent-jobs" not in str(path)
    assert list_event_ids_for_job(path) == ["evt-1"]


def test_write_event_fail_closed_without_kernel_ref(tmp_path: Path) -> None:
    product = tmp_path / "bare"
    product.mkdir()
    with pytest.raises(JournalStoreUnavailableError):
        load_platform_home(product)


def test_two_appends_intact_lines(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    home.mkdir()
    product = tmp_path / "mk"
    _write_kernel_ref(product, home)
    job_id = "job-deadbeef"
    for event_id, state in (("evt-a", "reserved"), ("evt-b", "lane_ready")):
        write_event(
            product,
            job_id,
            build_envelope(
                name="job.phase",
                outcome="success",
                trace_id=job_id,
                job_id=job_id,
                attrs={"to_state": state},
                event_id=event_id,
            ),
        )
    path = default_job_events_path(product, job_id)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["event_id"] for line in lines] == ["evt-a", "evt-b"]


def test_append_related_report_link_does_not_rewrite_last(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    home.mkdir()
    product = tmp_path / "mk"
    _write_kernel_ref(product, home)
    job_id = "job-cafe01"
    write_event(
        product,
        job_id,
        build_envelope(
            name="job.phase",
            outcome="success",
            trace_id=job_id,
            job_id=job_id,
            attrs={"to_state": "reserved"},
            event_id="evt-phase",
        ),
    )
    path = default_job_events_path(product, job_id)
    before = path.read_text(encoding="utf-8")
    assert append_related_report_link(product, job_id=job_id, report_id="apr-1") is True
    after_lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(after_lines) == 2
    assert after_lines[0] == before.strip().splitlines()[0]
    link = json.loads(after_lines[1])
    assert link["attrs"]["related_report_ids"] == ["apr-1"]
    assert link["attrs"]["linked_event_id"] == "evt-phase"
