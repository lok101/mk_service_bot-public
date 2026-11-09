from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.technician_warehouse.ports import (
    TechnicianWarehouseEventStore,
    TechnicianWarehouseRepository,
    TechnicianWarehouseWipeDraftCleanup,
)
from src.domain.ids import TechnicianId


@beartype
@dataclass(frozen=True, slots=True)
class WipeTechnicianWarehouseReport:
    technician_id: TechnicianId
    event_count: int
    is_closed: bool
    draft_present: bool
    deleted_events: int = 0
    draft_deleted: int = 0


@beartype
@dataclass(frozen=True, slots=True)
class WipeTechnicianWarehouse:
    event_store: TechnicianWarehouseEventStore
    repository: TechnicianWarehouseRepository
    draft_cleanup: TechnicianWarehouseWipeDraftCleanup

    @beartype
    def preview(self, *, technician_id: TechnicianId) -> WipeTechnicianWarehouseReport:
        events = self.event_store.get_events_for_technician(technician_id)
        warehouse = self.repository.get(technician_id)
        return WipeTechnicianWarehouseReport(
            technician_id=technician_id,
            event_count=len(events),
            is_closed=warehouse.is_closed(),
            draft_present=self.draft_cleanup.has_draft_for_technician(technician_id),
        )

    @beartype
    def execute(self, *, technician_id: TechnicianId) -> WipeTechnicianWarehouseReport:
        preview = self.preview(technician_id=technician_id)
        deleted_events = self.event_store.delete_all_for_technician(technician_id)
        draft_deleted = self.draft_cleanup.delete_for_technician(technician_id)
        return WipeTechnicianWarehouseReport(
            technician_id=technician_id,
            event_count=preview.event_count,
            is_closed=preview.is_closed,
            draft_present=preview.draft_present,
            deleted_events=deleted_events,
            draft_deleted=draft_deleted,
        )
