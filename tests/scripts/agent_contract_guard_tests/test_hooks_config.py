from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from scripts.agent_contract_guard_lib.hooks import (
    official_hook_command,
    official_hooks_config,
    validate_initial_hooks_install,
)
from scripts.agent_contract_guard_lib.paths import PathPolicyError
from tests.scripts.agent_contract_guard_tests.git_fakes import (
    commit_all,
    init_git_repo_with_guard_without_hooks,
    run_git,
    write,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def official_hooks_config_json() -> str:
    return json.dumps(official_hooks_config())


def test_hooks_config_uses_one_fail_closed_guard_command() -> None:
    config = json.loads(Path(".cursor/hooks.json").read_text(encoding="utf-8"))
    assert config["version"] == 1
    expected = {
        "preToolUse",
        "beforeShellExecution",
        "afterFileEdit",
        "stop",
        "subagentStop",
    }
    assert set(config["hooks"]) == expected
    assert config == official_hooks_config()
    for event in expected:
        command = config["hooks"][event][0]["command"]
        assert command == official_hook_command(event)
        assert "CURSOR_PROJECT_DIR" in command
        assert "CLAUDE_PROJECT_DIR" in command
    for event in ("preToolUse", "beforeShellExecution"):
        assert config["hooks"][event][0]["failClosed"] is True
        assert "matcher" not in config["hooks"][event][0]
    for event in ("stop", "subagentStop"):
        assert config["hooks"][event][0]["loop_limit"] == 3
        assert "failClosed" not in config["hooks"][event][0]
    assert "failClosed" not in config["hooks"]["afterFileEdit"][0]
    assert "subagent_stop" not in config["hooks"]
    assert "subAgentStop" not in config["hooks"]


def test_initial_hook_install_is_only_bootstrap_policy_exception(
    tmp_path: Path,
) -> None:
    baseline = init_git_repo_with_guard_without_hooks(tmp_path)
    assert validate_initial_hooks_install(
        tmp_path, baseline_ref=baseline, candidate=official_hooks_config_json()
    )
    write(tmp_path, ".cursor/hooks.json", official_hooks_config_json())
    commit_all(tmp_path, "install hooks")
    with pytest.raises(PathPolicyError, match="AGT005"):
        validate_initial_hooks_install(
            tmp_path,
            baseline_ref=run_git(tmp_path, "rev-parse", "HEAD").stdout.strip(),
            candidate=official_hooks_config_json(),
        )


def test_hook_adapter_documents_trusted_workspace_and_cloud_readonly_limits() -> None:
    text = Path("scripts/agent_contract_guard_lib/hooks.py").read_text(encoding="utf-8")
    assert "trusted workspace" in text
    assert "read-only turns" in text
    assert "CI" in text


@pytest.mark.skipif(os.name != "nt", reason="Windows cmd launcher")
def test_hook_launcher_from_foreign_cwd_via_cursor_project_dir() -> None:
    """Relative scripts\\... fails when cwd ≠ repo; CURSOR_PROJECT_DIR must win."""
    payload = '{"conversation_id":"diag","tool_name":"Shell","cwd":"."}'
    env = {**os.environ, "CURSOR_PROJECT_DIR": str(_REPO_ROOT)}
    command = official_hook_command("preToolUse")
    completed = subprocess.run(
        command,
        input=payload,
        text=True,
        capture_output=True,
        cwd=Path(os.environ.get("TEMP", _REPO_ROOT)),
        env=env,
        shell=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert '"permission": "allow"' in completed.stdout or '"permission":"allow"' in completed.stdout
