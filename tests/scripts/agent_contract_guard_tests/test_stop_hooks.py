from __future__ import annotations

from pathlib import Path

import pytest
from scripts.agent_contract_guard_lib import hooks
from scripts.agent_contract_guard_lib.attribution import record_attributed_write
from scripts.agent_contract_guard_lib.hooks import HookEvent, handle_hook
from tests.scripts.agent_contract_guard_tests.git_fakes import (
    activate_executor,
    active_contract_exists,
    passing_result,
    write,
)


def test_hook_payloads_use_same_guard_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    calls: list[str] = []
    monkeypatch.setattr(
        hooks,
        "verify_active_contract",
        lambda root, **_: calls.append(str(root)) or passing_result(),
    )
    handle_hook(
        tmp_path,
        event=HookEvent.AFTER_FILE_EDIT,
        payload={
            "conversation_id": "conv-test",
            "file_path": str(tmp_path / "src/allowed.py"),
            "edits": [{"old_string": "a", "new_string": "b"}],
        },
    )
    handle_hook(
        tmp_path,
        event=HookEvent.STOP,
        payload={
            "conversation_id": "conv-test",
            "status": "completed",
            "loop_count": 0,
        },
    )
    assert calls == [str(tmp_path), str(tmp_path)]


def test_stop_hooks_return_bounded_followup_on_violation(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    write(tmp_path, "src/forbidden.py", "hidden shell write\n")
    record_attributed_write(tmp_path, conversation_id="conv-test", path="src/forbidden.py")
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
    assert "AGT003 src/forbidden.py" in response["followup_message"]
    assert active_contract_exists(tmp_path)


def test_shell_bypass_is_rejected_by_authoritative_stop_verify(
    tmp_path: Path,
) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    write(tmp_path, "src/bypass.py", "hidden by unclassified shell\n")
    record_attributed_write(tmp_path, conversation_id="conv-test", path="src/bypass.py")
    assert (
        "AGT003"
        in handle_hook(
            tmp_path,
            event=HookEvent.STOP,
            payload={"status": "completed", "loop_count": 0, "conversation_id": "conv-test"},
        )["followup_message"]
    )


def test_subagent_stop_followup_only_for_completed_status(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    write(tmp_path, "src/bypass.py", "from subagent\n")
    aborted = handle_hook(
        tmp_path,
        event=HookEvent.SUBAGENT_STOP,
        payload={
            "subagent_type": "generalPurpose",
            "status": "aborted",
            "task": "t",
            "description": "d",
            "summary": "s",
            "duration_ms": 1,
            "message_count": 1,
            "tool_call_count": 0,
            "loop_count": 0,
            "modified_files": ["src/bypass.py"],
            "agent_transcript_path": None,
            "conversation_id": "conv-test",
        },
    )
    assert aborted == {}
    assert active_contract_exists(tmp_path)
    completed = handle_hook(
        tmp_path,
        event=HookEvent.SUBAGENT_STOP,
        payload={
            "subagent_type": "generalPurpose",
            "status": "completed",
            "task": "t",
            "description": "d",
            "summary": "s",
            "duration_ms": 1,
            "message_count": 1,
            "tool_call_count": 0,
            "loop_count": 0,
            "modified_files": ["src/bypass.py"],
            "agent_transcript_path": None,
            "conversation_id": "conv-test",
        },
    )
    assert "AGT003" in completed["followup_message"]


def test_stop_at_loop_limit_keeps_failed_active_stage_for_orchestrator(
    tmp_path: Path,
) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    write(tmp_path, "src/bypass.py", "still bad\n")
    record_attributed_write(tmp_path, conversation_id="conv-test", path="src/bypass.py")
    response = handle_hook(
        tmp_path,
        event=HookEvent.STOP,
        payload={"status": "completed", "loop_count": 3, "conversation_id": "conv-test"},
    )
    assert "followup_message" in response
    assert active_contract_exists(tmp_path)


def test_after_file_edit_is_audit_not_rollback(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.AFTER_FILE_EDIT,
        payload={
            "conversation_id": "conv-test",
            "file_path": str(tmp_path / "src/allowed.py"),
            "edits": [{"old_string": "a", "new_string": "b"}],
        },
    )
    assert response == {}


def test_stop_without_active_contract_is_noop(tmp_path: Path) -> None:
    assert (
        handle_hook(
            tmp_path,
            event=HookEvent.STOP,
            payload={
                "conversation_id": "conv-free",
                "status": "completed",
                "loop_count": 0,
            },
        )
        == {}
    )


def test_stop_invalid_payload_returns_agt001_followup(tmp_path: Path) -> None:
    activate_executor(tmp_path)
    response = handle_hook(
        tmp_path,
        event=HookEvent.STOP,
        payload={"cwd": "."},
    )
    assert "AGT001" in response["followup_message"]


def test_stop_without_own_contract_is_noop_when_other_chat_active(tmp_path: Path) -> None:
    from tests.scripts.agent_contract_guard_tests.git_fakes import activate_two_conversations

    activate_two_conversations(tmp_path, "conv-a", "conv-b")
    response = handle_hook(
        tmp_path,
        event=HookEvent.STOP,
        payload={
            "conversation_id": "conv-free",
            "status": "completed",
            "loop_count": 0,
        },
    )
    assert response == {}


def test_bound_subagent_stop_verifies_primary_key_not_agt001(tmp_path: Path) -> None:
    from tests.scripts.agent_contract_guard_tests.git_fakes import activate_valid_fixture

    activate_valid_fixture(
        tmp_path,
        conversation_id="conv-a",
        bound_conversation_ids=("conv-task",),
        allowlist=("src/a.py",),
    )
    write(tmp_path, "src/bypass.py", "from bound subagent\n")
    response = handle_hook(
        tmp_path,
        event=HookEvent.SUBAGENT_STOP,
        payload={
            "subagent_type": "generalPurpose",
            "status": "completed",
            "task": "t",
            "description": "d",
            "summary": "s",
            "duration_ms": 1,
            "message_count": 1,
            "tool_call_count": 0,
            "loop_count": 0,
            "modified_files": ["src/bypass.py"],
            "agent_transcript_path": None,
            "conversation_id": "conv-task",
        },
    )
    assert "followup_message" in response
    assert "AGT003" in response["followup_message"]
    assert "AGT001 no active contract" not in response["followup_message"]


def test_ambiguous_bound_conversation_ids_denies_agt001(tmp_path: Path) -> None:
    from tests.scripts.agent_contract_guard_tests.git_fakes import (
        activate_valid_fixture,
        init_git_repo,
        write_external_contract_and_activate,
    )

    baseline = init_git_repo(tmp_path)
    activate_valid_fixture(
        tmp_path,
        conversation_id="conv-a",
        bound_conversation_ids=("conv-task",),
        allowlist=("src/a.py",),
        baseline_ref=baseline,
    )
    write_external_contract_and_activate(
        tmp_path,
        conversation_id="conv-b",
        bound_conversation_ids=("conv-task",),
        allowlist=("docs/plans/b.md",),
        contract_id="aec-22222222-2222-2222-2222-222222222222",
        baseline_ref=baseline,
    )
    response = handle_hook(
        tmp_path,
        event=HookEvent.STOP,
        payload={
            "conversation_id": "conv-task",
            "status": "completed",
            "loop_count": 0,
        },
    )
    assert "followup_message" in response
    assert "AGT001 ambiguous bound_conversation_ids match" in response["followup_message"]
