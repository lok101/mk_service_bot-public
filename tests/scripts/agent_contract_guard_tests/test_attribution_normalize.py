from __future__ import annotations

from pathlib import Path

from scripts.agent_contract_guard_lib.attribution import (
    attributed_paths,
    record_attributed_write,
)
from scripts.agent_contract_guard_lib.hooks import (
    HookEvent,
    handle_hook,
    preflight_shell_permission,
)
from tests.scripts.agent_contract_guard_tests.git_fakes import activate_executor
from tests.scripts.agent_contract_guard_tests.test_hook_adapter import DEFAULT_CONVERSATION_ID


def test_after_file_edit_normalizes_windows_absolute_to_relative(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("tasks/", "docs/plans/"))
    abs_path = str(
        (tmp_path / "tasks" / "agent-process-report-triage-hygiene" / "TASK.md").resolve()
    )
    response = handle_hook(
        tmp_path,
        event=HookEvent.AFTER_FILE_EDIT,
        payload={
            "conversation_id": DEFAULT_CONVERSATION_ID,
            "generation_id": "gen-1",
            "file_path": abs_path,
            "workspace_roots": [str(tmp_path.resolve())],
        },
    )
    assert response == {}
    paths = attributed_paths(tmp_path, DEFAULT_CONVERSATION_ID)
    assert "tasks/agent-process-report-triage-hygiene/TASK.md" in paths
    assert not any(p.startswith("C:") or p.startswith("c:") for p in paths)


def test_shell_attribution_normalizes_windows_absolute(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("tasks/",))
    abs_path = str((tmp_path / "tasks" / "note.md").resolve())
    command = f'Set-Content -Path "{abs_path}" -Value x'
    response = preflight_shell_permission(
        tmp_path,
        command=command,
        conversation_id=DEFAULT_CONVERSATION_ID,
        workspace_roots=(str(tmp_path.resolve()),),
    )
    assert response.get("permission") == "allow"
    paths = attributed_paths(tmp_path, DEFAULT_CONVERSATION_ID)
    assert "tasks/note.md" in paths
    assert not any(":" in p and p[1] == ":" for p in paths if len(p) > 1)


def test_already_relative_attribution_unchanged(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("tasks/",))
    response = preflight_shell_permission(
        tmp_path,
        command="Set-Content -Path tasks/note.md -Value x",
        conversation_id=DEFAULT_CONVERSATION_ID,
        workspace_roots=(str(tmp_path.resolve()),),
    )
    assert response.get("permission") == "allow"
    assert attributed_paths(tmp_path, DEFAULT_CONVERSATION_ID) == frozenset({"tasks/note.md"})


def test_outside_abs_with_allowlisted_marker_segment_is_denied(tmp_path: Path) -> None:
    """Absolute path outside workspace_roots must not remap via src/tasks markers."""
    activate_executor(tmp_path, allowlist=("src/", "tasks/"))
    outside = str((tmp_path.parent / "other-repo" / "src" / "x.py").resolve())
    response = preflight_shell_permission(
        tmp_path,
        command=f'Set-Content -Path "{outside}" -Value x',
        conversation_id=DEFAULT_CONVERSATION_ID,
        workspace_roots=(str(tmp_path.resolve()),),
    )
    assert response.get("permission") == "deny"
    msg = str(response.get("agent_message", ""))
    assert "AGT003" in msg or "AGT005" in msg or "AGT001" in msg
    paths = attributed_paths(tmp_path, DEFAULT_CONVERSATION_ID)
    assert "src/x.py" not in paths
    assert not any(p == "src/x.py" or p.endswith("/src/x.py") for p in paths)


def test_outside_abs_tasks_marker_not_attributed_as_relative(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("tasks/",))
    outside = str((tmp_path.parent / "foreign" / "tasks" / "note.md").resolve())
    response = preflight_shell_permission(
        tmp_path,
        command=f'Set-Content -Path "{outside}" -Value x',
        conversation_id=DEFAULT_CONVERSATION_ID,
        workspace_roots=(str(tmp_path.resolve()),),
    )
    assert response.get("permission") == "deny"
    paths = attributed_paths(tmp_path, DEFAULT_CONVERSATION_ID)
    assert "tasks/note.md" not in paths


def test_record_attributed_write_normalizes_abs_windows_path_to_relative(
    tmp_path: Path,
) -> None:
    """Direct entry also goes through _normalize_file_path + workspace root."""
    (tmp_path / "tasks").mkdir(parents=True, exist_ok=True)
    abs_path = str((tmp_path / "tasks" / "note.md").resolve())
    record_attributed_write(tmp_path, conversation_id="conv-a", path=abs_path)
    paths = attributed_paths(tmp_path, "conv-a")
    assert paths == frozenset({"tasks/note.md"})
    assert not any(p.startswith(("C:", "c:")) or (len(p) > 1 and p[1] == ":") for p in paths)
