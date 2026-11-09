from __future__ import annotations

import json
from pathlib import Path

from scripts.agent_journal_lib.backfill import backfill_host_journal_to_home
from scripts.agent_journal_lib.envelope import build_envelope
from scripts.agent_journal_lib.home_paths import default_job_events_path
from scripts.agent_journal_lib.store import list_event_ids_for_job, write_event
from scripts.agent_process_report_lib.home_paths import default_product_id


def _write_kernel_ref(product: Path, home: Path) -> None:
    product.mkdir(parents=True, exist_ok=True)
    (product / "kernel_ref").write_text(
        json.dumps({"home": str(home), "ref": "test", "mount": {}}),
        encoding="utf-8",
    )
    (product / "AGENT-OVERLAY.md").write_text("# Overlay mk_service_bot\n", encoding="utf-8")


def test_backfill_idempotent_by_event_id(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    home.mkdir()
    product = tmp_path / "mk"
    _write_kernel_ref(product, home)
    git_common = tmp_path / "git"
    job_id = "job-abcdef"
    host_events = git_common / "agent-jobs" / job_id / "events.jsonl"
    host_events.parent.mkdir(parents=True)
    event = build_envelope(
        name="job.phase",
        outcome="success",
        trace_id=job_id,
        job_id=job_id,
        attrs={"to_state": "reserved"},
        event_id="evt-host-1",
    )
    host_events.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")

    first = backfill_host_journal_to_home(
        git_common_dir=git_common,
        product_root=product,
        home=home,
        product_id=default_product_id(product),
    )
    assert first.events_copied == 1
    assert first.events_skipped == 0
    path = default_job_events_path(product, job_id)
    assert list_event_ids_for_job(path) == ["evt-host-1"]

    second = backfill_host_journal_to_home(
        git_common_dir=git_common,
        product_root=product,
        home=home,
        product_id=default_product_id(product),
    )
    assert second.events_copied == 0
    assert second.events_skipped == 1
    assert list_event_ids_for_job(path) == ["evt-host-1"]


def test_backfill_skips_already_present_home_event(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    home.mkdir()
    product = tmp_path / "mk"
    _write_kernel_ref(product, home)
    git_common = tmp_path / "git"
    job_id = "job-feed01"
    event = build_envelope(
        name="job.phase",
        outcome="success",
        trace_id=job_id,
        job_id=job_id,
        attrs={"to_state": "reserved"},
        event_id="evt-same",
    )
    write_event(product, job_id, event)
    host_events = git_common / "agent-jobs" / job_id / "events.jsonl"
    host_events.parent.mkdir(parents=True)
    host_events.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")
    result = backfill_host_journal_to_home(
        git_common_dir=git_common,
        product_root=product,
        home=home,
        product_id=default_product_id(product),
    )
    assert result.events_copied == 0
    assert result.events_skipped == 1
