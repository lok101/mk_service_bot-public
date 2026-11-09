from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.agent_contract_guard_lib.attribution import record_attributed_write
from scripts.agent_contract_guard_lib.git_snapshot import (
    GitCommandError,
    collect_git_delta,
    snapshot_preexisting_paths,
)
from scripts.agent_contract_guard_lib.models import ContractRole
from scripts.agent_contract_guard_lib.schema import load_contract
from scripts.agent_contract_guard_lib.verification import verify_contract
from tests.scripts.agent_contract_guard_tests.git_fakes import (
    activate_fixture,
    hashed_path,
    init_git_repo,
    run_git,
    toggle_progress,
    write,
)


def test_git_snapshot_collects_modified_deleted_renamed_and_untracked(
    tmp_path: Path,
) -> None:
    baseline = init_git_repo(tmp_path)
    write(tmp_path, "src/allowed.py", "new\n")
    run_git(tmp_path, "mv", "docs/plans/plan.md", "docs/plans/renamed.md")
    snapshot = collect_git_delta(tmp_path, baseline_ref=baseline)
    assert snapshot.changed_paths == (
        "docs/plans/plan.md",
        "docs/plans/renamed.md",
        "src/allowed.py",
    )


def test_preexisting_snapshot_rejects_missing_path_and_hash_mismatch(
    tmp_path: Path,
) -> None:
    baseline = init_git_repo(tmp_path)
    with pytest.raises(GitCommandError, match="AGT001 preexisting path missing"):
        snapshot_preexisting_paths(
            tmp_path,
            baseline_ref=baseline,
            expected=(hashed_path("missing.txt", "x\n"),),
        )
    write(tmp_path, "notes.txt", "known\n")
    with pytest.raises(GitCommandError, match="AGT001 preexisting hash mismatch"):
        snapshot_preexisting_paths(
            tmp_path,
            baseline_ref=baseline,
            expected=(hashed_path("notes.txt", "other\n"),),
        )


def test_preexisting_manifest_requires_exact_content_hash(tmp_path: Path) -> None:
    baseline = init_git_repo(tmp_path)
    write(tmp_path, "notes.txt", "known\n")
    manifest = snapshot_preexisting_paths(
        tmp_path,
        baseline_ref=baseline,
        expected=(hashed_path("notes.txt", "known\n"),),
    )
    write(tmp_path, "notes.txt", "changed during stage\n")
    assert manifest.changed_since_activation(tmp_path) == ("notes.txt",)


def test_executor_verify_allows_exact_allowlisted_delta_and_progress(
    tmp_path: Path,
) -> None:
    baseline = init_git_repo(tmp_path)
    contract, activation = activate_fixture(
        tmp_path,
        role=ContractRole.EXECUTOR,
        baseline_ref=baseline,
        allowlist=("src/allowed.py", "docs/plans/plan.md"),
    )
    write(tmp_path, "src/allowed.py", "allowed\n")
    toggle_progress(tmp_path / "docs/plans/plan.md")
    assert (
        verify_contract(
            tmp_path,
            contract,
            activation,
            attributed_paths=frozenset({"src/allowed.py", "docs/plans/plan.md"}),
        ).violations
        == ()
    )


def test_verify_reports_sorted_agt002_to_agt005_violations(
    tmp_path: Path,
) -> None:
    baseline = init_git_repo(tmp_path)
    contract, activation = activate_fixture(
        tmp_path,
        role=ContractRole.EXECUTOR,
        baseline_ref=baseline,
        allowlist=("src/allowed.py",),
        protected=("docs/specs/design.md",),
    )
    write(tmp_path, "docs/specs/design.md", "tampered\n")
    write(tmp_path, "src/not-allowed.py", "bad\n")
    result = verify_contract(
        tmp_path,
        contract,
        activation,
        attributed_paths=frozenset({"docs/specs/design.md", "src/not-allowed.py"}),
    )
    assert [(item.code, item.path) for item in result.violations] == sorted(
        [
            ("AGT002", "docs/specs/design.md"),
            ("AGT003", "src/not-allowed.py"),
            ("AGT005", "docs/specs/design.md"),
        ]
    )


def test_reviewer_verify_requires_activation_snapshot_unchanged(
    tmp_path: Path,
) -> None:
    baseline = init_git_repo(tmp_path)
    write(tmp_path, "src/executor.py", "executor delta\n")
    contract, activation = activate_fixture(
        tmp_path,
        role=ContractRole.REVIEWER,
        baseline_ref=baseline,
        preexisting=("src/executor.py",),
    )
    assert verify_contract(tmp_path, contract, activation).violations == ()
    write(tmp_path, "reviewer-note.txt", "forbidden\n")
    assert (
        verify_contract(tmp_path, contract, activation, attributed_paths=frozenset()).violations
        == ()
    )
    record_attributed_write(tmp_path, conversation_id="conv-test", path="reviewer-note.txt")
    assert [
        v.code
        for v in verify_contract(
            tmp_path,
            contract,
            activation,
            attributed_paths=frozenset({"reviewer-note.txt"}),
        ).violations
    ] == ["AGT006"]


def test_verify_reports_agt004_for_plan_task_drift(tmp_path: Path) -> None:
    baseline = init_git_repo(tmp_path)
    contract, activation = activate_fixture(
        tmp_path,
        role=ContractRole.EXECUTOR,
        baseline_ref=baseline,
        allowlist=("docs/plans/plan.md",),
    )
    plan = tmp_path / "docs/plans/plan.md"
    plan.write_text(
        plan.read_text(encoding="utf-8").replace("Выполнить test", "Изменить design spec"),
        encoding="utf-8",
    )
    assert [
        v.code
        for v in verify_contract(
            tmp_path,
            contract,
            activation,
            attributed_paths=frozenset({"docs/plans/plan.md"}),
        ).violations
    ] == ["AGT004"]


def test_verify_rejects_new_symlink_outside_workspace(tmp_path: Path) -> None:
    baseline = init_git_repo(tmp_path)
    contract, activation = activate_fixture(
        tmp_path,
        role=ContractRole.EXECUTOR,
        baseline_ref=baseline,
        allowlist=("escape.txt",),
    )
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = tmp_path / "escape.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    assert [
        v.code
        for v in verify_contract(
            tmp_path,
            contract,
            activation,
            attributed_paths=frozenset({"escape.txt"}),
        ).violations
    ] == ["AGT005"]


def test_executor_verify_allows_declared_preexisting_unchanged(
    tmp_path: Path,
) -> None:
    baseline = init_git_repo(tmp_path)
    write(tmp_path, "notes.txt", "known\n")
    contract, activation = activate_fixture(
        tmp_path,
        role=ContractRole.EXECUTOR,
        baseline_ref=baseline,
        allowlist=("src/allowed.py",),
        preexisting=("notes.txt",),
    )
    assert verify_contract(tmp_path, contract, activation).violations == ()


def test_verify_rejects_extra_and_tampered_canonical_contract(
    tmp_path: Path,
) -> None:
    baseline = init_git_repo(tmp_path)
    contract, activation = activate_fixture(
        tmp_path,
        role=ContractRole.EXECUTOR,
        baseline_ref=baseline,
        allowlist=("src/allowed.py",),
    )
    write(tmp_path, ".cursor/agent-contract/contracts/aec-extra.json", "{}\n")
    extra = verify_contract(
        tmp_path,
        contract,
        activation,
        attributed_paths=frozenset({".cursor/agent-contract/contracts/aec-extra.json"}),
    )
    assert ("AGT005", ".cursor/agent-contract/contracts/aec-extra.json") in [
        (item.code, item.path) for item in extra.violations
    ]
    canonical = tmp_path / (".cursor/agent-contract/contracts/" + contract.contract_id + ".json")
    payload = json.loads(canonical.read_text(encoding="utf-8"))
    payload["write_allowlist"] = ["src/allowed.py", "src/pwned.py"]
    canonical.write_text(json.dumps(payload), encoding="utf-8")
    write(tmp_path, "src/pwned.py", "pwned\n")
    tampered = load_contract(canonical, workspace=tmp_path)
    result = verify_contract(
        tmp_path,
        tampered,
        activation,
        attributed_paths=frozenset(
            {
                canonical.relative_to(tmp_path).as_posix(),
                "src/pwned.py",
            }
        ),
    )
    codes_by_path = {(item.code, item.path) for item in result.violations}
    assert ("AGT005", canonical.relative_to(tmp_path).as_posix()) in codes_by_path
    assert ("AGT003", "src/pwned.py") in codes_by_path


def test_reviewer_verify_rejects_modify_and_delete_of_snapshot(
    tmp_path: Path,
) -> None:
    baseline = init_git_repo(tmp_path)
    write(tmp_path, "src/executor.py", "executor delta\n")
    contract, activation = activate_fixture(
        tmp_path,
        role=ContractRole.REVIEWER,
        baseline_ref=baseline,
        preexisting=("src/executor.py",),
    )
    write(tmp_path, "src/executor.py", "mutated\n")
    assert "AGT006" in [
        item.code for item in verify_contract(tmp_path, contract, activation).violations
    ]
    (tmp_path / "src/executor.py").unlink()
    assert "AGT006" in [
        item.code for item in verify_contract(tmp_path, contract, activation).violations
    ]
