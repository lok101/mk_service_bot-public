from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.agent_contract_guard_lib.lifecycle import (
    LifecycleError,
    activate_contract,
    deactivate_contract,
    record_verification,
    recover_contract,
)
from scripts.agent_contract_guard_lib.schema import load_contract
from scripts.agent_contract_guard_lib.verification import verify_contract
from tests.scripts.agent_contract_guard_tests.git_fakes import (
    activate_valid_fixture,
    init_git_repo,
    mark_stale,
    prepare_violating_active_contract,
    write_external_contract,
)


def test_activate_atomically_persists_canonical_contract_and_active_pointer(
    tmp_path: Path,
) -> None:
    baseline = init_git_repo(tmp_path)
    input_path = write_external_contract(tmp_path.parent, baseline_ref=baseline)
    active = activate_contract(tmp_path, input_path)
    assert active.canonical_path == (
        ".cursor/agent-contract/contracts/" + active.contract_id + ".json"
    )
    assert (tmp_path / active.canonical_path).is_file()
    assert (tmp_path / ".cursor/agent-contract/runtime/active.json").is_file()


def test_lifecycle_rejects_stale_active_and_recovery_without_reason(
    tmp_path: Path,
) -> None:
    active = activate_valid_fixture(tmp_path)
    mark_stale(tmp_path, active)
    with pytest.raises(LifecycleError, match="AGT001"):
        activate_valid_fixture(tmp_path)
    with pytest.raises(LifecycleError, match="reason"):
        recover_contract(tmp_path, reason="")
    evidence = recover_contract(tmp_path, reason="parent process terminated")
    assert evidence.result == "failed"
    assert evidence.violations[0].code == "AGT001"


def test_deactivate_requires_matching_successful_verify(tmp_path: Path) -> None:
    activate_valid_fixture(tmp_path)
    with pytest.raises(LifecycleError, match="AGT001"):
        deactivate_contract(tmp_path, result="passed", reason="verified")


def test_activate_requires_conversation_id_and_allows_parallel_keys(
    tmp_path: Path,
) -> None:
    baseline = init_git_repo(tmp_path)
    a = write_external_contract(
        tmp_path.parent / "a.json",
        baseline_ref=baseline,
        conversation_id="conv-a",
        allowlist=("src/a.py",),
    )
    b = write_external_contract(
        tmp_path.parent / "b.json",
        baseline_ref=baseline,
        conversation_id="conv-b",
        allowlist=("docs/plans/other.md",),
        contract_id="aec-22222222-2222-2222-2222-222222222222",
    )
    activate_contract(tmp_path, a)
    activate_contract(tmp_path, b)
    pointer = json.loads(
        (tmp_path / ".cursor/agent-contract/runtime/active.json").read_text(encoding="utf-8")
    )
    assert set(pointer["by_conversation"]) == {"conv-a", "conv-b"}
    with pytest.raises(LifecycleError, match="AGT001"):
        activate_contract(tmp_path, a)


def test_activate_ignores_foreign_dirty_tree_outside_own_allowlist(
    tmp_path: Path,
) -> None:
    baseline = init_git_repo(tmp_path)
    from tests.scripts.agent_contract_guard_tests.fakes import write_text

    write_text(tmp_path, "docs/plans/foreign-pack/README.md", "other chat\n")
    input_path = write_external_contract(
        tmp_path.parent / "own.json",
        baseline_ref=baseline,
        conversation_id="conv-a",
        allowlist=("src/allowed.py",),
        preexisting=(),
    )
    activate_contract(tmp_path, input_path)


def test_deactivate_removes_only_own_conversation_key(tmp_path: Path) -> None:
    baseline = init_git_repo(tmp_path)
    a = write_external_contract(
        tmp_path.parent / "a.json",
        baseline_ref=baseline,
        conversation_id="conv-a",
    )
    b = write_external_contract(
        tmp_path.parent / "b.json",
        baseline_ref=baseline,
        conversation_id="conv-b",
        contract_id="aec-22222222-2222-2222-2222-222222222222",
    )
    activate_contract(tmp_path, a)
    activate_contract(tmp_path, b)
    deactivate_contract(tmp_path, result="failed", reason="cleanup", conversation_id="conv-a")
    pointer = json.loads(
        (tmp_path / ".cursor/agent-contract/runtime/active.json").read_text(encoding="utf-8")
    )
    assert set(pointer["by_conversation"]) == {"conv-b"}


def test_recover_removes_legacy_singleton_pointer(tmp_path: Path) -> None:
    pointer = tmp_path / ".cursor/agent-contract/runtime/active.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_text(
        json.dumps(
            {
                "contract_id": "aec-11111111-1111-1111-1111-111111111111",
                "canonical_path": (
                    ".cursor/agent-contract/contracts/aec-11111111-1111-1111-1111-111111111111.json"
                ),
                "activated_at": "2026-09-14T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    recover_contract(tmp_path, reason="legacy cutover")
    assert not pointer.is_file()


def test_deactivate_passed_after_failed_verify_is_agt001(tmp_path: Path) -> None:
    active = prepare_violating_active_contract(tmp_path)
    contract = load_contract(tmp_path / active.canonical_path, workspace=tmp_path)
    failed = verify_contract(tmp_path, contract, active.activation_snapshot)
    assert failed.passed is False
    record_verification(tmp_path, failed)
    with pytest.raises(LifecycleError, match="AGT001"):
        deactivate_contract(tmp_path, result="passed", reason="verified")
