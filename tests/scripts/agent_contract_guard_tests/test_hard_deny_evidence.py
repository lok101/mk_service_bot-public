from __future__ import annotations

from pathlib import Path

from scripts.agent_contract_guard_lib.hooks import HookEvent, handle_hook
from scripts.agent_process_report_lib.store import list_reports
from tests.scripts.agent_contract_guard_tests.git_fakes import activate_executor
from tests.scripts.agent_contract_guard_tests.test_hook_adapter import DEFAULT_CONVERSATION_ID


def test_hard_deny_apr_evidence_has_fingerprint_or_path_hints(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    common = tmp_path / "git-common"
    common.mkdir()

    def _resolve(_workspace: Path) -> Path | None:
        return common

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "scripts.agent_process_apr_lib.enforcement.resolve_git_common_dir",
        _resolve,
    )

    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "generation_id": "gen-1",
            "tool_name": "SomeOtherTool",
            "tool_input": {"path": "src/secret.py"},
            "workspace_roots": [str(tmp_path)],
        },
    )
    assert response["permission"] == "deny"
    assert "APR001" in str(response.get("agent_message", ""))

    from datetime import timedelta

    reports = list_reports(common, since=timedelta(days=1))
    assert reports
    evidence = reports[0].evidence
    assert evidence.get("command_family") in {"tool", "shell"}
    has_fp = bool(evidence.get("command_fingerprint") or evidence.get("argv_fingerprint"))
    has_hints = bool(evidence.get("path_hints"))
    assert has_fp or has_hints or evidence.get("tool_name") == "SomeOtherTool"
    assert "tool_input" not in evidence
    assert evidence.get("tool_name") == "SomeOtherTool"
    assert "src/secret.py" in evidence.get("path_hints", [])
