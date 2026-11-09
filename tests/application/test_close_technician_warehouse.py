from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.technician_warehouse.close_warehouse import (
    CloseTechnicianWarehouse,
    CloseWarehouseDryRunReport,
)
from src.application.technician_warehouse.errors import (
    CloseTechnicianWarehouseError,
    WarehouseAlreadyClosed,
)
from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.application.technician_warehouse.import_ms_transfers import (
    TechnicianWarehouseImportResult,
)
from src.domain.ids import EventId, TechnicianId
from src.domain.technician_warehouse import (
    SYNTHETIC_ZERO_BASELINE_ID,
    TechnicianWarehouse,
    TechnicianWarehouseLine,
    TechnicianWarehouseTransferObserved,
    TransferDirection,
)
from src.infrastructure.testing.technician_warehouse_fakes import (
    InMemoryTechnicianWarehouseEventStore,
    InMemoryTechnicianWarehouseRepository,
)

_TECH = TechnicianId("tech-1")
_T0 = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
_T1 = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
_T2 = datetime(2026, 7, 1, 11, 0, tzinfo=UTC)
_T3 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


@dataclass
class _FakeImporter:
    calls: list[tuple[TechnicianId, datetime]] = field(default_factory=list)

    async def execute(self, technician_id: TechnicianId, *, anchor_at: datetime):
        self.calls.append((technician_id, anchor_at))
        return TechnicianWarehouseImportResult(
            imported=0,
            updated=0,
            voided=0,
            ignored=0,
            skipped_unresolved=0,
            truncated_non_domain=0,
            transfer_refs=(),
            unmatched_products=(),
        )


def _repo_with_baseline_and_transfers(
    transfers: list[TechnicianWarehouseTransferObserved],
) -> tuple[InMemoryTechnicianWarehouseRepository, TechnicianWarehouseExecutor]:
    store = InMemoryTechnicianWarehouseEventStore()
    repo = InMemoryTechnicianWarehouseRepository(event_store=store)
    executor = TechnicianWarehouseExecutor(repository=repo, publisher=None)
    warehouse = TechnicianWarehouse.empty(_TECH)
    warehouse.count_inventory(
        inventory_id="inv-b",
        form_token="tok-b",
        counted_at=_T0,
        actual_by_sku={"coffee": Decimal("10")},
        baseline=False,
    )
    for transfer in transfers:
        warehouse.observe_transfer(transfer)
    events = warehouse.collect_events()
    store.append(_TECH, expected_version=0, events=events)
    return repo, executor


def _transfer(
    doc_id: str,
    *,
    direction: TransferDirection,
    moment: datetime,
    updated_at: datetime | None = None,
    observed_at: datetime | None = None,
) -> TechnicianWarehouseTransferObserved:
    return TechnicianWarehouseTransferObserved(
        event_id=EventId(f"e-{doc_id}"),
        technician_id=_TECH,
        occurred_at=observed_at or moment,
        external_document_id=doc_id,
        moment=moment,
        updated_at=updated_at or moment,
        observed_at=observed_at or moment,
        content_hash=f"hash-{doc_id}",
        direction=direction,
        lines=(TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal("10")),),
    )


def test_close_confirm_appends_exit_after_import() -> None:
    ret = _transfer("ret-1", direction=TransferDirection.SUPPLY_RETURN, moment=_T2)
    repo, executor = _repo_with_baseline_and_transfers([ret])
    importer = _FakeImporter()
    uc = CloseTechnicianWarehouse(executor=executor, importer=importer)
    closed_at = _T3
    event = asyncio.run(uc.execute(technician_id=_TECH, closed_at=closed_at, confirm=True))
    assert importer.calls == [(_TECH, closed_at)]
    warehouse = repo.get(_TECH)
    assert warehouse.is_closed() is True
    assert event.return_external_document_id == "ret-1"
    assert warehouse.latest_warehouse_delta() is not None
    assert warehouse.latest_warehouse_delta().actual_by_sku == {}


def test_close_dry_run_does_not_append_exit_event() -> None:
    ret = _transfer("ret-1", direction=TransferDirection.SUPPLY_RETURN, moment=_T2)
    repo, executor = _repo_with_baseline_and_transfers([ret])
    version_before = repo.get(_TECH).version
    uc = CloseTechnicianWarehouse(executor=executor, importer=_FakeImporter())
    report = asyncio.run(uc.execute(technician_id=_TECH, closed_at=_T3, confirm=False))
    assert isinstance(report, CloseWarehouseDryRunReport)
    assert report.return_external_document_id == "ret-1"
    assert report.previous_inventory_id == "inv-b"
    assert repo.get(_TECH).version == version_before
    assert repo.get(_TECH).is_closed() is False


def test_close_blocks_when_last_transfer_is_not_supply_return() -> None:
    # Last by key is SUPPLY_IN even if earlier return exists
    earlier_return = _transfer(
        "ret-old",
        direction=TransferDirection.SUPPLY_RETURN,
        moment=_T1,
    )
    last_in = _transfer("in-new", direction=TransferDirection.SUPPLY_IN, moment=_T2)
    _, executor = _repo_with_baseline_and_transfers([earlier_return, last_in])
    uc = CloseTechnicianWarehouse(executor=executor, importer=_FakeImporter())
    with pytest.raises(CloseTechnicianWarehouseError, match="SUPPLY_RETURN|supply_return"):
        asyncio.run(uc.execute(technician_id=_TECH, closed_at=_T3, confirm=True))


def test_close_last_return_tie_break_uses_full_key() -> None:
    # Same moment; higher updated_at wins; must be RETURN
    a = _transfer(
        "a",
        direction=TransferDirection.SUPPLY_IN,
        moment=_T2,
        updated_at=_T2,
        observed_at=_T2,
    )
    b = _transfer(
        "b",
        direction=TransferDirection.SUPPLY_RETURN,
        moment=_T2,
        updated_at=_T3,
        observed_at=_T2,
    )
    repo, executor = _repo_with_baseline_and_transfers([a, b])
    event = asyncio.run(
        CloseTechnicianWarehouse(
            executor=executor,
            importer=_FakeImporter(),
        ).execute(technician_id=_TECH, closed_at=_T3, confirm=True)
    )
    assert event.return_external_document_id == "b"
    assert repo.get(_TECH).is_closed() is True


def test_close_blocks_when_already_closed() -> None:
    ret = _transfer("ret-1", direction=TransferDirection.SUPPLY_RETURN, moment=_T2)
    _, executor = _repo_with_baseline_and_transfers([ret])
    importer = _FakeImporter()
    uc = CloseTechnicianWarehouse(executor=executor, importer=importer)
    asyncio.run(uc.execute(technician_id=_TECH, closed_at=_T3, confirm=True))
    assert len(importer.calls) == 1
    with pytest.raises(WarehouseAlreadyClosed):
        asyncio.run(uc.execute(technician_id=_TECH, closed_at=_T3, confirm=True))
    assert len(importer.calls) == 1


def test_close_ignores_voided_transfer_when_selecting_last_return() -> None:
    live_return = _transfer(
        "ret-live",
        direction=TransferDirection.SUPPLY_RETURN,
        moment=_T1,
    )
    later_voided = _transfer(
        "ret-void",
        direction=TransferDirection.SUPPLY_RETURN,
        moment=_T2,
    )
    store = InMemoryTechnicianWarehouseEventStore()
    repo = InMemoryTechnicianWarehouseRepository(event_store=store)
    executor = TechnicianWarehouseExecutor(repository=repo, publisher=None)
    warehouse = TechnicianWarehouse.empty(_TECH)
    warehouse.count_inventory(
        inventory_id="inv-b",
        form_token="tok-b",
        counted_at=_T0,
        actual_by_sku={"coffee": Decimal("10")},
        baseline=False,
    )
    warehouse.observe_transfer(live_return)
    warehouse.observe_transfer(later_voided)
    warehouse.void_transfer(external_document_id="ret-void", observed_at=_T3)
    store.append(_TECH, expected_version=0, events=warehouse.collect_events())

    event = asyncio.run(
        CloseTechnicianWarehouse(
            executor=executor,
            importer=_FakeImporter(),
        ).execute(technician_id=_TECH, closed_at=_T3, confirm=True)
    )
    assert event.return_external_document_id == "ret-live"
    assert repo.get(_TECH).is_closed() is True


def _repo_with_transfers_only(
    transfers: list[TechnicianWarehouseTransferObserved],
) -> tuple[InMemoryTechnicianWarehouseRepository, TechnicianWarehouseExecutor]:
    store = InMemoryTechnicianWarehouseEventStore()
    repo = InMemoryTechnicianWarehouseRepository(event_store=store)
    executor = TechnicianWarehouseExecutor(repository=repo, publisher=None)
    warehouse = TechnicianWarehouse.empty(_TECH)
    for transfer in transfers:
        warehouse.observe_transfer(transfer)
    store.append(_TECH, expected_version=0, events=warehouse.collect_events())
    return repo, executor


def test_close_dry_run_without_inventory_reports_synthetic_previous_id() -> None:
    # happy dry-run
    ret = _transfer("ret-1", direction=TransferDirection.SUPPLY_RETURN, moment=_T2)
    repo, executor = _repo_with_transfers_only([ret])
    version_before = repo.get(_TECH).version
    report = asyncio.run(
        CloseTechnicianWarehouse(
            executor=executor,
            importer=_FakeImporter(),
        ).execute(technician_id=_TECH, closed_at=_T3, confirm=False)
    )
    assert isinstance(report, CloseWarehouseDryRunReport)
    assert report.previous_inventory_id == SYNTHETIC_ZERO_BASELINE_ID
    assert repo.get(_TECH).version == version_before
    assert repo.get(_TECH).is_closed() is False


def test_close_confirm_without_inventory_appends_exit() -> None:
    # happy confirm
    ret = _transfer("ret-1", direction=TransferDirection.SUPPLY_RETURN, moment=_T2)
    repo, executor = _repo_with_transfers_only([ret])
    event = asyncio.run(
        CloseTechnicianWarehouse(
            executor=executor,
            importer=_FakeImporter(),
        ).execute(technician_id=_TECH, closed_at=_T3, confirm=True)
    )
    warehouse = repo.get(_TECH)
    assert warehouse.is_closed() is True
    assert event.return_external_document_id == "ret-1"
    delta = warehouse.latest_warehouse_delta()
    assert delta is not None
    assert delta.previous_inventory_id == SYNTHETIC_ZERO_BASELINE_ID
    assert delta.actual_by_sku == {}
