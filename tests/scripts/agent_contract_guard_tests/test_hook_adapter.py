from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.agent_contract_guard_lib.hooks import (
    HookEvent,
    HookPayloadError,
    after_file_edit_response,
    handle_hook,
    parse_hook_payload,
    permission_response,
    stop_response,
)
from scripts.agent_contract_guard_lib.lifecycle import (
    activate_contract,
    bind_generation,
    record_verification,
)
from scripts.agent_contract_guard_lib.models import ContractRole
from tests.scripts.agent_contract_guard_tests.fakes import (
    APPROVED_SPEC,
    PLAN_PATH,
    contract_payload,
    plan_text,
    sha256_text,
    write_text,
)
from tests.scripts.agent_contract_guard_tests.git_fakes import (
    activate_executor,
    activate_executor_and_plan_author,
    activate_executor_with_approved_spec,
    activate_two_conversations,
    activate_valid_fixture,
    deactivate_all,
    init_git_repo,
    mark_stale,
    passing_result_for,
    write,
)

DEFAULT_CONVERSATION_ID = "conv-test"
FREE_CONVERSATION_ID = "conv-free"


def write_payload(*, conversation_id: str, path: str) -> dict[str, object]:
    return {
        "conversation_id": conversation_id,
        "generation_id": "gen-1",
        "tool_name": "Write",
        "tool_input": {"path": path},
        "hook_event_name": "preToolUse",
    }


def delete_payload(*, conversation_id: str, path: str) -> dict[str, object]:
    return {
        "conversation_id": conversation_id,
        "generation_id": "gen-1",
        "tool_name": "Delete",
        "tool_input": {"path": path},
        "hook_event_name": "preToolUse",
    }


def handle_preflight(workspace: Path, payload: dict[str, object]) -> dict[str, str]:
    result = handle_hook(workspace, event=HookEvent.PRE_TOOL_USE, payload=payload)
    return {str(key): str(value) for key, value in result.items()}


def load_hook_fixture(name: str) -> dict[str, object]:
    return json.loads(
        Path("tests/scripts/agent_contract_guard_tests/hook_payloads", name).read_text(
            encoding="utf-8"
        )
    )


@pytest.mark.parametrize(
    ("event", "fixture"),
    [
        ("preToolUse", "pre_tool_use.json"),
        ("beforeShellExecution", "before_shell_execution.json"),
        ("afterFileEdit", "after_file_edit.json"),
        ("stop", "stop.json"),
        ("subagentStop", "subagent_stop.json"),
    ],
)
def test_hook_payload_parser_accepts_official_cursor_shapes(event: str, fixture: str) -> None:
    payload = load_hook_fixture(fixture)
    assert parse_hook_payload(event, payload).event == event


def test_hook_payload_parser_fails_closed_without_required_fields() -> None:
    with pytest.raises(HookPayloadError, match="AGT001"):
        parse_hook_payload("beforeShellExecution", {"cwd": "."})


def test_hook_output_uses_only_fields_supported_by_event() -> None:
    assert permission_response(allow=False, message="AGT003") == {
        "permission": "deny",
        "user_message": "AGT003",
        "agent_message": "AGT003",
    }
    assert stop_response("AGT005 protected path") == {"followup_message": "AGT005 protected path"}
    assert after_file_edit_response() == {}


def test_hook_payload_parser_rejects_subagent_stop_aliases() -> None:
    payload = load_hook_fixture("subagent_stop.json")
    assert payload["hook_event_name"] == "subagentStop"
    parsed = parse_hook_payload("subagentStop", payload)
    assert parsed.event == "subagentStop"
    for alias in ("subagent_stop", "subAgentStop", "SubagentStop"):
        with pytest.raises(HookPayloadError, match="AGT001"):
            parse_hook_payload(alias, payload)


def test_pre_tool_use_denies_known_path_outside_allowlist(
    tmp_path: Path,
) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "tool_name": "Write",
            "tool_input": {"path": "src/forbidden.py", "contents": "secret"},
            "tool_use_id": "tool-1",
            "cwd": str(tmp_path),
        },
    )
    assert response["permission"] == "deny"
    assert "AGT003" in response["agent_message"]


def test_before_shell_execution_denies_obvious_protected_write(
    tmp_path: Path,
) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.BEFORE_SHELL_EXECUTION,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "command": "Set-Content .cursor/hooks.json '{}'",
            "cwd": str(tmp_path),
            "sandbox": False,
        },
    )
    assert response["permission"] == "deny"
    assert "AGT005" in response["agent_message"]


def test_invalid_write_payload_fails_closed(tmp_path: Path) -> None:
    activate_executor(tmp_path)
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={"tool_name": "Write"},
    )
    assert response["permission"] == "deny"
    assert "AGT001" in response["agent_message"]


def test_before_shell_allows_read_only_checks_but_final_verify_remains_authoritative(
    tmp_path: Path,
) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.BEFORE_SHELL_EXECUTION,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "command": "uv run pytest -q",
            "cwd": str(tmp_path),
            "sandbox": False,
        },
    )
    assert response["permission"] == "allow"
    write(tmp_path, "src/bypass.py", "hidden\n")
    from scripts.agent_contract_guard_lib.attribution import record_attributed_write

    record_attributed_write(tmp_path, conversation_id="conv-test", path="src/bypass.py")
    stop = handle_hook(
        tmp_path,
        event=HookEvent.STOP,
        payload={"status": "completed", "loop_count": 0, "conversation_id": "conv-test"},
    )
    assert "AGT003" in stop["followup_message"]


def test_lifecycle_command_allowed_only_in_matching_verified_state(
    tmp_path: Path,
) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    deny_deactivate = handle_hook(
        tmp_path,
        event=HookEvent.BEFORE_SHELL_EXECUTION,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "command": (
                "uv run python scripts/agent_contract_guard.py "
                "deactivate --result passed --reason verified"
            ),
            "cwd": str(tmp_path),
            "sandbox": False,
        },
    )
    assert deny_deactivate["permission"] == "deny"
    record_verification(
        tmp_path,
        passing_result_for(tmp_path),
    )
    allow_deactivate = handle_hook(
        tmp_path,
        event=HookEvent.BEFORE_SHELL_EXECUTION,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "command": (
                "uv run python scripts/agent_contract_guard.py "
                "deactivate --result passed --reason verified"
            ),
            "cwd": str(tmp_path),
            "sandbox": False,
        },
    )
    assert allow_deactivate["permission"] == "allow"


def test_pre_tool_use_allows_absolute_allowlisted_path(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "tool_name": "Write",
            "tool_input": {
                "path": str(tmp_path / "src/allowed.py"),
                "contents": "ok",
            },
            "cwd": str(tmp_path),
            "workspace_roots": [str(tmp_path)],
        },
    )
    assert response == {"permission": "allow"}


def test_pre_tool_use_allows_absolute_root_file_when_workspace_roots_mismatch(
    tmp_path: Path,
) -> None:
    activate_executor(tmp_path, allowlist=("AGENTS.md",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "tool_name": "Write",
            "tool_input": {
                "path": str(tmp_path / "AGENTS.md"),
                "contents": "ok",
            },
            "cwd": str(tmp_path),
            "workspace_roots": [str(tmp_path / "cursor-copy")],
        },
    )
    assert response == {"permission": "allow"}


def test_pre_tool_use_allows_absolute_verification_path_when_workspace_roots_mismatch(
    tmp_path: Path,
) -> None:
    activate_executor(tmp_path, allowlist=("verification/README.md",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "tool_name": "Write",
            "tool_input": {
                "path": str(tmp_path / "verification/README.md"),
                "contents": "ok",
            },
            "cwd": str(tmp_path),
            "workspace_roots": [str(tmp_path / "cursor-copy")],
        },
    )
    assert response == {"permission": "allow"}


def test_pre_tool_use_denies_absolute_path_outside_hook_workspace(
    tmp_path: Path,
) -> None:
    activate_executor(tmp_path, allowlist=("AGENTS.md",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "tool_name": "Write",
            "tool_input": {
                "path": str(tmp_path.parent / "other" / "AGENTS.md"),
                "contents": "ok",
            },
            "cwd": str(tmp_path),
            "workspace_roots": [str(tmp_path / "cursor-copy")],
        },
    )
    assert response["permission"] == "deny"
    assert "AGT003" in response["agent_message"]


def test_activate_allowed_when_no_active_contract(tmp_path: Path) -> None:
    response = handle_hook(
        tmp_path,
        event=HookEvent.BEFORE_SHELL_EXECUTION,
        payload={
            "conversation_id": FREE_CONVERSATION_ID,
            "command": (
                "uv run python scripts/agent_contract_guard.py activate --contract in.json"
            ),
            "cwd": str(tmp_path),
            "sandbox": False,
        },
    )
    assert response == {"permission": "allow"}


def test_recover_allowed_only_when_stale_with_reason(tmp_path: Path) -> None:
    active = activate_executor(tmp_path)
    deny = handle_hook(
        tmp_path,
        event=HookEvent.BEFORE_SHELL_EXECUTION,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "command": ("uv run python scripts/agent_contract_guard.py recover --reason crash"),
            "cwd": str(tmp_path),
            "sandbox": False,
        },
    )
    assert deny["permission"] == "deny"
    mark_stale(tmp_path, active)
    allow = handle_hook(
        tmp_path,
        event=HookEvent.BEFORE_SHELL_EXECUTION,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "command": ("uv run python scripts/agent_contract_guard.py recover --reason crash"),
            "cwd": str(tmp_path),
            "sandbox": False,
        },
    )
    assert allow == {"permission": "allow"}


def test_recover_without_stale_lifecycle_deny(tmp_path: Path) -> None:
    activate_executor(tmp_path)
    response = handle_hook(
        tmp_path,
        event=HookEvent.BEFORE_SHELL_EXECUTION,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "command": ("uv run python scripts/agent_contract_guard.py recover --reason crash"),
            "cwd": str(tmp_path),
            "sandbox": False,
        },
    )
    assert response["permission"] == "deny"
    assert "AGT001 recovery requires stale marker" in response["agent_message"]


def test_passed_deactivate_without_verify_lifecycle_deny(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.BEFORE_SHELL_EXECUTION,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "command": (
                "uv run python scripts/agent_contract_guard.py "
                "deactivate --result passed --reason verified"
            ),
            "cwd": str(tmp_path),
            "sandbox": False,
        },
    )
    assert response["permission"] == "deny"
    assert "AGT001 passed deactivate requires fresh verify" in response["agent_message"]


def test_no_active_shell_lifecycle_recover_deny(tmp_path: Path) -> None:
    deactivate_all(tmp_path)
    response = handle_hook(
        tmp_path,
        event=HookEvent.BEFORE_SHELL_EXECUTION,
        payload={
            "conversation_id": FREE_CONVERSATION_ID,
            "command": ("uv run python scripts/agent_contract_guard.py recover --reason crash"),
            "cwd": str(tmp_path),
            "sandbox": False,
        },
    )
    assert response["permission"] == "deny"
    assert "AGT001 no active contract" in response["agent_message"]


def test_read_tools_allowed_without_active_contract(tmp_path: Path) -> None:
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": FREE_CONVERSATION_ID,
            "tool_name": "Read",
            "tool_input": {"path": "src/x.py"},
        },
    )
    assert response == {"permission": "allow"}


def test_read_check_shell_allowed_without_active_contract(tmp_path: Path) -> None:
    response = handle_hook(
        tmp_path,
        event=HookEvent.BEFORE_SHELL_EXECUTION,
        payload={
            "conversation_id": FREE_CONVERSATION_ID,
            "command": "uv run pytest -q",
            "cwd": str(tmp_path),
            "sandbox": False,
        },
    )
    assert response == {"permission": "allow"}


def test_write_allowed_without_active_contract(tmp_path: Path) -> None:
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": FREE_CONVERSATION_ID,
            "tool_name": "Write",
            "tool_input": {"path": "src/x.py", "contents": "x"},
        },
    )
    assert response == {"permission": "allow"}


def test_mcp_allowed_without_active_contract(tmp_path: Path) -> None:
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": FREE_CONVERSATION_ID,
            "tool_name": "CallDynamicTool",
            "tool_input": {"namespace": "user-linear", "toolName": "save_issue"},
        },
    )
    assert response == {"permission": "allow"}


def test_unclassified_shell_allowed_without_active_contract(tmp_path: Path) -> None:
    response = handle_hook(
        tmp_path,
        event=HookEvent.BEFORE_SHELL_EXECUTION,
        payload={
            "conversation_id": FREE_CONVERSATION_ID,
            "command": "python -c \"open('src/x.py','w').write('x')\"",
            "cwd": str(tmp_path),
            "sandbox": False,
        },
    )
    assert response == {"permission": "allow"}


def test_write_denied_when_active_contract_is_stale(tmp_path: Path) -> None:
    active = activate_executor(tmp_path, allowlist=("src/allowed.py",))
    mark_stale(tmp_path, active)
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "tool_name": "Write",
            "tool_input": {"path": "src/allowed.py", "contents": "x"},
        },
    )
    assert response["permission"] == "deny"
    assert "AGT001" in response["agent_message"]


def test_hook_with_generation_id_allows_when_no_active_contract(
    tmp_path: Path,
) -> None:
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": "conv-1",
            "generation_id": "gen-1",
            "tool_name": "Write",
            "tool_input": {"path": "src/x.py", "contents": "x"},
            "cwd": str(tmp_path),
        },
    )
    assert response == {"permission": "allow"}


def test_hook_unmatched_conversation_does_not_raise_lifecycle_error(
    tmp_path: Path,
) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": "conv-other",
            "generation_id": "gen-1",
            "tool_name": "Write",
            "tool_input": {"path": "src/x.py", "contents": "x"},
            "cwd": str(tmp_path),
        },
    )
    assert "permission" in response


def test_hook_missing_conversation_id_and_cross_contract_lock(tmp_path: Path) -> None:
    payload = {
        "conversation_id": "",
        "generation_id": "gen-1",
        "tool_name": "Write",
        "tool_input": {"path": "src/a.py"},
        "hook_event_name": "preToolUse",
    }
    response = handle_preflight(tmp_path, payload)
    assert response["permission"] == "deny"
    assert "AGT001" in response["agent_message"]


def test_bind_generation_updates_only_own_key(tmp_path: Path) -> None:
    activate_two_conversations(tmp_path, "conv-a", "conv-b")
    bind_generation(tmp_path, "gen-a", conversation_id="conv-a")
    pointer = json.loads(
        (tmp_path / ".cursor/agent-contract/runtime/active.json").read_text(encoding="utf-8")
    )
    assert pointer["by_conversation"]["conv-a"]["owner_generation"] == "gen-a"
    assert pointer["by_conversation"]["conv-b"].get("owner_generation") in (None, "")


def test_hook_lookup_uses_conversation_id_not_workspace_singleton(
    tmp_path: Path,
) -> None:
    activate_executor_and_plan_author(tmp_path)
    allow = handle_preflight(
        tmp_path,
        write_payload(conversation_id="conv-a", path="src/a.py"),
    )
    deny = handle_preflight(
        tmp_path,
        write_payload(conversation_id="conv-b", path="src/a.py"),
    )
    assert allow["permission"] == "allow"
    assert deny["permission"] == "deny"
    assert "AGT003" in deny["agent_message"]


def test_cross_contract_lock_denies_foreign_approved_and_protected(
    tmp_path: Path,
) -> None:
    activate_executor_with_approved_spec(tmp_path, conversation_id="conv-a")
    response = handle_preflight(
        tmp_path,
        write_payload(conversation_id="conv-b", path=APPROVED_SPEC),
    )
    assert response["permission"] == "deny"
    assert response["agent_message"].startswith(("AGT002", "AGT005"))


def _activate_plan_owner_with_approved_plan(workspace: Path, *, conversation_id: str) -> str:
    """Activate plan-author owning PLAN_PATH via approved_inputs; return contract_id."""
    baseline = init_git_repo(workspace)
    write_text(workspace, PLAN_PATH, plan_text())
    write_text(workspace, APPROVED_SPEC, "approved\n")
    contract_id = "aec-aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    payload = contract_payload(
        role=ContractRole.PLAN_AUTHOR,
        baseline_ref=baseline,
        conversation_id=conversation_id,
        allowlist=(PLAN_PATH, "docs/plans/"),
        protected=(),
    )
    payload["contract_id"] = contract_id
    payload["approved_inputs"] = [
        {"path": APPROVED_SPEC, "sha256": sha256_text("approved\n")},
        {"path": PLAN_PATH, "sha256": sha256_text(plan_text())},
    ]
    input_path = workspace.parent / f"input-plan-owner-{workspace.name}.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    activate_contract(workspace, input_path)
    return contract_id


def test_cross_contract_foreign_plan_write_deny_includes_owner_conversation_id(
    tmp_path: Path,
) -> None:
    contract_id = _activate_plan_owner_with_approved_plan(tmp_path, conversation_id="conv-owner")
    response = handle_preflight(
        tmp_path,
        write_payload(conversation_id="conv-other", path=PLAN_PATH),
    )
    assert response["permission"] == "deny"
    msg = response["agent_message"]
    assert msg.startswith("AGT002")
    assert PLAN_PATH in msg
    assert "conversation_id=conv-owner" in msg
    assert f"contract_id={contract_id}" in msg
    assert ":\\" not in msg
    assert not any(part.startswith(("C:/", "c:/")) for part in msg.split())


def test_cross_contract_agt005_protected_includes_owner_hint_no_abs_path_leak(
    tmp_path: Path,
) -> None:
    activate_executor_with_approved_spec(tmp_path, conversation_id="conv-a")
    abs_path = str((tmp_path / APPROVED_SPEC).resolve())
    response = handle_preflight(
        tmp_path,
        {
            **write_payload(conversation_id="conv-b", path=abs_path),
            "workspace_roots": [str(tmp_path.resolve())],
        },
    )
    assert response["permission"] == "deny"
    msg = response["agent_message"]
    assert msg.startswith("AGT005")
    assert APPROVED_SPEC in msg
    assert "conversation_id=conv-a" in msg
    assert "contract_id=" in msg
    assert abs_path not in msg
    assert ":\\" not in msg
    assert not any(token.startswith(("C:/", "c:/")) for token in msg.split())


def test_cross_contract_message_absent_when_no_actives(tmp_path: Path) -> None:
    deactivate_all(tmp_path)
    response = handle_preflight(
        tmp_path,
        write_payload(conversation_id="conv-free", path=PLAN_PATH),
    )
    assert response["permission"] == "allow"
    assert "conversation_id=" not in response.get("agent_message", "")
    assert "cross_contract" not in response.get("agent_message", "")


def test_neighbour_without_active_may_write_builtin_protected(
    tmp_path: Path,
) -> None:
    """Cross-contract lock does not global-lock builtin protected.

    Builtin protected still binds the conversation that *has* an active
    contract (cannot allowlist process skills onto an executor).
    """
    activate_valid_fixture(tmp_path, conversation_id="conv-a")
    neighbour = handle_preflight(
        tmp_path,
        write_payload(conversation_id="conv-b", path=".cursor/hooks.json"),
    )
    assert neighbour["permission"] == "allow"
    own = handle_preflight(
        tmp_path,
        write_payload(conversation_id="conv-a", path=".cursor/hooks.json"),
    )
    assert own["permission"] == "deny"
    assert "AGT005" in own["agent_message"]
    deactivate_all(tmp_path)
    after = handle_preflight(
        tmp_path,
        write_payload(conversation_id="conv-b", path=".cursor/hooks.json"),
    )
    assert after["permission"] == "allow"


def test_neighbour_without_active_may_delete_contract_json(tmp_path: Path) -> None:
    """Catalog `.cursor/agent-contract/` binds only the chat with an active contract.

    Delete of its canonical JSON is AGT005 while that chat is active.
    A chat without an active contract may delete the same path. Deactivate
    drops the pointer and leaves the JSON on disk.
    """
    active = activate_valid_fixture(tmp_path, conversation_id="conv-a")
    contract_json = active.canonical_path
    assert contract_json.startswith(".cursor/agent-contract/contracts/")
    assert contract_json.endswith(".json")
    neighbour = handle_preflight(
        tmp_path,
        delete_payload(conversation_id="conv-b", path=contract_json),
    )
    assert neighbour["permission"] == "allow"
    own = handle_preflight(
        tmp_path,
        delete_payload(conversation_id="conv-a", path=contract_json),
    )
    assert own["permission"] == "deny"
    assert "AGT005" in own["agent_message"]
    deactivate_all(tmp_path)
    assert (tmp_path / contract_json).is_file()
    after = handle_preflight(
        tmp_path,
        delete_payload(conversation_id="conv-a", path=contract_json),
    )
    assert after["permission"] == "allow"


def test_executor_write_own_linked_spec_denied(tmp_path: Path) -> None:
    activate_executor_with_approved_spec(tmp_path, conversation_id="conv-a")
    response = handle_preflight(
        tmp_path,
        write_payload(conversation_id="conv-a", path=APPROVED_SPEC),
    )
    assert response["permission"] == "deny"


def test_subagent_same_conversation_inherits_contract(tmp_path: Path) -> None:
    activate_valid_fixture(tmp_path, conversation_id="conv-a", allowlist=("src/a.py",))
    response = handle_preflight(
        tmp_path,
        write_payload(conversation_id="conv-a", path="src/a.py"),
    )
    assert response["permission"] == "allow"


def test_bound_conversation_ids_apply_same_allowlist(tmp_path: Path) -> None:
    activate_valid_fixture(
        tmp_path,
        conversation_id="conv-a",
        bound_conversation_ids=("conv-task",),
        allowlist=("src/a.py",),
    )
    response = handle_preflight(
        tmp_path,
        write_payload(conversation_id="conv-task", path="src/a.py"),
    )
    assert response["permission"] == "allow"


def test_mcp_denied_when_active_contract_is_stale(tmp_path: Path) -> None:
    active = activate_executor(tmp_path)
    mark_stale(tmp_path, active)
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "tool_name": "CallDynamicTool",
            "tool_input": {"namespace": "user-linear", "toolName": "save_issue"},
        },
    )
    assert response["permission"] == "deny"
    assert "AGT001" in response["agent_message"]


def _lane_root(tmp_path: Path) -> str:
    return str(tmp_path / "mk_service_bot-wt" / "demo-lane")


def test_move_agent_to_root_with_root_path_allowed(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "tool_name": "move_agent_to_root",
            "tool_input": {"rootPath": _lane_root(tmp_path)},
        },
    )
    assert response == {"permission": "allow"}


def test_move_agent_to_root_with_path_key_allowed(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "tool_name": "move_agent_to_root",
            "tool_input": {"path": _lane_root(tmp_path)},
        },
    )
    assert response == {"permission": "allow"}


def test_call_dynamic_tool_app_control_root_move_allowed(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "tool_name": "CallDynamicTool",
            "tool_input": {
                "namespace": "cursor-app-control",
                "toolName": "move_agent_to_root",
                "arguments": {"rootPath": _lane_root(tmp_path)},
                "path": _lane_root(tmp_path),
            },
        },
    )
    assert response == {"permission": "allow"}


def test_call_mcp_tool_app_control_cloned_root_allowed(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "tool_name": "CallMcpTool",
            "tool_input": {
                "server": "cursor-app-control",
                "toolName": "move_agent_to_cloned_root",
                "arguments": {"rootPath": _lane_root(tmp_path)},
            },
        },
    )
    assert response == {"permission": "allow"}


def test_mcp_prefixed_move_agent_to_root_allowed(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "tool_name": "MCP:move_agent_to_root",
            "tool_input": {"path": _lane_root(tmp_path)},
        },
    )
    assert response == {"permission": "allow"}


def test_mcp_prefixed_move_agent_to_cloned_root_allowed(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "tool_name": "MCP:move_agent_to_cloned_root",
            "tool_input": {"path": _lane_root(tmp_path)},
        },
    )
    assert response == {"permission": "allow"}


def test_mcp_prefixed_call_dynamic_tool_move_agent_to_root_allowed(
    tmp_path: Path,
) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "tool_name": "MCP:CallDynamicTool",
            "tool_input": {
                "namespace": "cursor-app-control",
                "toolName": "move_agent_to_root",
                "arguments": {"rootPath": _lane_root(tmp_path)},
                "path": _lane_root(tmp_path),
            },
        },
    )
    assert response == {"permission": "allow"}


def test_mcp_prefixed_call_mcp_tool_move_agent_to_cloned_root_allowed(
    tmp_path: Path,
) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "tool_name": "MCP:CallMcpTool",
            "tool_input": {
                "server": "cursor-app-control",
                "toolName": "move_agent_to_cloned_root",
                "arguments": {"rootPath": _lane_root(tmp_path)},
                "path": _lane_root(tmp_path),
            },
        },
    )
    assert response == {"permission": "allow"}


def test_unknown_mcp_tool_with_path_still_denied(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "tool_name": "MCP:open_resource",
            "tool_input": {"path": "src/allowed.py"},
        },
    )
    assert response["permission"] == "deny"
    assert "AGT001 unsupported write tool" in response["agent_message"]


def test_unknown_tool_with_path_still_denied(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "tool_name": "SomeOtherTool",
            "tool_input": {"path": "src/allowed.py"},
        },
    )
    assert response["permission"] == "deny"
    assert "AGT001 unsupported write tool" in response["agent_message"]


def test_read_lints_allowed_with_active_aec(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "generation_id": "gen-1",
            "tool_name": "ReadLints",
            "tool_input": {"paths": ["src/allowed.py"]},
        },
    )
    assert response == {"permission": "allow"}


def test_list_tool_allowed_with_active_aec(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "generation_id": "gen-1",
            "tool_name": "List",
            "tool_input": {"path": "src/"},
        },
    )
    assert response == {"permission": "allow"}


def test_read_lints_with_path_keys_allowed(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "generation_id": "gen-1",
            "tool_name": "ReadLints",
            "tool_input": {"path": "scripts/agent_contract_guard_lib/hooks.py"},
        },
    )
    assert response == {"permission": "allow"}


def test_navigation_allowed_when_active_contract_is_stale(tmp_path: Path) -> None:
    active = activate_executor(tmp_path, allowlist=("src/allowed.py",))
    mark_stale(tmp_path, active)
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "tool_name": "move_agent_to_root",
            "tool_input": {"path": _lane_root(tmp_path)},
        },
    )
    assert response == {"permission": "allow"}


def test_write_still_denied_when_stale_after_navigation_allow(tmp_path: Path) -> None:
    active = activate_executor(tmp_path, allowlist=("src/allowed.py",))
    mark_stale(tmp_path, active)
    response = handle_hook(
        tmp_path,
        event=HookEvent.PRE_TOOL_USE,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "tool_name": "Write",
            "tool_input": {"path": "src/allowed.py", "contents": "x"},
        },
    )
    assert response["permission"] == "deny"
    assert "AGT001" in response["agent_message"]
