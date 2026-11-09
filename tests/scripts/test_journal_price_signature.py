from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from scripts.agent_journal_lib.envelope import JournalEmitError, load_catalog_names
from scripts.agent_journal_lib.human_stop import HUMAN_STOP, HumanStopError, emit_human_stop
from scripts.agent_journal_lib.price import (
    attach_price_attrs,
    compute_loaded_process_context_bytes,
    price_fields_for_job,
)
from scripts.agent_journal_lib.projection import (
    build_projection_from_events,
    rebuild_projection_for_product_job,
)
from scripts.agent_journal_lib.surface_enter import emit_surface_enter
from scripts.agent_process_eval_lib.paths import unique_loaded_bytes
from scripts.agent_process_report_lib.home_paths import default_product_id
from scripts.agent_process_report_lib.models import ReportKind, ReportOutcome, new_report
from scripts.agent_process_report_lib.store import create_report


def _write_kernel_ref(product: Path, home: Path) -> None:
    product.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    (product / "kernel_ref").write_text(
        json.dumps({"home": str(home), "ref": "test", "mount": {}}),
        encoding="utf-8",
    )
    (product / "AGENT-OVERLAY.md").write_text("# Overlay mk_service_bot\n", encoding="utf-8")


def test_catalog_includes_human_stop() -> None:
    assert HUMAN_STOP in load_catalog_names()


def test_emit_human_stop_increments_projection_count(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    job_id = "job-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    event = emit_human_stop(
        product,
        job_id=job_id,
        reason="permit.issue",
        outcome="success",
        parent_span_id="parent-1",
    )

    assert event["name"] == HUMAN_STOP
    assert event["attrs"]["reason"] == "permit.issue"
    assert "tool_input" not in event["attrs"]
    projection = rebuild_projection_for_product_job(product, job_id)
    assert projection.get("human_stop_count") == 1


def test_loaded_bytes_unique_paths_once(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    skill = product / "SKILL.md"
    skill.write_text("abc\n", encoding="utf-8")
    other = product / "other.py"
    other.write_text("xy\n", encoding="utf-8")
    job_id = "job-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

    emit_surface_enter(product, job_id=job_id, role="skill", path=skill)
    emit_surface_enter(product, job_id=job_id, role="skill", path=skill)
    emit_surface_enter(product, job_id=job_id, role="script", path=other)

    expected = unique_loaded_bytes([skill, other])
    assert compute_loaded_process_context_bytes(product, job_id) == expected
    fields = price_fields_for_job(product, job_id)
    assert fields["loaded_process_context_bytes"] == expected
    assert fields["human_stop_count"] == 0


def test_loaded_bytes_zero_when_no_skill_script_paths(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    job_id = "job-cccccccccccccccccccccccccccccccc"
    assert compute_loaded_process_context_bytes(product, job_id) == 0
    assert price_fields_for_job(product, job_id)["loaded_process_context_bytes"] == 0


def test_finalize_attrs_include_price_fields(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    skill = product / "SKILL.md"
    skill.write_text("hello\n", encoding="utf-8")
    job_id = "job-dddddddddddddddddddddddddddddddd"
    emit_surface_enter(product, job_id=job_id, role="skill", path=skill)
    emit_human_stop(product, job_id=job_id, reason="human.in_out")

    attrs = attach_price_attrs(product, job_id, {"to_state": "ready_for_closeout"})
    assert attrs["human_stop_count"] == 1
    assert attrs["loaded_process_context_bytes"] == skill.stat().st_size


def test_emit_human_stop_error_unknown_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    monkeypatch.setattr(
        "scripts.agent_journal_lib.envelope.load_catalog_names",
        lambda **_kwargs: frozenset({"job.phase"}),
    )
    with pytest.raises((HumanStopError, JournalEmitError)):
        emit_human_stop(
            product,
            job_id="job-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            reason="x",
        )


def test_emit_human_stop_error_home_down(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    product.mkdir()
    (product / "AGENT-OVERLAY.md").write_text("# Overlay mk_service_bot\n", encoding="utf-8")
    with pytest.raises((HumanStopError, JournalEmitError, OSError, RuntimeError)):
        emit_human_stop(
            product,
            job_id="job-ffffffffffffffffffffffffffffffff",
            reason="permit.issue",
        )


def test_projection_rebuild_counts_stops_and_bytes_attrs() -> None:
    events = [
        {
            "schema_version": 1,
            "job_id": "job-h",
            "name": HUMAN_STOP,
            "occurred_at": "2026-11-05T00:00:00Z",
            "attrs": {"reason": "a"},
        },
        {
            "schema_version": 1,
            "job_id": "job-h",
            "name": HUMAN_STOP,
            "occurred_at": "2026-11-05T00:01:00Z",
            "attrs": {"reason": "b"},
        },
        {
            "schema_version": 1,
            "job_id": "job-h",
            "name": "gate.final",
            "occurred_at": "2026-11-05T00:02:00Z",
            "attrs": {
                "human_stop_count": 2,
                "loaded_process_context_bytes": 42,
            },
        },
    ]
    projection = build_projection_from_events(events)
    assert projection["human_stop_count"] == 2
    assert projection["loaded_process_context_bytes"] == 42


def test_permit_issue_emits_human_stop(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    common = tmp_path / "git-common"
    common.mkdir()
    job_id = "job-11111111111111111111111111111111"

    from scripts.agent_recovery_permit_lib.store import issue_new_permit

    issue_new_permit(
        common,
        issuer="agent_worktree.remove",
        source_report_id="apr-1",
        operation="remove_unregistered_lane_residue",
        target_paths=("x",),
        job_id=job_id,
        product_root=product,
    )
    projection = rebuild_projection_for_product_job(product, job_id)
    assert projection.get("human_stop_count", 0) >= 1


def test_permit_no_job_id_skips_stop(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    common = tmp_path / "git-common"
    common.mkdir()

    from scripts.agent_recovery_permit_lib.store import issue_new_permit

    permit = issue_new_permit(
        common,
        issuer="agent_worktree.remove",
        source_report_id="apr-2",
        operation="remove_unregistered_lane_residue",
        target_paths=("y",),
        job_id=None,
        product_root=product,
    )
    assert permit.job_id is None


def test_surface_mark_in_out_emits_human_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    entry = product / "triage.py"
    entry.write_text("pass\n", encoding="utf-8")
    monkeypatch.chdir(product)
    job_id = "job-22222222222222222222222222222222"

    from scripts.agent_journal_surface_mark import main as mark_main

    code = mark_main(
        [
            "--job-id",
            job_id,
            "--role",
            "human.in_out",
            "--path",
            str(entry),
            "--decision",
            "in",
        ]
    )
    assert code == 0
    projection = rebuild_projection_for_product_job(product, job_id)
    assert projection.get("human_stop_count", 0) >= 1


def test_write_job_event_terminal_includes_price(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    skill = product / "SKILL.md"
    skill.write_text("body\n", encoding="utf-8")
    job_id = "job-33333333333333333333333333333333"
    emit_surface_enter(product, job_id=job_id, role="skill", path=skill)
    emit_human_stop(product, job_id=job_id, reason="human.spec_accept")

    from scripts.agent_journal_lib.emit import write_job_event

    write_job_event(
        product,
        job_id,
        {"type": "ready_for_closeout", "from_state": "implementing"},
        result_sha="a" * 40,
    )
    projection = rebuild_projection_for_product_job(product, job_id)
    assert projection.get("human_stop_count") == 1
    assert projection.get("loaded_process_context_bytes") == skill.stat().st_size


def test_gate_final_includes_price(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    job_id = "job-44444444444444444444444444444444"
    emit_human_stop(product, job_id=job_id, reason="permit.consume")

    from scripts.agent_journal_lib.gate_emit import emit_gate_and_probes
    from scripts.agent_journal_lib.keys import EMITTER_GATE_FINAL

    class _Report:
        mode = "final"
        overall = "pass"
        exit_code = 0
        platform_on = True
        profile = "default"
        probes = ()

    emit_gate_and_probes(
        product,
        job_id=job_id,
        gate_name="gate.final",
        report=_Report(),
        emitter_id=EMITTER_GATE_FINAL,
        emitter_path=Path(__file__).resolve(),
    )
    projection = rebuild_projection_for_product_job(product, job_id)
    assert projection.get("human_stop_count") == 1
    assert projection.get("loaded_process_context_bytes") == 0


def test_compare_jobs_differs_on_stops_bytes_hashes(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    skill_a = product / "a.md"
    skill_a.write_text("aaa\n", encoding="utf-8")
    skill_b = product / "b.md"
    skill_b.write_text("bbbb\n", encoding="utf-8")
    job_a = "job-55555555555555555555555555555555"
    job_b = "job-66666666666666666666666666666666"

    emit_surface_enter(product, job_id=job_a, role="skill", path=skill_a)
    emit_human_stop(product, job_id=job_a, reason="human.in_out")
    from scripts.agent_journal_lib.emit import write_job_event

    write_job_event(product, job_a, {"type": "ready_for_closeout"}, result_sha="b" * 40)

    emit_surface_enter(product, job_id=job_b, role="skill", path=skill_b)
    emit_human_stop(product, job_id=job_b, reason="human.in_out")
    emit_human_stop(product, job_id=job_b, reason="permit.issue")
    write_job_event(product, job_b, {"type": "ready_for_closeout"}, result_sha="c" * 40)

    from scripts.agent_journal_lib.read import compare_jobs

    cmp = compare_jobs(product, job_a=job_a, job_b=job_b)
    assert cmp["job_a"]["human_stop_count"] == 1
    assert cmp["job_b"]["human_stop_count"] == 2
    assert (
        cmp["job_a"]["loaded_process_context_bytes"] != cmp["job_b"]["loaded_process_context_bytes"]
    )
    assert cmp["surface_hashes_intersection"] == []


def test_late_signature_apr_in_window_and_apb(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    job_id = "job-77777777777777777777777777777777"
    from scripts.agent_journal_lib.emit import write_job_event

    write_job_event(product, job_id, {"type": "ready_for_closeout"}, result_sha="d" * 40)

    reports_root = home / "var" / "process-reports"
    now = datetime.now(UTC)
    report = new_report(
        kind=ReportKind.PROCESS_SCRIPT_FAILURE,
        outcome=ReportOutcome.FAILED,
        surface="test",
        operation="op",
        signature="sig-exact-1",
        expected="e",
        actual="a",
        evidence={},
        job_id=job_id,
        product_id=default_product_id(product),
        occurred_at=now - timedelta(days=2),
    )
    create_report(
        tmp_path / "git-common",
        report,
        reports_root=reports_root,
        journal_product_root=product,
    )

    older = new_report(
        kind=ReportKind.PROCESS_SCRIPT_FAILURE,
        outcome=ReportOutcome.FAILED,
        surface="test",
        operation="op",
        signature="sig-exact-1",
        expected="e",
        actual="a",
        evidence={},
        job_id="job-88888888888888888888888888888888",
        product_id=default_product_id(product),
        occurred_at=now - timedelta(days=20),
    )
    create_report(
        tmp_path / "git-common",
        older,
        reports_root=reports_root,
        journal_product_root=product,
    )

    problems = tmp_path / "problems"
    problems.mkdir()
    (problems / "README.md").write_text(
        "| APB id | Status | Signatures | Linear |\n"
        "|--------|--------|------------|--------|\n"
        "| `APB-0099-test` | open | sig-exact-1 | |\n",
        encoding="utf-8",
    )

    from scripts.agent_journal_lib.read import late_signature

    result = late_signature(
        product,
        job_id=job_id,
        older_than_days=14,
        problems_dir=problems,
        git_common_dir=tmp_path / "git-common",
    )
    apr_sigs = [row["signature"] for row in result.get("apr_matches", [])]
    assert "sig-exact-1" in apr_sigs
    assert all(
        datetime.fromisoformat(row["occurred_at"].replace("Z", "+00:00"))
        >= now - timedelta(days=14)
        for row in result["apr_matches"]
    )
    assert any(hit.get("signature") == "sig-exact-1" for hit in result.get("apb_matches", []))


def test_late_signature_outside_window_empty_apr(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    job_id = "job-99999999999999999999999999999999"
    from scripts.agent_journal_lib.emit import write_job_event

    write_job_event(product, job_id, {"type": "ready_for_closeout"}, result_sha="e" * 40)
    reports_root = home / "var" / "process-reports"
    now = datetime.now(UTC)
    report = new_report(
        kind=ReportKind.PROCESS_SCRIPT_FAILURE,
        outcome=ReportOutcome.FAILED,
        surface="test",
        operation="op",
        signature="sig-old-only",
        expected="e",
        actual="a",
        evidence={},
        job_id=job_id,
        product_id=default_product_id(product),
        occurred_at=now - timedelta(days=30),
    )
    create_report(
        tmp_path / "git-common",
        report,
        reports_root=reports_root,
        journal_product_root=product,
    )

    from scripts.agent_journal_lib.read import late_signature

    result = late_signature(
        product,
        job_id=job_id,
        older_than_days=14,
        problems_dir=tmp_path / "empty-problems",
        git_common_dir=tmp_path / "git-common",
    )
    assert result.get("apr_matches") == []


def test_cli_job_json_default_and_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    job_id = "job-abababababababababababababababab"
    from scripts.agent_journal_lib.emit import write_job_event

    write_job_event(product, job_id, {"type": "ready_for_closeout"}, result_sha="f" * 40)
    monkeypatch.chdir(product)

    from scripts.agent_journal_read import main as read_main

    code = read_main(["job", "--job-id", job_id])
    assert code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["job_id"] == job_id
    assert "human_stop_count" in payload
    assert "tool_input" not in json.dumps(payload)

    code_md = read_main(["job", "--job-id", job_id, "--format", "md"])
    assert code_md == 0
    md = capsys.readouterr().out
    assert md.strip()
    assert "human_stop_count" in md or "stops" in md.lower()


def test_no_chat_only_stop_helper() -> None:
    """Chat-only path must not invent stop emit; helper requires explicit reason."""
    import inspect

    from scripts.agent_journal_lib import human_stop as mod

    sig = inspect.signature(mod.emit_human_stop)
    assert "reason" in sig.parameters
