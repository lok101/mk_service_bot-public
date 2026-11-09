from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.agent_contract_guard_lib.hooks import (
    HookEvent,
    classify_destructive_git,
    classify_foreign_lane_git,
    handle_hook,
    preflight_shell_permission,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(path: Path, *, branch: str = "main") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")
    (path / "README").write_text("x\n", encoding="utf-8")
    _git(path, "add", "README")
    _git(path, "commit", "-m", "init")
    if branch != "main":
        _git(path, "checkout", "-b", branch)
    return path


def test_branch_delete_master_and_main_are_agt008(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "primary", branch="agent/mine")
    for command in (
        "git branch -D master",
        "git branch -d main",
        "git branch --delete main",
        "git.exe branch -D master",
    ):
        message = classify_foreign_lane_git(command, workspace=repo)
        assert message is not None and message.startswith("AGT008")
        response = preflight_shell_permission(repo, command=command, conversation_id="conv-free")
        assert response["permission"] == "deny"
        assert "AGT008" in response["agent_message"]


def test_branch_delete_foreign_agent_is_agt008(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "primary", branch="agent/mine")
    _git(repo, "branch", "agent/other")
    message = classify_foreign_lane_git("git branch -D agent/other", workspace=repo)
    assert message is not None and message.startswith("AGT008")


def test_branch_delete_current_agent_not_agt008(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "primary", branch="agent/mine")
    assert classify_foreign_lane_git("git branch -d agent/mine", workspace=repo) is None


def test_branch_delete_combined_short_options_are_agt008(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "primary", branch="agent/mine")
    for command in (
        "git branch -df master",
        "git branch -Df main",
        "git branch -fd main",
    ):
        message = classify_foreign_lane_git(command, workspace=repo)
        assert message is not None and message.startswith("AGT008")


def test_branch_delete_options_not_only_first_token_are_agt008(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "primary", branch="agent/mine")
    _git(repo, "branch", "agent/other")
    for command in (
        "git branch -f -d master",
        "git branch --force -d main",
        "git branch -f -D agent/other",
    ):
        message = classify_foreign_lane_git(command, workspace=repo)
        assert message is not None and message.startswith("AGT008")


def test_branch_delete_options_after_name_are_agt008(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "primary", branch="agent/mine")
    _git(repo, "branch", "agent/other")
    for command in (
        "git branch master -d",
        "git branch -f master -d",
        "git branch main --delete",
        "git branch --force main --delete",
        "git branch master -df",
        "git branch agent/other -D",
    ):
        message = classify_foreign_lane_git(command, workspace=repo)
        assert message is not None and message.startswith("AGT008")


def test_worktree_add_and_list_not_agt008(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "primary")
    for command in (
        "git worktree add -b agent/shelves ../mk_service_bot-wt/shelves HEAD",
        "git worktree list",
    ):
        assert classify_foreign_lane_git(command, workspace=repo) is None
        assert classify_destructive_git(command, write_allowlist=None) is None


def test_worktree_remove_from_lane_is_agt008(tmp_path: Path) -> None:
    _init_repo(tmp_path / "primary")
    lane = tmp_path / "mk_service_bot-wt" / "shelves"
    lane.mkdir(parents=True)
    # lane cwd: для path-правила достаточно сегмента mk_service_bot-wt
    (lane / ".git").write_text("gitdir: ../.git\n", encoding="utf-8")
    message = classify_foreign_lane_git(
        f"git worktree remove {lane}",
        workspace=lane,
    )
    assert message is not None and message.startswith("AGT008")


def test_worktree_remove_lane_path_from_primary_allowed(tmp_path: Path) -> None:
    primary = _init_repo(tmp_path / "primary")
    lane = tmp_path / "mk_service_bot-wt" / "shelves"
    lane.mkdir(parents=True)
    assert (
        classify_foreign_lane_git(
            f"git worktree remove {lane}",
            workspace=primary,
        )
        is None
    )


def test_worktree_remove_primary_path_denied(tmp_path: Path) -> None:
    primary = _init_repo(tmp_path / "primary")
    message = classify_foreign_lane_git(
        f"git worktree remove {primary}",
        workspace=primary,
    )
    assert message is not None and message.startswith("AGT008")


def test_checkout_and_switch_master_main_are_agt008(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "primary", branch="agent/mine")
    for command in (
        "git checkout master",
        "git checkout main",
        "git switch master",
        "git switch main",
    ):
        message = classify_foreign_lane_git(command, workspace=repo)
        assert message is not None and message.startswith("AGT008")


def test_commit_status_diff_log_not_agt008(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "primary", branch="agent/mine")
    for command in (
        "git status",
        "git diff",
        "git log -1",
        "git commit -m msg",
        "git add README",
    ):
        assert classify_foreign_lane_git(command, workspace=repo) is None


def test_command_chain_with_foreign_lane_git_is_agt008(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "primary", branch="agent/mine")
    message = classify_foreign_lane_git(
        "git status && git branch -D master",
        workspace=repo,
    )
    assert message is not None and message.startswith("AGT008")


def test_before_shell_hook_denies_branch_delete_master(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "primary", branch="agent/mine")
    response = handle_hook(
        repo,
        event=HookEvent.BEFORE_SHELL_EXECUTION,
        payload={
            "conversation_id": "conv-free",
            "command": "git branch -D master",
            "cwd": str(repo),
            "sandbox": False,
        },
    )
    assert response["permission"] == "deny"
    assert "AGT008" in response["agent_message"]
