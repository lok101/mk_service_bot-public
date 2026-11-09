from __future__ import annotations

from src.infrastructure.kitvending.deploy.models import KitVendingMachineRecord
from src.infrastructure.kitvending.deploy.resolution import (
    ResolvedOwner,
    resolve_active_owner,
)


def _rec(vm_id: int, name: str) -> KitVendingMachineRecord:
    return KitVendingMachineRecord(vm_id, name)


def test_head_only_active_selects_head() -> None:
    accounts = [(0, (_rec(1001, "Аппарат [512]"),))]
    result = resolve_active_owner(accounts, "512")
    assert result == ResolvedOwner(
        account_index=0,
        record=_rec(1001, "Аппарат [512]"),
        head_shadow=False,
    )


def test_child_only_active_selects_child() -> None:
    accounts = [(0, ()), (1, (_rec(1001, "Аппарат [512]"),))]
    result = resolve_active_owner(accounts, "512")
    assert isinstance(result, ResolvedOwner)
    assert result.account_index == 1
    assert result.head_shadow is False


def test_head_shadow_selects_child_and_flags_shadow() -> None:
    accounts = [
        (0, (_rec(1001, "Аппарат [512]"),)),
        (1, (_rec(1001, "Аппарат [512]"),)),
    ]
    result = resolve_active_owner(accounts, "512")
    assert isinstance(result, ResolvedOwner)
    assert result.account_index == 1
    assert result.head_shadow is True


def test_inactive_record_with_other_id_is_ignored() -> None:
    accounts = [
        (0, (_rec(9001, "[ X ] [512] старый"), _rec(1001, "Аппарат [512]"))),
    ]
    result = resolve_active_owner(accounts, "512")
    assert isinstance(result, ResolvedOwner)
    assert result.record.vending_machine_id == 1001


def test_only_inactive_returns_not_found() -> None:
    accounts = [(0, (_rec(9001, "[ X ] [512] старый"),))]
    assert resolve_active_owner(accounts, "512") == "machine_not_found_in_kit"


def test_no_matching_code_returns_not_found() -> None:
    accounts = [(0, (_rec(1001, "Аппарат [513]"),))]
    assert resolve_active_owner(accounts, "512") == "machine_not_found_in_kit"


def test_duplicate_same_id_within_account_dedup_to_single_owner() -> None:
    accounts = [
        (0, (_rec(1001, "Аппарат [512] A"), _rec(1001, "Аппарат [512] B"))),
    ]
    result = resolve_active_owner(accounts, "512")
    assert isinstance(result, ResolvedOwner)
    assert result.record.vending_machine_id == 1001


def test_different_ids_within_account_is_ambiguous() -> None:
    accounts = [
        (0, (_rec(1001, "Аппарат [512]"), _rec(2002, "Аппарат [512]"))),
    ]
    assert resolve_active_owner(accounts, "512") == "ambiguous_machine_code"


def test_different_ids_across_accounts_is_ambiguous() -> None:
    accounts = [
        (0, (_rec(1001, "Аппарат [512]"),)),
        (1, (_rec(2002, "Аппарат [512]"),)),
    ]
    assert resolve_active_owner(accounts, "512") == "ambiguous_machine_code"


def test_same_active_id_in_multiple_children_is_ambiguous() -> None:
    accounts = [
        (0, ()),
        (1, (_rec(1001, "Аппарат [512]"),)),
        (2, (_rec(1001, "Аппарат [512]"),)),
    ]
    assert resolve_active_owner(accounts, "512") == "ambiguous_machine_code"
