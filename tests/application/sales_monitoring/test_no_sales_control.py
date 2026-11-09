from __future__ import annotations

from src.application.sales_monitoring.no_sales_control import (
    control_blocks_technician_visit,
    control_is_muted,
    engineer_wait_document_id,
    mute_cancel_document_id,
    mute_document_id,
)
from src.domain.ids import MachineId

_MACHINE = MachineId("501")
_OPENED = "evt-open-1"


def test_control_blocks_only_matching_opened_event_id() -> None:
    mute_id = mute_document_id(_MACHINE, _OPENED)
    documents = [{"_id": mute_id}]
    assert control_blocks_technician_visit(documents, machine_id=_MACHINE, opened_event_id=_OPENED)
    assert not control_blocks_technician_visit(
        documents, machine_id=_MACHINE, opened_event_id="evt-open-2"
    )


def test_mute_cancel_lifts_block_and_engineer_wait_holds() -> None:
    mute_id = mute_document_id(_MACHINE, _OPENED)
    documents = [
        {"_id": mute_id},
        {"_id": mute_cancel_document_id(_MACHINE, mute_id)},
    ]
    assert not control_blocks_technician_visit(
        documents, machine_id=_MACHINE, opened_event_id=_OPENED
    )
    documents.append({"_id": engineer_wait_document_id(_MACHINE, _OPENED)})
    assert control_blocks_technician_visit(documents, machine_id=_MACHINE, opened_event_id=_OPENED)


def test_control_is_muted_only_active_mute() -> None:
    mute_id = mute_document_id(_MACHINE, _OPENED)
    assert control_is_muted(
        [{"_id": mute_id}],
        machine_id=_MACHINE,
        opened_event_id=_OPENED,
    )
    assert not control_is_muted(
        [
            {"_id": mute_id},
            {"_id": mute_cancel_document_id(_MACHINE, mute_id)},
        ],
        machine_id=_MACHINE,
        opened_event_id=_OPENED,
    )
    assert not control_is_muted(
        [{"_id": engineer_wait_document_id(_MACHINE, _OPENED)}],
        machine_id=_MACHINE,
        opened_event_id=_OPENED,
    )
