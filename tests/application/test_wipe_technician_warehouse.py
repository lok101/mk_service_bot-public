from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.technician_warehouse.wipe_warehouse import (
    WipeTechnicianWarehouse,
    WipeTechnicianWarehouseReport,
)
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.technician_warehouse.events import TechnicianWarehouseLoadingObserved
from src.domain.technician_warehouse.models import TechnicianWarehouseLine
from src.infrastructure.testing.technician_warehouse_fakes import (
    InMemoryTechnicianWarehouseEventStore,
    InMemoryTechnicianWarehouseRepository,
)

_TECH = TechnicianId("tech-wipe")
_T0 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


class _FakeDraftCleanup:
    def __init__(self) -> None:
        self.deleted_for: list[TechnicianId] = []
        self.present = True

    def has_draft_for_technician(self, technician_id: TechnicianId) -> bool:
        _ = technician_id
        return self.present

    def delete_for_technician(self, technician_id: TechnicianId) -> int:
        self.deleted_for.append(technician_id)
        if not self.present:
            return 0
        self.present = False
        return 1


def _seed_one_event(store: InMemoryTechnicianWarehouseEventStore) -> None:
    event = TechnicianWarehouseLoadingObserved(
        event_id=EventId("obs-1"),
        technician_id=_TECH,
        occurred_at=_T0,
        source_event_id="src-1",
        machine_id=MachineId("vm-1"),
        submitted_at=_T0,
        lines=(TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal("1000")),),
    )
    store.append(_TECH, 0, (event,))


def test_wipe_technician_warehouse_dry_run_no_delete() -> None:
    store = InMemoryTechnicianWarehouseEventStore()
    _seed_one_event(store)
    drafts = _FakeDraftCleanup()
    repo = InMemoryTechnicianWarehouseRepository(event_store=store)
    uc = WipeTechnicianWarehouse(
        event_store=store,
        repository=repo,
        draft_cleanup=drafts,
    )
    report = uc.preview(technician_id=_TECH)
    assert isinstance(report, WipeTechnicianWarehouseReport)
    assert report.event_count == 1
    assert report.draft_present is True
    assert report.is_closed is False
    assert len(store.get_events_for_technician(_TECH)) == 1
    assert drafts.deleted_for == []


def test_wipe_technician_warehouse_confirm_deletes_stream_and_drafts() -> None:
    store = InMemoryTechnicianWarehouseEventStore()
    _seed_one_event(store)
    drafts = _FakeDraftCleanup()
    repo = InMemoryTechnicianWarehouseRepository(event_store=store)
    uc = WipeTechnicianWarehouse(
        event_store=store,
        repository=repo,
        draft_cleanup=drafts,
    )
    report = uc.execute(technician_id=_TECH)
    assert report.deleted_events == 1
    assert report.draft_deleted == 1
    assert store.get_events_for_technician(_TECH) == []
    assert drafts.deleted_for == [_TECH]
