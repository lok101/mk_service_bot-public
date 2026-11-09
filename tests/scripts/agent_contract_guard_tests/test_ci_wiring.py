from __future__ import annotations

from tests.scripts.agent_contract_guard_tests.fakes import read_repo


def test_check_wrappers_run_agent_contract_gate_with_same_policy() -> None:
    shell = read_repo("scripts/check.sh")
    powershell = read_repo("scripts/check.ps1")
    command_tokens = (
        "python",
        "scripts/agent_contract_guard.py",
        "verify",
        "--ci",
    )
    assert all(token in shell for token in command_tokens)
    assert all(token in powershell for token in command_tokens)
    assert shell.index("agent_contract_guard.py") < shell.index("pytest -q")
    assert powershell.index("agent_contract_guard.py") < powershell.index("'pytest', '-q'")


def test_codeowners_covers_guard_policy_contracts_and_workflow() -> None:
    text = read_repo(".github/CODEOWNERS")
    for pattern in (
        "/.cursor/hooks.json",
        "/.cursor/agent-contract/",
        "/scripts/agent_contract_guard.py",
        "/scripts/agent_contract_guard_lib/",
        "/.cursor/skills/skill-orchestrator/",
        "/.cursor/skills/plan-quality-review/",
        "/.github/CODEOWNERS",
        "/.github/workflows/",
    ):
        assert pattern in text


def test_check_workflow_fetches_contract_baseline_history() -> None:
    text = read_repo(".github/workflows/check.yml")
    assert "fetch-depth: 0" in text
    assert "scripts/check.sh" in text
