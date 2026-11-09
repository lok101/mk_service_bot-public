from __future__ import annotations

from pathlib import Path

from scripts.agent_contract_guard_lib.models import ContractRole
from scripts.agent_contract_guard_lib.verification import verify_contract_chain
from tests.scripts.agent_contract_guard_tests.git_fakes import (
    amended_plan,
    commit_all,
    init_git_repo,
    init_git_repo_with_guard_without_hooks,
    install_guard_tree_without_hooks,
    write,
    write_canonical_contract,
    write_executor_contract_for_plan,
    write_plan_author_amendment_contract,
)


def test_ci_accepts_final_diff_covered_by_canonical_contracts(
    tmp_path: Path,
) -> None:
    baseline = init_git_repo_with_guard_without_hooks(tmp_path)
    write_canonical_contract(
        tmp_path,
        role=ContractRole.EXECUTOR,
        baseline_ref=baseline,
        allowlist=("src/allowed.py", "tests/test_allowed.py"),
    )
    write(tmp_path, "src/allowed.py", "allowed\n")
    write(tmp_path, "tests/test_allowed.py", "def test_allowed():\n    assert True\n")
    commit_all(tmp_path, "covered executor delta")
    result = verify_contract_chain(tmp_path, base_ref=baseline)
    assert result.bootstrap is False
    assert result.violations == ()


def test_ci_rejects_diff_without_contract_coverage(tmp_path: Path) -> None:
    baseline = init_git_repo_with_guard_without_hooks(tmp_path)
    write(tmp_path, "src/uncovered.py", "uncovered\n")
    commit_all(tmp_path, "uncovered path")
    result = verify_contract_chain(tmp_path, base_ref=baseline)
    assert [(v.code, v.path) for v in result.violations] == [("AGT003", "src/uncovered.py")]


def test_ci_uses_latest_plan_author_semantic_hash(tmp_path: Path) -> None:
    baseline = init_git_repo_with_guard_without_hooks(tmp_path)
    write_executor_contract_for_plan(tmp_path, baseline)
    write_plan_author_amendment_contract(tmp_path, baseline, title="Task 4A")
    write(tmp_path, "docs/plans/plan.md", amended_plan(title="Task 4A"))
    commit_all(tmp_path, "plan-author amendment")
    assert verify_contract_chain(tmp_path, base_ref=baseline).violations == ()


def test_ci_allows_single_bootstrap_when_base_has_no_guard(tmp_path: Path) -> None:
    baseline = init_git_repo(tmp_path)
    install_guard_tree_without_hooks(tmp_path)
    commit_all(tmp_path, "first bootstrap without hooks")
    result = verify_contract_chain(tmp_path, base_ref=baseline)
    assert result.bootstrap is True
    assert ".cursor/agent-contract/schema.json" in result.changed_paths
    assert ".cursor/hooks.json" not in result.changed_paths
    assert result.violations == ()


def test_ci_rejects_hooks_in_first_bootstrap(tmp_path: Path) -> None:
    baseline = init_git_repo(tmp_path)
    install_guard_tree_without_hooks(tmp_path)
    write(tmp_path, ".cursor/hooks.json", "{}\n")
    commit_all(tmp_path, "bootstrap with hooks")
    result = verify_contract_chain(tmp_path, base_ref=baseline)
    assert result.bootstrap is True
    assert ("AGT005", ".cursor/hooks.json") in [(v.code, v.path) for v in result.violations]


def test_ci_does_not_treat_later_guard_edits_as_bootstrap(tmp_path: Path) -> None:
    baseline = init_git_repo_with_guard_without_hooks(tmp_path)
    install_guard_tree_without_hooks(tmp_path, overwrite=True)
    commit_all(tmp_path, "rewrite guard after first install")
    result = verify_contract_chain(tmp_path, base_ref=baseline)
    assert result.bootstrap is False
    assert result.violations == ()


def test_ci_rejects_contract_with_non_ancestor_baseline(tmp_path: Path) -> None:
    baseline = init_git_repo_with_guard_without_hooks(tmp_path)
    write_canonical_contract(
        tmp_path,
        role=ContractRole.EXECUTOR,
        baseline_ref="deadbeef" * 5,
        allowlist=("src/allowed.py",),
    )
    commit_all(tmp_path, "contract with bad baseline")
    result = verify_contract_chain(tmp_path, base_ref=baseline)
    assert [v.code for v in result.violations] == ["AGT001"]


def test_ci_rejects_tampered_approved_input(tmp_path: Path) -> None:
    baseline = init_git_repo_with_guard_without_hooks(tmp_path)
    write_canonical_contract(
        tmp_path,
        role=ContractRole.EXECUTOR,
        baseline_ref=baseline,
        allowlist=("src/allowed.py",),
    )
    write(tmp_path, "docs/specs/design.md", "tampered\n")
    write(tmp_path, "src/allowed.py", "allowed\n")
    commit_all(tmp_path, "tamper approved input")
    result = verify_contract_chain(tmp_path, base_ref=baseline)
    assert ("AGT002", "docs/specs/design.md") in [(v.code, v.path) for v in result.violations]


def test_ci_rejects_final_plan_without_matching_latest_semantic_contract(
    tmp_path: Path,
) -> None:
    baseline = init_git_repo_with_guard_without_hooks(tmp_path)
    write_executor_contract_for_plan(tmp_path, baseline)
    write(tmp_path, "docs/plans/plan.md", amended_plan(title="uncontracted Task 4A"))
    commit_all(tmp_path, "plan drift")
    result = verify_contract_chain(tmp_path, base_ref=baseline)
    assert [v.code for v in result.violations] == ["AGT004"]


def test_ci_skips_codeowners_and_workflow_directory_as_trust_root(
    tmp_path: Path,
) -> None:
    baseline = init_git_repo_with_guard_without_hooks(tmp_path)
    write(
        tmp_path,
        ".github/CODEOWNERS",
        "/.cursor/agent-contract/ @lok101\n/.github/CODEOWNERS @lok101\n",
    )
    write(tmp_path, ".github/workflows/e2e-flows.yml", "name: e2e\n")
    commit_all(tmp_path, "human trust-root edits")
    result = verify_contract_chain(tmp_path, base_ref=baseline)
    assert result.bootstrap is False
    assert result.violations == ()
