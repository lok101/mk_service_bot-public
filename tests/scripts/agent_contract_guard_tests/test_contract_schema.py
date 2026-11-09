from __future__ import annotations

from pathlib import Path

import pytest
from scripts.agent_contract_guard_lib.models import ContractRole
from scripts.agent_contract_guard_lib.schema import (
    ContractValidationError,
    load_contract,
    verify_approved_inputs,
)

from .fakes import APPROVED_SPEC, contract_payload, write_contract


def test_contract_schema_accepts_role_specific_contracts(tmp_path: Path) -> None:
    for role in ContractRole:
        path = write_contract(tmp_path, contract_payload(role=role))
        contract = load_contract(path, workspace=tmp_path)
        assert contract.role is role
        assert contract.schema_version == 1


def test_contract_schema_rejects_path_overlap_and_invalid_sha256(tmp_path: Path) -> None:
    payload = contract_payload(role=ContractRole.EXECUTOR)
    payload["write_allowlist"] = ["docs/specs/design.md"]
    payload["protected_paths"] = ["docs/specs/design.md"]
    approved_inputs = payload["approved_inputs"]
    assert isinstance(approved_inputs, list)
    first_input = approved_inputs[0]
    assert isinstance(first_input, dict)
    first_input["sha256"] = "not-a-sha"
    with pytest.raises(ContractValidationError, match="AGT001"):
        load_contract(write_contract(tmp_path, payload), workspace=tmp_path)


def test_contract_schema_rejects_allowlist_protected_overlap(tmp_path: Path) -> None:
    payload = contract_payload(role=ContractRole.EXECUTOR)
    payload["write_allowlist"] = [APPROVED_SPEC]
    payload["protected_paths"] = [APPROVED_SPEC]
    with pytest.raises(ContractValidationError, match="AGT001"):
        load_contract(write_contract(tmp_path, payload), workspace=tmp_path)


def test_approved_input_hash_mismatch_is_agt002(tmp_path: Path) -> None:
    contract_path = write_contract(tmp_path, contract_payload())
    (tmp_path / "docs/specs/design.md").write_text("changed", encoding="utf-8")
    assert [
        item.code
        for item in verify_approved_inputs(
            load_contract(contract_path, workspace=tmp_path),
            workspace=tmp_path,
        )
    ] == ["AGT002"]


def test_approved_input_hash_matches_workspace_text(tmp_path: Path) -> None:
    contract = load_contract(
        write_contract(tmp_path, contract_payload()),
        workspace=tmp_path,
    )
    assert verify_approved_inputs(contract, workspace=tmp_path) == ()


def test_contract_schema_legacy_load_without_conversation_id(tmp_path: Path) -> None:
    payload = contract_payload()
    del payload["conversation_id"]
    path = write_contract(tmp_path, payload)
    contract = load_contract(path, workspace=tmp_path)
    assert contract.conversation_id == ""


def test_contract_schema_requires_conversation_id_on_activate(tmp_path: Path) -> None:
    from scripts.agent_contract_guard_lib.schema import require_conversation_id_for_activate

    payload = contract_payload()
    del payload["conversation_id"]
    path = write_contract(tmp_path, payload)
    contract = load_contract(path, workspace=tmp_path)
    with pytest.raises(ContractValidationError, match="AGT001"):
        require_conversation_id_for_activate(contract)


def test_contract_schema_accepts_bound_conversation_ids(tmp_path: Path) -> None:
    payload = contract_payload()
    payload["conversation_id"] = "conv-a"
    payload["bound_conversation_ids"] = ["conv-task-1"]
    path = write_contract(tmp_path, payload)
    contract = load_contract(path, workspace=tmp_path)
    assert contract.conversation_id == "conv-a"
    assert contract.bound_conversation_ids == ("conv-task-1",)
