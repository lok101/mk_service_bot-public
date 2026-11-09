from __future__ import annotations

from dataclasses import dataclass, field

from beartype import beartype

from src.application.technician_warehouse import TechnicianWarehouseConcurrencyError
from src.application.technician_warehouse.ports import (
    TechnicianWarehouseEventStore,
    TechnicianWarehouseRepository,
    has_finalized_transfers_for_session_in_events,
)
from src.domain.ids import TechnicianId
from src.domain.technician_warehouse import TechnicianWarehouse
from src.domain.technician_warehouse.events import WarehouseEvent


@beartype
def _append_events(
    *,
    technician_id: TechnicianId,
    stream: list[WarehouseEvent],
    expected_version: int,
    events: tuple[WarehouseEvent, ...],
) -> None:
    existing_ids = {event.event_id for event in stream}
    if all(event.event_id in existing_ids for event in events):
        return

    if expected_version != len(stream):
        raise TechnicianWarehouseConcurrencyError(technician_id=technician_id)

    for event in events:
        if event.event_id in existing_ids:
            continue
        if event.technician_id != technician_id:
            raise ValueError("event technician_id mismatch")
        stream.append(event)
        existing_ids.add(event.event_id)


@beartype
@dataclass(slots=True)
class InMemoryTechnicianWarehouseEventStore(TechnicianWarehouseEventStore):
    _streams: dict[str, list[WarehouseEvent]] = field(default_factory=dict)

    @beartype
    def append(
        self,
        technician_id: TechnicianId,
        expected_version: int,
        events: tuple[WarehouseEvent, ...],
    ) -> None:
        """Append events to the technician stream with optimistic concurrency.

        Events in one call are inserted sequentially without a transaction.
        The domain currently emits one pending event per command, so a partial
        stream mid-batch is not expected. Multi-event batches and atomicity are
        out of scope until such commands exist.
        """
        stream = self._streams.setdefault(technician_id.value, [])
        _append_events(
            technician_id=technician_id,
            stream=stream,
            expected_version=expected_version,
            events=events,
        )

    @beartype
    def get_events_for_technician(
        self,
        technician_id: TechnicianId,
    ) -> list[WarehouseEvent]:
        return list(self._streams.get(technician_id.value, []))

    @beartype
    def list_technician_ids(self) -> tuple[TechnicianId, ...]:
        return tuple(TechnicianId(technician_id) for technician_id in sorted(self._streams.keys()))

    @beartype
    def delete_all_for_technician(self, technician_id: TechnicianId) -> int:
        stream = self._streams.pop(technician_id.value, [])
        return len(stream)


@beartype
@dataclass(frozen=True, slots=True)
class InMemoryTechnicianWarehouseRepository(TechnicianWarehouseRepository):
    event_store: InMemoryTechnicianWarehouseEventStore

    @beartype
    def get(self, technician_id: TechnicianId) -> TechnicianWarehouse:
        events = self.event_store.get_events_for_technician(technician_id)
        return TechnicianWarehouse.rehydrate(technician_id, events)

    @beartype
    def save(self, warehouse: TechnicianWarehouse, *, expected_version: int) -> None:
        pending = warehouse.collect_events()
        if not pending:
            return
        self.event_store.append(
            warehouse.technician_id,
            expected_version,
            pending,
        )
        warehouse.clear_pending_events()

    @beartype
    def has_finalized_transfers_for_session(
        self,
        technician_id: TechnicianId,
        *,
        session_id: str,
    ) -> bool:
        events = self.event_store.get_events_for_technician(technician_id)
        return has_finalized_transfers_for_session_in_events(events, session_id=session_id)
