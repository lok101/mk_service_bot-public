from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.agent_contract_guard_lib.hooks import HookEvent, handle_hook
from scripts.agent_process_report_lib.models import ReportKind, ReportOutcome, new_report
from scripts.agent_process_report_lib.store import create_report
from tests.scripts.agent_contract_guard_tests.git_fakes import activate_executor


def _git_common(workspace: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    )
    raw = Path(result.stdout.strip())
    return raw if raw.is_absolute() else (workspace / raw).resolve()


def test_stop_followup_mentions_report_id_without_subagent_claim(
    tmp_path: Path,
) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    common = _git_common(tmp_path)
    report = create_report(
        common,
        new_report(
            kind=ReportKind.HARD_BOUNDARY_ATTEMPT,
            outcome=ReportOutcome.BLOCKED,
            surface="aec.hook",
            operation="shell",
            signature="agt007",
            expected="deny",
            actual="blocked",
            evidence={},
            conversation_id="conv-test",
            report_id="apr-ffffffff-ffff-ffff-ffff-ffffffffffff",
        ),
    )
    response = handle_hook(
        tmp_path,
        event=HookEvent.STOP,
        payload={
            "conversation_id": "conv-test",
            "status": "completed",
            "loop_count": 0,
        },
    )
    assert "followup_message" in response
    message = response["followup_message"]
    assert report.report_id in message
    assert "report-analyst" in message
    assert "Subagent was already started" not in message or "do not claim" in message
    assert "started Subagent" not in message
