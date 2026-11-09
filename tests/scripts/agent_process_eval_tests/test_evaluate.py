from __future__ import annotations

from pathlib import Path

import pytest
from scripts.agent_process_eval_lib.evaluate import (
    evaluate_corpus,
    evaluate_fixture,
    evaluate_trace,
)
from scripts.agent_process_eval_lib.models import Fixture, TraceEvent


def _ev(kind: str, **payload: object) -> TraceEvent:
    return TraceEvent(kind=kind, payload=payload)


def test_evaluate_trace_accepts_green_autonomous_path() -> None:
    events = [
        _ev("state", state="reserved"),
        _ev("state", state="lane_ready"),
        _ev("state", state="designing"),
        _ev("state", state="planning"),
        _ev("state", state="implementing"),
        _ev("state", state="reviewing"),
        _ev("review", result="pass", writer="none"),
        _ev("state", state="verifying"),
        _ev("verification", result="pass", fresh=True),
        _ev("state", state="committing"),
        _ev("commit", branch="agent/demo"),
        _ev("state", state="ready_for_closeout"),
    ]
    result = evaluate_trace(events)
    assert result.ok is True
    assert result.human_stops == 0
    assert result.merge_attempted is False
    assert result.reviewer_wrote is False
    assert result.fresh_review_before_commit is True
    assert result.fresh_verification_before_commit is True


def test_evaluate_trace_counts_material_stop_once() -> None:
    events = [
        _ev("state", state="designing"),
        _ev("human_stop", reason="material_decision"),
        _ev("state", state="designing"),
        _ev("state", state="planning"),
    ]
    result = evaluate_trace(events)
    assert result.human_stops == 1
    assert result.stop_reasons == ("material_decision",)


def test_evaluate_trace_rejects_merge_and_reviewer_write() -> None:
    events = [
        _ev("review", result="pass", writer="reviewer"),
        _ev("merge", target="master"),
    ]
    result = evaluate_trace(events)
    assert result.ok is False
    assert result.reviewer_wrote is True
    assert result.merge_attempted is True


def test_evaluate_trace_rejects_unknown_state_transition() -> None:
    events = [
        _ev("state", state="reserved"),
        _ev("state", state="committing"),  # skip
    ]
    result = evaluate_trace(events)
    assert result.ok is False
    assert "illegal_transition" in result.failures


def test_corpus_has_twelve_fixtures_and_all_match_expected() -> None:
    root = Path("verification/agent-process")
    report = evaluate_corpus(root)
    assert len(report.fixture_ids) == 15
    assert report.all_matched is True
    assert "09-closeout-permit-recovered" in report.fixture_ids
    assert "10-hard-deny-wide-delete" in report.fixture_ids
    assert "11-mcp-nav-allow" in report.fixture_ids
    assert "12-lifecycle-mistaken-recover-deny" in report.fixture_ids
    assert "13-omc-fresh-ok" in report.fixture_ids
    assert "14-omc-skip-implementing" in report.fixture_ids
    assert "15-omc-stale-inputs" in report.fixture_ids


def test_missing_expected_fails_corpus_load(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    expected = tmp_path / "expected"
    fixtures.mkdir()
    expected.mkdir()
    (fixtures / "99-orphan.json").write_text(
        '{"schema_version":1,"id":"99-orphan","title":"x","process":"autonomous-v1","events":[]}',
        encoding="utf-8",
    )
    from scripts.agent_process_eval_lib.evaluate import load_corpus

    with pytest.raises(FileNotFoundError):
        load_corpus(tmp_path)


def test_recovered_trajectory_predicates() -> None:
    events = [
        _ev("state", state="implementing"),
        TraceEvent(
            kind="process_report",
            payload={"kind": "process_script_failure", "outcome": "failed"},
        ),
        _ev("permit", action="issued", operation="remove_unregistered_lane_residue"),
        _ev("hook", permission="allow", code="APR005", apr="APR005"),
        _ev("permit", action="consumed", operation="remove_unregistered_lane_residue"),
        TraceEvent(
            kind="process_report",
            payload={"kind": "permitted_recovery", "outcome": "recovered"},
        ),
    ]
    result = evaluate_trace(events)
    assert result.ok is True
    assert result.recovered_via_permit is True
    assert result.hard_agt_weakened is False
    assert result.human_stops == 0


def test_hard_deny_trajectory_predicates() -> None:
    events = [
        _ev("hook", permission="deny", code="APR001", report_kind="hard_boundary_attempt"),
        TraceEvent(
            kind="process_report",
            payload={"kind": "hard_boundary_attempt", "outcome": "blocked"},
        ),
    ]
    result = evaluate_trace(events)
    assert result.ok is True
    assert result.hard_boundary_reported is True
    assert result.recovered_via_permit is False
    assert result.hard_agt_weakened is False


def test_mcp_nav_allow_trajectory_not_hard_agt_weaken() -> None:
    events = [
        _ev("state", state="implementing"),
        _ev(
            "hook",
            permission="allow",
            code="workspace_navigation",
            tool_name="MCP:move_agent_to_root",
        ),
    ]
    result = evaluate_trace(events)
    assert result.ok is True
    assert result.hard_agt_weakened is False
    assert result.hard_boundary_reported is False


def test_lifecycle_mistaken_recover_deny_trajectory() -> None:
    events = [
        _ev(
            "hook",
            permission="deny",
            code="APR001",
            report_kind="hard_boundary_attempt",
            signature="lifecycle",
        ),
        TraceEvent(
            kind="process_report",
            payload={
                "kind": "hard_boundary_attempt",
                "outcome": "blocked",
                "signature": "lifecycle",
                "actual": "AGT001 recovery requires stale marker",
            },
        ),
    ]
    result = evaluate_trace(events)
    assert result.ok is True
    assert result.hard_boundary_reported is True
    assert result.recovered_via_permit is False
    assert result.hard_agt_weakened is False


def test_residue_permit_path_trajectory_aligned_with_fixture_09() -> None:
    events = [
        TraceEvent(
            kind="process_report",
            payload={
                "kind": "process_script_failure",
                "outcome": "failed",
                "signature": "unregistered_lane_residue",
            },
        ),
        _ev("permit", action="issued", operation="remove_unregistered_lane_residue"),
        _ev("hook", permission="allow", code="APR005", apr="APR005"),
        _ev("permit", action="consumed", operation="remove_unregistered_lane_residue"),
        TraceEvent(
            kind="process_report",
            payload={"kind": "permitted_recovery", "outcome": "recovered"},
        ),
    ]
    result = evaluate_trace(events)
    assert result.ok is True
    assert result.recovered_via_permit is True
    assert result.hard_agt_weakened is False


def _model_check_fixture(*events: TraceEvent) -> Fixture:
    return Fixture(
        schema_version=1,
        id="omc",
        title="omc",
        process="operating-model-case-check",
        events=events,
    )


def test_model_check_fresh_ok_allows_implementing() -> None:
    result = evaluate_fixture(
        _model_check_fixture(
            _ev("state", state="planning"),
            _ev("model_check", verdict="ok"),
            _ev("state", state="implementing"),
        )
    )
    assert result.ok is True
    assert result.failures == ()


def test_legacy_implementing_without_model_check_stays_ok() -> None:
    fixture = Fixture(
        schema_version=1,
        id="legacy",
        title="legacy",
        process="legacy",
        events=(
            _ev("state", state="planning"),
            _ev("state", state="implementing"),
        ),
    )
    result = evaluate_fixture(fixture)
    assert result.ok is True
    assert "model_check_gate" not in result.failures


def test_model_check_skip_and_stale_reject_implementing() -> None:
    skipped = evaluate_fixture(
        _model_check_fixture(
            _ev("state", state="planning"),
            _ev("state", state="implementing"),
        )
    )
    assert skipped.ok is False
    assert "model_check_gate" in skipped.failures
    stale = evaluate_fixture(
        _model_check_fixture(
            _ev("state", state="planning"),
            _ev("model_check", verdict="ok"),
            _ev("inputs_changed"),
            _ev("state", state="implementing"),
        )
    )
    assert stale.ok is False
    assert stale.failures == ("model_check_gate",)
