from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.agent_job_lib.manifest_store import append_event
from scripts.agent_journal_lib.emit import append_jsonl, legacy_job_event_to_envelope
from scripts.agent_journal_lib.envelope import (
    JournalEmitError,
    build_envelope,
    load_catalog_names,
)
from scripts.agent_journal_lib.redaction import redact_attrs

# json used by _product_with_home and assertions


def test_catalog_contains_v1_names() -> None:
    names = load_catalog_names()
    assert "job.phase" in names
    assert "gate.final" in names


def test_build_envelope_happy_job_phase() -> None:
    event = build_envelope(
        name="job.phase",
        outcome="success",
        trace_id="job-1",
        job_id="job-1",
        attrs={"from_state": None, "to_state": "reserved"},
    )
    assert event["schema_version"] == 1
    assert event["name"] == "job.phase"
    assert event["event_id"]
    assert event["trace_id"] == "job-1"
    assert event["job_id"] == "job-1"
    assert event["attrs"]["to_state"] == "reserved"


def test_build_envelope_rejects_unknown_name() -> None:
    with pytest.raises(JournalEmitError, match="unknown event name"):
        build_envelope(
            name="job.unknown",
            outcome="success",
            trace_id="job-1",
            job_id="job-1",
            attrs={},
        )


def test_build_envelope_requires_job_id_for_phase() -> None:
    with pytest.raises(JournalEmitError, match="job.phase requires job_id"):
        build_envelope(
            name="job.phase",
            outcome="success",
            trace_id="trace-only",
            attrs={"to_state": "reserved"},
        )


def test_redaction_drops_forbidden_keys_and_secrets() -> None:
    cleaned = redact_attrs(
        {
            "to_state": "lane_ready",
            "body": "secret issue text",
            "note": "token=abc123xyz",
        }
    )
    assert "body" not in cleaned
    assert cleaned["to_state"] == "lane_ready"
    assert "[REDACTED]" in cleaned["note"]


def test_append_jsonl_writes_envelope(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    event = build_envelope(
        name="job.phase",
        outcome="success",
        trace_id="job-1",
        job_id="job-1",
        attrs={"to_state": "reserved"},
    )
    append_jsonl(path, event)
    line = path.read_text(encoding="utf-8").strip()
    loaded = json.loads(line)
    assert loaded["name"] == "job.phase"
    assert loaded["schema_version"] == 1


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


def test_legacy_wrap_and_manifest_append(tmp_path: Path) -> None:
    from scripts.agent_journal_lib.home_paths import default_job_events_path

    job_id = "job-abc123"
    envelope = legacy_job_event_to_envelope(
        job_id,
        {"type": "lane_ready", "worktree_path": "/tmp/wt", "branch": "agent/x"},
    )
    assert envelope["name"] == "job.phase"
    assert envelope["outcome"] == "success"
    assert envelope["attrs"]["to_state"] == "lane_ready"
    assert envelope["attrs"]["from_state"] == "reserved"
    assert envelope["attrs"]["legacy_type"] == "lane_ready"

    product, _home = _product_with_home(tmp_path)
    git_common = tmp_path / "git"
    git_common.mkdir()
    append_event(
        git_common,
        job_id,
        {"type": "reserved", "slug": "demo"},
        product_root=product,
    )
    events_path = default_job_events_path(product, job_id)
    rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["schema_version"] == 1
    assert rows[0]["name"] == "job.phase"
    assert rows[0]["trace_id"] == job_id
    assert rows[0]["event_id"]
    assert rows[0]["attrs"]["to_state"] == "reserved"
    assert not (git_common / "agent-jobs" / job_id / "events.jsonl").exists()


def test_fail_transition_emits_fail_outcome(tmp_path: Path) -> None:
    from scripts.agent_journal_lib.home_paths import default_job_events_path

    job_id = "job-deadbeef"
    product, _home = _product_with_home(tmp_path)
    git_common = tmp_path / "git"
    git_common.mkdir()
    append_event(
        git_common,
        job_id,
        {"type": "failed", "reason": "worktree"},
        product_root=product,
    )
    events_path = default_job_events_path(product, job_id)
    row = json.loads(events_path.read_text(encoding="utf-8").splitlines()[0])
    assert row["outcome"] == "fail"
    assert row["attrs"]["to_state"] == "failed"
