from __future__ import annotations

from pathlib import Path

from scripts.agent_contract_guard_lib.attribution import (
    attributed_paths,
    record_attributed_write,
)
from scripts.agent_contract_guard_lib.models import ContractRole
from scripts.agent_contract_guard_lib.verification import verify_active_contract
from tests.scripts.agent_contract_guard_tests.fakes import APPROVED_SPEC, PLAN_PATH, write_text
from tests.scripts.agent_contract_guard_tests.git_fakes import (
    activate_contract,
    activate_valid_fixture,
    init_git_repo,
    write_external_contract,
)


def test_attribution_records_paths_per_conversation(tmp_path: Path) -> None:
    record_attributed_write(tmp_path, conversation_id="conv-a", path="src/a.py")
    record_attributed_write(tmp_path, conversation_id="conv-a", path="src/b.py")
    record_attributed_write(tmp_path, conversation_id="conv-b", path="docs/plans/x.md")
    assert attributed_paths(tmp_path, "conv-a") == frozenset({"src/a.py", "src/b.py"})
    assert attributed_paths(tmp_path, "conv-b") == frozenset({"docs/plans/x.md"})


def test_local_verify_ignores_unattributed_foreign_dirty_tree(tmp_path: Path) -> None:
    baseline = init_git_repo(tmp_path)
    activate_valid_fixture(
        tmp_path,
        conversation_id="conv-a",
        baseline_ref=baseline,
        allowlist=("src/a.py",),
    )
    write_text(tmp_path, "docs/plans/b/README.md", "other\n")
    result = verify_active_contract(tmp_path, conversation_id="conv-a")
    assert result.passed is True


def test_reviewer_agt006_only_on_attributed_writes(tmp_path: Path) -> None:
    baseline = init_git_repo(tmp_path)
    activate_valid_fixture(
        tmp_path,
        role=ContractRole.REVIEWER,
        conversation_id="conv-a",
        baseline_ref=baseline,
    )
    write_text(tmp_path, "docs/plans/foreign/README.md", "other\n")
    clean = verify_active_contract(tmp_path, conversation_id="conv-a")
    assert clean.passed is True
    record_attributed_write(tmp_path, conversation_id="conv-a", path="notes.txt")
    write_text(tmp_path, "notes.txt", "reviewer wrote\n")
    dirty = verify_active_contract(tmp_path, conversation_id="conv-a")
    assert dirty.passed is False
    assert dirty.violations[0].code == "AGT006"


def test_local_verify_agt003_on_attributed_outside_allowlist(tmp_path: Path) -> None:
    baseline = init_git_repo(tmp_path)
    activate_valid_fixture(
        tmp_path,
        conversation_id="conv-a",
        baseline_ref=baseline,
        allowlist=("src/allowed.py",),
    )
    record_attributed_write(tmp_path, conversation_id="conv-a", path="docs/plans/out.md")
    write_text(tmp_path, "docs/plans/out.md", "leak\n")
    result = verify_active_contract(tmp_path, conversation_id="conv-a")
    assert result.passed is False
    assert result.violations[0].code == "AGT003"


def test_after_file_edit_records_attribution(tmp_path: Path) -> None:
    activate_valid_fixture(tmp_path, conversation_id="conv-a")
    payload = {
        "conversation_id": "conv-a",
        "generation_id": "gen-1",
        "file_path": "src/allowed.py",
        "hook_event_name": "afterFileEdit",
    }
    from scripts.agent_contract_guard_lib.hooks import handle_hook

    handle_hook(tmp_path, event="afterFileEdit", payload=payload)
    assert "src/allowed.py" in attributed_paths(tmp_path, "conv-a")


def test_activate_resets_prior_conversation_attribution(tmp_path: Path) -> None:
    record_attributed_write(tmp_path, conversation_id="conv-a", path="notes.txt")
    assert "notes.txt" in attributed_paths(tmp_path, "conv-a")
    activate_valid_fixture(tmp_path, conversation_id="conv-a")
    assert attributed_paths(tmp_path, "conv-a") == frozenset()


def test_reviewer_verify_ignores_pre_activate_attributions(tmp_path: Path) -> None:
    record_attributed_write(tmp_path, conversation_id="conv-a", path="notes.txt")
    write_text(tmp_path, "notes.txt", "stale\n")
    activate_valid_fixture(
        tmp_path,
        role=ContractRole.REVIEWER,
        conversation_id="conv-a",
    )
    result = verify_active_contract(tmp_path, conversation_id="conv-a")
    assert result.passed is True


def test_attribution_rejects_path_like_conversation_id(tmp_path: Path) -> None:
    record_attributed_write(tmp_path, conversation_id="../hooks", path="src/a.py")
    escaped = tmp_path / ".cursor" / "hooks.json"
    assert not escaped.is_file()
    assert attributed_paths(tmp_path, "../hooks") == frozenset()


def test_local_verify_agt002_on_any_active_approved_input(tmp_path: Path) -> None:
    baseline = init_git_repo(tmp_path)
    path_a = write_external_contract(
        tmp_path.parent / "a.json",
        baseline_ref=baseline,
        conversation_id="conv-a",
        contract_id="aec-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    )
    path_b = write_external_contract(
        tmp_path.parent / "b.json",
        baseline_ref=baseline,
        conversation_id="conv-b",
        contract_id="aec-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    )
    activate_contract(tmp_path, path_a)
    activate_contract(tmp_path, path_b)
    write_text(tmp_path, APPROVED_SPEC, "tampered\n")
    result = verify_active_contract(tmp_path, conversation_id="conv-a")
    assert result.passed is False
    assert any(item.code == "AGT002" for item in result.violations)


def test_semantic_plan_drift_own_plan_agt004(tmp_path: Path) -> None:
    baseline = init_git_repo(tmp_path)
    activate_valid_fixture(tmp_path, conversation_id="conv-a", baseline_ref=baseline)
    plan = tmp_path / PLAN_PATH
    plan.write_text(plan.read_text(encoding="utf-8") + "\n## Задача drift\n", encoding="utf-8")
    result = verify_active_contract(tmp_path, conversation_id="conv-a")
    assert result.passed is False
    assert any(item.code == "AGT004" for item in result.violations)
