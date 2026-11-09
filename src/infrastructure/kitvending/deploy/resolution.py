from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from beartype import beartype

from src.application.matrix_automation import (
    MatrixDeployFailureReason,
    extract_vending_machine_code,
    is_inactive_vending_machine_name,
)
from src.infrastructure.kitvending.deploy.models import KitVendingMachineRecord


@dataclass(frozen=True, slots=True)
class ResolvedOwner:
    account_index: int
    record: KitVendingMachineRecord
    head_shadow: bool


@beartype
def _active_owner_in_account(
    records: tuple[KitVendingMachineRecord, ...],
    machine_code: str,
) -> KitVendingMachineRecord | MatrixDeployFailureReason | None:
    by_id: dict[int, KitVendingMachineRecord] = {}
    for record in records:
        name = record.vending_machine_name
        if is_inactive_vending_machine_name(name):
            continue
        if extract_vending_machine_code(name) != machine_code:
            continue
        by_id.setdefault(record.vending_machine_id, record)
    if len(by_id) > 1:
        return "ambiguous_machine_code"
    if not by_id:
        return None
    return next(iter(by_id.values()))


@beartype
def resolve_active_owner(
    accounts: Sequence[tuple[int, tuple[KitVendingMachineRecord, ...]]],
    machine_code: str,
) -> ResolvedOwner | MatrixDeployFailureReason:
    matches: list[tuple[int, KitVendingMachineRecord]] = []
    for index, records in accounts:
        owner = _active_owner_in_account(records, machine_code)
        if isinstance(owner, str):
            return owner
        if owner is not None:
            matches.append((index, owner))
    if not matches:
        return "machine_not_found_in_kit"
    if len({record.vending_machine_id for _, record in matches}) > 1:
        return "ambiguous_machine_code"
    children = [(index, record) for index, record in matches if index != 0]
    head = [(index, record) for index, record in matches if index == 0]
    if len(children) > 1:
        return "ambiguous_machine_code"
    if children:
        index, record = children[0]
        return ResolvedOwner(account_index=index, record=record, head_shadow=bool(head))
    index, record = head[0]
    return ResolvedOwner(account_index=index, record=record, head_shadow=False)
