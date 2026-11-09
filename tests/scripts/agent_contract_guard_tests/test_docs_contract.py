from __future__ import annotations

import ast
from pathlib import Path

from tests.scripts.agent_contract_guard_tests.fakes import read_repo

_CONTROLLED_NEGATIVES = {
    "AGT001": "test_lifecycle_rejects_stale_active_and_recovery_without_reason",
    "AGT002": "test_approved_input_hash_mismatch_is_agt002",
    "AGT003": "test_ci_rejects_diff_without_contract_coverage",
    "AGT004": "test_verify_reports_agt004_for_plan_task_drift",
    "AGT005": "test_verify_reports_sorted_agt002_to_agt005_violations",
    "AGT006": "test_reviewer_verify_requires_activation_snapshot_unchanged",
}


def collect_test_function_names(root: Path) -> set[str]:
    names: set[str] = set()
    for path in root.rglob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                names.add(node.name)
    return names


def test_agent_docs_describe_enforced_contract_boundaries() -> None:
    agents = read_repo("AGENTS.md")
    glossary = read_repo("docs/glossary.md")
    policy = read_repo(".cursor/agent-contract/README.md")
    # AGENTS router: pointer only; boundaries live in policy + glossary (slim-router).
    assert "Agent Execution Contract" in agents
    assert ".cursor/agent-contract/README.md" in agents
    assert "author/execute/review" in policy
    assert "не sandbox" in policy.lower() or "**не** sandbox" in policy.lower()
    assert "**Agent Execution Contract** | plan pipeline ✅" in glossary
    assert "MCP" in policy and "вне scope" in policy


def test_docs_route_to_policy_and_recovery_commands() -> None:
    docs = read_repo("docs/README.md")
    plans = read_repo("docs/plans/README.md")
    policy = read_repo(".cursor/agent-contract/README.md")
    agents = read_repo("AGENTS.md")
    glossary = read_repo("docs/glossary.md")
    assert ".cursor/agent-contract/README.md" in docs
    assert "by_conversation" in docs
    assert "2026-09-15" in plans
    for command in ("status", "verify", "recover", "deactivate"):
        assert command in policy
    assert "by_conversation" in policy
    assert "conversation_id" in policy
    assert "attributed" in policy.lower()
    assert "cross-contract lock" in policy.lower()
    assert "trusted workspace" in policy
    assert "Cloud Agents" in policy
    assert "read-only turns" in policy
    assert "CI gate" in policy
    assert "**не** sandbox" in policy.lower()
    # Slim AGENTS keeps a pointer; conversation-scoped details stay in policy/glossary.
    assert ".cursor/agent-contract/README.md" in agents
    assert "by_conversation" in policy
    assert "conversation-scoped" in glossary or "conversation-scoped" in policy


def test_task_and_index_mark_verified_contract_implementation_done() -> None:
    task = read_repo("tasks/agent-execution-contract/TASK.md")
    index = read_repo("tasks/README.md")
    plan = "docs/plans/2026-09-14-agent-execution-contract/README.md"
    amendment_plan = "2026-09-21-agent-execution-contract-conversation-scope"
    assert plan in task
    assert amendment_plan in task
    assert "2026-09-14-agent-execution-contract/README.md" in index
    assert "| Реализация (v1) | ✅" in task
    assert "execute + Final Gate ✅" in task
    assert "2026-09-15" in task
    assert "в работе" not in task.split("## Scope", 1)[0]


def test_controlled_negative_matrix_names_existing_tests() -> None:
    collected = collect_test_function_names(Path("tests/scripts/agent_contract_guard_tests"))
    assert set(_CONTROLLED_NEGATIVES.values()) <= collected
