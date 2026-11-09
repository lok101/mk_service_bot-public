from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.ids import MachineId


@beartype
def mute_document_id(machine_id: MachineId, opened_event_id: str) -> str:
    return f"no_sales_mute:{machine_id.value}:{opened_event_id}"


@beartype
def mute_cancel_document_id(machine_id: MachineId, mute_event_id: str) -> str:
    return f"no_sales_mute_cancel:{machine_id.value}:{mute_event_id}"


@beartype
def engineer_wait_document_id(machine_id: MachineId, opened_event_id: str) -> str:
    return f"no_sales_engineer_wait:{machine_id.value}:{opened_event_id}"


@beartype
def control_is_muted(
    documents: Sequence[Mapping[str, object]],
    *,
    machine_id: MachineId,
    opened_event_id: str,
) -> bool:
    ids = {document.get("_id") for document in documents}
    mute_id = mute_document_id(machine_id, opened_event_id)
    return mute_id in ids and mute_cancel_document_id(machine_id, mute_id) not in ids


@beartype
def control_blocks_technician_visit(
    documents: Sequence[Mapping[str, object]],
    *,
    machine_id: MachineId,
    opened_event_id: str,
) -> bool:
    waiting = engineer_wait_document_id(machine_id, opened_event_id) in {
        document.get("_id") for document in documents
    }
    return waiting or control_is_muted(
        documents,
        machine_id=machine_id,
        opened_event_id=opened_event_id,
    )


@runtime_checkable
class NoSalesVisitBlockLookup(Protocol):
    def blocks_technician_visit(self, *, machine_id: MachineId, opened_event_id: str) -> bool: ...
