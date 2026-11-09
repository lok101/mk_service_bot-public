from __future__ import annotations

from pathlib import Path

import pytest
from scripts.agent_contract_guard_lib.hooks import (
    HookEvent,
    classify_destructive_git,
    handle_hook,
    preflight_shell_permission,
)
from tests.scripts.agent_contract_guard_tests.git_fakes import activate_executor


def test_stash_list_and_show_not_agt007() -> None:
    for command in ("git stash list", "git stash show"):
        assert classify_destructive_git(command, write_allowlist=None) is None
        response = preflight_shell_permission(
            Path("."),
            command=command,
            conversation_id="conv-free",
        )
        assert response == {"permission": "allow"}


def test_worktree_commands_not_agt007() -> None:
    for command in (
        "git worktree add -b agent/shelves ../mk_service_bot-wt/shelves HEAD",
        "git worktree list",
    ):
        assert classify_destructive_git(command, write_allowlist=None) is None


@pytest.mark.parametrize(
    "command",
    [
        "git stash push -m hide",
        "git stash pop",
        "git stash apply",
        "git stash drop",
        "git reset --hard",
        "git clean -fd",
    ],
)
def test_mutating_stash_reset_clean_are_agt007(command: str) -> None:
    message = classify_destructive_git(command, write_allowlist=None)
    assert message is not None
    assert message.startswith("AGT007")
    assert "lane" in message.lower()
    response = preflight_shell_permission(
        Path("."),
        command=command,
        conversation_id="conv-free",
    )
    assert response["permission"] == "deny"
    assert "AGT007" in response["agent_message"]
    assert "lane" in response["agent_message"].lower()


def test_restore_and_checkout_without_paths_are_agt007() -> None:
    for command in (
        "git restore",
        "git restore --source=HEAD",
        "git checkout --",
        "git checkout HEAD --",
    ):
        message = classify_destructive_git(command, write_allowlist=None)
        assert message is not None and message.startswith("AGT007")


def test_restore_paths_denied_without_active_contract() -> None:
    command = "git restore -- src/allowed.py"
    assert classify_destructive_git(command, write_allowlist=None) is not None
    response = preflight_shell_permission(
        Path("."),
        command=command,
        conversation_id="conv-free",
    )
    assert response["permission"] == "deny"
    assert "AGT007" in response["agent_message"]


def test_restore_path_outside_allowlist_is_agt007(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    command = "git restore -- src/other.py"
    assert classify_destructive_git(command, write_allowlist=("src/allowed.py",)) is not None
    response = preflight_shell_permission(
        tmp_path,
        command=command,
        conversation_id="conv-test",
    )
    assert response["permission"] == "deny"
    assert "AGT007" in response["agent_message"]


def test_restore_paths_inside_allowlist_allowed_with_active_contract(
    tmp_path: Path,
) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py", "docs/plans/x.md"))
    command = "git restore -- src/allowed.py docs/plans/x.md"
    assert (
        classify_destructive_git(
            command,
            write_allowlist=("src/allowed.py", "docs/plans/x.md"),
        )
        is None
    )
    response = preflight_shell_permission(
        tmp_path,
        command=command,
        conversation_id="conv-test",
    )
    assert response == {"permission": "allow"}


def test_checkout_dashed_paths_follow_allowlist(tmp_path: Path) -> None:
    activate_executor(tmp_path, allowlist=("src/allowed.py",))
    assert (
        classify_destructive_git(
            "git checkout HEAD -- src/allowed.py",
            write_allowlist=("src/allowed.py",),
        )
        is None
    )
    assert (
        classify_destructive_git(
            "git checkout HEAD -- src/other.py",
            write_allowlist=("src/allowed.py",),
        )
        is not None
    )


@pytest.mark.parametrize(
    "command",
    [
        "git status && git stash push -m x",
        "git stash list; git reset --hard",
        "uv run pytest -q && git clean -fd",
    ],
)
def test_command_chain_with_destructive_git_is_agt007(command: str) -> None:
    message = classify_destructive_git(command, write_allowlist=None)
    assert message is not None and message.startswith("AGT007")
    response = preflight_shell_permission(
        Path("."),
        command=command,
        conversation_id="conv-free",
    )
    assert response["permission"] == "deny"
    assert "AGT007" in response["agent_message"]


def test_command_chain_without_destructive_git_not_agt007() -> None:
    command = "git status && uv run pytest -q"
    assert classify_destructive_git(command, write_allowlist=None) is None


def test_before_shell_hook_denies_stash_push_without_contract(tmp_path: Path) -> None:
    response = handle_hook(
        tmp_path,
        event=HookEvent.BEFORE_SHELL_EXECUTION,
        payload={
            "conversation_id": "conv-free",
            "command": "git stash push -m hide",
            "cwd": str(tmp_path),
            "sandbox": False,
        },
    )
    assert response["permission"] == "deny"
    assert "AGT007" in response["agent_message"]


def test_before_shell_hook_allows_stash_list_without_contract(tmp_path: Path) -> None:
    response = handle_hook(
        tmp_path,
        event=HookEvent.BEFORE_SHELL_EXECUTION,
        payload={
            "conversation_id": "conv-free",
            "command": "git stash list",
            "cwd": str(tmp_path),
            "sandbox": False,
        },
    )
    assert response == {"permission": "allow"}


@pytest.mark.parametrize(
    "command",
    [
        "git --no-pager stash push -m hide",
        "git -C . stash push",
        "git -c foo.bar=1 stash pop",
        "git.exe stash push -m hide",
        "git --no-pager reset --hard",
        "git -C . clean -fd",
    ],
)
def test_git_global_options_and_exe_mutating_are_agt007(command: str) -> None:
    message = classify_destructive_git(command, write_allowlist=None)
    assert message is not None and message.startswith("AGT007")
    response = preflight_shell_permission(
        Path("."),
        command=command,
        conversation_id="conv-free",
    )
    assert response["permission"] == "deny"
    assert "AGT007" in response["agent_message"]


@pytest.mark.parametrize(
    "command",
    [
        "git --no-pager stash list",
        "git.exe stash list",
        "git -C . stash show",
    ],
)
def test_git_global_options_and_exe_stash_read_not_agt007(command: str) -> None:
    assert classify_destructive_git(command, write_allowlist=None) is None
