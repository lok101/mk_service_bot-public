from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from scripts.agent_process_report_lib.cli import main
from scripts.agent_process_report_lib.models import ReportKind, ReportOutcome, new_report
from scripts.agent_process_report_lib.store import (
    ReportNotFoundError,
    create_report,
    load_report,
)


def _common(tmp_path: Path) -> Path:
    common = tmp_path / "g"
    common.mkdir()
    return common


def test_cli_list_enrich_gc_preserves_unresolved(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    common = _common(tmp_path)
    old = datetime.now(UTC) - timedelta(days=20)
    unresolved = new_report(
        kind=ReportKind.PROCESS_SCRIPT_FAILURE,
        outcome=ReportOutcome.FAILED,
        surface="closeout",
        operation="remove",
        signature="sig.unresolved",
        expected="ok",
        actual="fail",
        evidence={},
        report_id="apr-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        occurred_at=old,
    )
    promoted = new_report(
        kind=ReportKind.HARD_BOUNDARY_ATTEMPT,
        outcome=ReportOutcome.BLOCKED,
        surface="hook",
        operation="Write",
        signature="sig.promoted",
        expected="deny",
        actual="attempt",
        evidence={},
        report_id="apr-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        occurred_at=old,
    )
    create_report(common, unresolved)
    create_report(common, promoted)
    # Mark promoted via enrich + promotion status field used by gc.
    assert (
        main(
            [
                "enrich",
                "--git-common-dir",
                str(common),
                "--report-id",
                promoted.report_id,
                "--root-cause",
                "known pattern",
                "--normalized-signature",
                "sig.promoted.norm",
                "--promotion-status",
                "promoted",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "list",
                "--git-common-dir",
                str(common),
                "--since",
                "30d",
            ]
        )
        == 0
    )
    listed = capsys.readouterr().out
    assert unresolved.report_id in listed
    assert promoted.report_id in listed
    assert "command output" not in listed.lower()

    assert main(["gc", "--git-common-dir", str(common), "--older-than-days", "14"]) == 0
    still = load_report(common, unresolved.report_id)
    assert still.report_id == unresolved.report_id
    with pytest.raises(ReportNotFoundError):
        load_report(common, promoted.report_id)


def test_cli_enrich_unknown_report_id(tmp_path: Path) -> None:
    common = _common(tmp_path)
    code = main(
        [
            "enrich",
            "--git-common-dir",
            str(common),
            "--report-id",
            "apr-cccccccc-cccc-cccc-cccc-cccccccccccc",
            "--root-cause",
            "x",
        ]
    )
    assert code != 0


def test_cli_list_empty_store(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    common = _common(tmp_path)
    assert main(["list", "--git-common-dir", str(common), "--since", "3d"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["count"] == 0
    assert payload["report_ids"] == []


def test_cli_list_default_excludes_conv_free(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    common = _common(tmp_path)
    live = new_report(
        kind=ReportKind.HARD_BOUNDARY_ATTEMPT,
        outcome=ReportOutcome.BLOCKED,
        surface="hook",
        operation="Write",
        signature="sig.live",
        expected="deny",
        actual="attempt",
        evidence={"command_family": "tool"},
        report_id="apr-dddddddd-dddd-dddd-dddd-dddddddddddd",
        conversation_id="conv-live-1",
    )
    noise = new_report(
        kind=ReportKind.HARD_BOUNDARY_ATTEMPT,
        outcome=ReportOutcome.BLOCKED,
        surface="hook",
        operation="Write",
        signature="sig.noise",
        expected="deny",
        actual="attempt",
        evidence={"command_family": "tool"},
        report_id="apr-eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
        conversation_id="conv-free",
    )
    create_report(common, live)
    create_report(common, noise)

    assert main(["list", "--git-common-dir", str(common), "--since", "3d"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert live.report_id in payload["report_ids"]
    assert noise.report_id not in payload["report_ids"]
    assert payload["excluded_count"] == 1
    assert payload.get("by_noise", {}).get("conv-free") == 1
    assert load_report(common, noise.report_id).report_id == noise.report_id


def test_cli_list_include_conv_free_opt_out(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    common = _common(tmp_path)
    noise = new_report(
        kind=ReportKind.PROCESS_SCRIPT_FAILURE,
        outcome=ReportOutcome.FAILED,
        surface="eval",
        operation="fixture",
        signature="sig.noise",
        expected="ok",
        actual="fail",
        evidence={},
        report_id="apr-ffffffff-ffff-ffff-ffff-ffffffffffff",
        conversation_id="conv-free",
    )
    create_report(common, noise)
    assert (
        main(
            [
                "list",
                "--git-common-dir",
                str(common),
                "--since",
                "3d",
                "--include-conv-free",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert noise.report_id in payload["report_ids"]
    assert payload["excluded_count"] == 0


def test_cli_list_live_only_flag(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    common = _common(tmp_path)
    noise = new_report(
        kind=ReportKind.HARD_BOUNDARY_ATTEMPT,
        outcome=ReportOutcome.BLOCKED,
        surface="hook",
        operation="Shell",
        signature="sig.noise",
        expected="deny",
        actual="attempt",
        evidence={},
        report_id="apr-11111111-1111-1111-1111-111111111111",
        conversation_id="conv-free",
    )
    create_report(common, noise)
    assert (
        main(
            [
                "list",
                "--git-common-dir",
                str(common),
                "--since",
                "3d",
                "--include-conv-free",
                "--live-only",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 0
    assert payload["excluded_count"] == 1
