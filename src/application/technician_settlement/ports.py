from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.ids import TechnicianId
from src.domain.technician_settlement import TechnicianSettlement
from src.domain.technician_settlement.events import SettlementEvent


@runtime_checkable
class TechnicianSettlementEventStore(Protocol):
    @beartype
    def append(self, event: SettlementEvent, *, expected_version: int) -> None: ...

    @beartype
    def get_events_for_technician(
        self,
        technician_id: TechnicianId,
    ) -> list[SettlementEvent]: ...

    @beartype
    def count_all(self) -> int: ...

    @beartype
    def delete_all(self) -> int: ...


@runtime_checkable
class TechnicianSettlementRepository(Protocol):
    @property
    def event_store(self) -> TechnicianSettlementEventStore: ...

    @beartype
    def get(self, technician_id: TechnicianId) -> TechnicianSettlement: ...

    @beartype
    def save(self, aggregate: TechnicianSettlement) -> None: ...
