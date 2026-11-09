from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.application.technician_warehouse.ports import TechnicianWarehouseRepository
from src.domain.ids import EventId, TechnicianId
from src.domain.technician_warehouse import TechnicianWarehouse
from src.domain.technician_warehouse.events import TechnicianWarehouseTransferObserved
from src.domain.technician_warehouse.models import TechnicianWarehouseLine, TransferDirection
from src.infrastructure.composition.adapters.warehouse_session_finalize import (
    WarehouseSessionFinalizeAdapter,
)
from src.infrastructure.testing.technician_warehouse_fakes import (
    InMemoryTechnicianWarehouseEventStore,
    InMemoryTechnicianWarehouseRepository,
)

_TECHNICIAN_ID = TechnicianId("tech-1")
_SESSION_ID = "tech-1:2026-05-25T00:00:00+00:00"


@dataclass(slots=True)
class _SaveCountingRepository(TechnicianWarehouseRepository):
    inner: InMemoryTechnicianWarehouseRepository
    save_calls: int = 0

    def get(self, technician_id: TechnicianId) -> TechnicianWarehouse:
        return self.inner.get(technician_id)

    def save(self, warehouse: TechnicianWarehouse, *, expected_version: int) -> None:
        self.save_calls += 1
        self.inner.save(warehouse, expected_version=expected_version)

    def has_finalized_transfers_for_session(
        self,
        technician_id: TechnicianId,
        *,
        session_id: str,
    ) -> bool:
        return self.inner.has_finalized_transfers_for_session(
            technician_id,
            session_id=session_id,
        )


def _warehouse_with_delta() -> _SaveCountingRepository:
    inner = InMemoryTechnicianWarehouseRepository(
        event_store=InMemoryTechnicianWarehouseEventStore(),
    )
    repository = _SaveCountingRepository(inner=inner)
    executor = TechnicianWarehouseExecutor(repository=repository)
    executor.execute(
        _TECHNICIAN_ID,
        lambda warehouse: warehouse.count_inventory(
            inventory_id="inv-baseline",
            form_token="token-baseline",
            counted_at=datetime(2026, 5, 1, tzinfo=UTC),
            actual_by_sku={"coffee": Decimal("10")},
            baseline=False,
        ),
    )
    executor.execute(
        _TECHNICIAN_ID,
        lambda warehouse: warehouse.observe_transfer(
            TechnicianWarehouseTransferObserved(
                event_id=EventId("transfer-1"),
                technician_id=_TECHNICIAN_ID,
                occurred_at=datetime(2026, 5, 10, tzinfo=UTC),
                external_document_id="doc-1",
                moment=datetime(2026, 5, 10, tzinfo=UTC),
                updated_at=datetime(2026, 5, 10, tzinfo=UTC),
                observed_at=datetime(2026, 5, 20, tzinfo=UTC),
                content_hash="hash-1",
                direction=TransferDirection.SUPPLY_IN,
                lines=(TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal("2")),),
            ),
        ),
    )
    executor.execute(
        _TECHNICIAN_ID,
        lambda warehouse: warehouse.count_inventory(
            inventory_id="inv-current",
            form_token="token-current",
            counted_at=datetime(2026, 5, 20, tzinfo=UTC),
            actual_by_sku={"coffee": Decimal("12")},
            baseline=False,
        ),
    )
    return repository


def test_warehouse_session_finalize_adapter_is_idempotent_for_same_session_id() -> None:
    repository = _warehouse_with_delta()
    executor = TechnicianWarehouseExecutor(repository=repository)
    adapter = WarehouseSessionFinalizeAdapter(executor=executor)

    saves_before = repository.save_calls
    adapter.finalize_transfers(_SESSION_ID)
    saves_after_first = repository.save_calls - saves_before
    adapter.finalize_transfers(_SESSION_ID)
    saves_after_second = repository.save_calls - saves_before - saves_after_first

    assert saves_after_first == 1
    assert saves_after_second == 0
    events = repository.inner.event_store.get_events_for_technician(_TECHNICIAN_ID)
    finalize_events = [
        event
        for event in events
        if event.__class__.__name__ == "TechnicianWarehouseTransferFinalized"
    ]
    assert len(finalize_events) == 1
