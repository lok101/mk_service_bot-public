from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.agent_journal_lib.envelope import JournalEmitError, build_envelope
from scripts.agent_journal_lib.store import (
    append_event,
    attach_related_report_to_last,
    list_event_ids_for_job,
)


def test_append_and_list_event_ids_happy(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    first = build_envelope(
        name="job.phase",
        outcome="success",
        trace_id="job-1",
        job_id="job-1",
        attrs={"to_state": "reserved"},
        event_id="evt-1",
    )
    second = build_envelope(
        name="job.phase",
        outcome="success",
        trace_id="job-1",
        job_id="job-1",
        attrs={"to_state": "lane_ready"},
        event_id="evt-2",
    )
    append_event(path, first)
    append_event(path, second)
    assert list_event_ids_for_job(path) == ["evt-1", "evt-2"]


def test_list_skips_legacy_and_corrupt_lines(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        '{"type":"reserved"}\n'
        "not-json\n"
        + json.dumps(
            build_envelope(
                name="job.phase",
                outcome="success",
                trace_id="job-1",
                job_id="job-1",
                attrs={"to_state": "reserved"},
                event_id="evt-ok",
            ),
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    assert list_event_ids_for_job(path) == ["evt-ok"]


def test_attach_related_report_to_last_updates_attrs(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    event = build_envelope(
        name="job.phase",
        outcome="success",
        trace_id="job-1",
        job_id="job-1",
        attrs={"to_state": "reserved"},
        event_id="evt-1",
    )
    append_event(path, event)
    assert attach_related_report_to_last(path, "apr-1") is True
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    loaded = json.loads(lines[0])
    assert loaded["attrs"]["related_report_ids"] == ["apr-1"]


def test_attach_related_report_noop_when_empty(tmp_path: Path) -> None:
    path = tmp_path / "missing.jsonl"
    assert attach_related_report_to_last(path, "apr-1") is False


def test_append_rejects_invalid_envelope(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    with pytest.raises(JournalEmitError):
        append_event(path, {"name": "job.unknown", "schema_version": 1})
