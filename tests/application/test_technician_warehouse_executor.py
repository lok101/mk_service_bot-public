from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.outbox.handler_ids import (
    TECHNICIAN_WAREHOUSE_INVENTORY_TELEGRAM_HANDLER_ID,
)
from src.application.technician_warehouse.errors import TechnicianWarehouseConcurrencyError
from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.application.technician_warehouse.ports import TechnicianWarehouseRepository
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.technician_warehouse import TechnicianWarehouse
from src.domain.technician_warehouse.events import (
    TechnicianWarehouseInventoryCounted,
    TechnicianWarehouseLoadingObserved,
    TechnicianWarehouseTransferObserved,
)
from src.domain.technician_warehouse.models import TechnicianWarehouseLine, TransferDirection
from src.infrastructure.outbox.memory import InMemoryOutboxStore
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher
from src.infrastructure.outbox.serialization import event_from_outbox_document
from src.infrastructure.testing.technician_warehouse_fakes import (
    InMemoryTechnicianWarehouseEventStore,
    InMemoryTechnicianWarehouseRepository,
)

_TECHNICIAN_ID = TechnicianId("tech-1")
_NOW = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)


def _baseline_inventory_event() -> TechnicianWarehouseInventoryCounted:
    return TechnicianWarehouseInventoryCounted(
        event_id=EventId("evt-inv-1"),
        technician_id=_TECHNICIAN_ID,
        occurred_at=_NOW,
        inventory_id="inv-1",
        form_token="token-1",
        counted_at=_NOW,
        lines=(("coffee", Decimal("10")),),
        baseline=True,
    )


def _loading_observed_event() -> TechnicianWarehouseLoadingObserved:
    return TechnicianWarehouseLoadingObserved(
        event_id=EventId("evt-loading-1"),
        technician_id=_TECHNICIAN_ID,
        occurred_at=_NOW,
        source_event_id="loading-1",
        machine_id=MachineId("vm-01"),
        submitted_at=_NOW,
        lines=(TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal("5")),),
    )


def test_in_memory_store_duplicate_event_id_is_idempotent() -> None:
    store = InMemoryTechnicianWarehouseEventStore()
    event = _baseline_inventory_event()
    store.append(_TECHNICIAN_ID, 0, (event,))
    store.append(_TECHNICIAN_ID, 0, (event,))
    assert store.get_events_for_technician(_TECHNICIAN_ID) == [event]


def test_in_memory_store_rejects_stale_expected_version() -> None:
    store = InMemoryTechnicianWarehouseEventStore()
    store.append(_TECHNICIAN_ID, 0, (_baseline_inventory_event(),))
    with pytest.raises(TechnicianWarehouseConcurrencyError):
        store.append(_TECHNICIAN_ID, 0, (_loading_observed_event(),))


def test_in_memory_repository_round_trip() -> None:
    repository = InMemoryTechnicianWarehouseRepository(
        event_store=InMemoryTechnicianWarehouseEventStore(),
    )
    warehouse = repository.get(_TECHNICIAN_ID)
    warehouse.count_inventory(
        inventory_id="inv-1",
        form_token="token-1",
        counted_at=_NOW,
        actual_by_sku={"coffee": Decimal("10")},
        baseline=False,
    )
    repository.save(warehouse, expected_version=0)
    loaded = repository.get(_TECHNICIAN_ID)
    assert loaded.latest_inventory_id == "inv-1"


class ConflictOnceWarehouseRepository(TechnicianWarehouseRepository):
    def __init__(self) -> None:
        self._inner = InMemoryTechnicianWarehouseRepository(
            event_store=InMemoryTechnicianWarehouseEventStore(),
        )
        self.save_calls = 0
        self._conflicted = False

    def get(self, technician_id: TechnicianId) -> TechnicianWarehouse:
        return self._inner.get(technician_id)

    def save(self, warehouse: TechnicianWarehouse, *, expected_version: int) -> None:
        self.save_calls += 1
        if not self._conflicted:
            self._conflicted = True
            raise TechnicianWarehouseConcurrencyError(technician_id=warehouse.technician_id)
        self._inner.save(warehouse, expected_version=expected_version)

    def has_finalized_transfers_for_session(
        self,
        technician_id: TechnicianId,
        *,
        session_id: str,
    ) -> bool:
        return self._inner.has_finalized_transfers_for_session(
            technician_id,
            session_id=session_id,
        )


class AlwaysConflictingWarehouseRepository(TechnicianWarehouseRepository):
    def get(self, technician_id: TechnicianId) -> TechnicianWarehouse:
        return TechnicianWarehouse.empty(technician_id)

    def save(self, warehouse: TechnicianWarehouse, *, expected_version: int) -> None:
        raise TechnicianWarehouseConcurrencyError(technician_id=warehouse.technician_id)

    def has_finalized_transfers_for_session(
        self,
        technician_id: TechnicianId,
        *,
        session_id: str,
    ) -> bool:
        _ = technician_id, session_id
        return False


class SaveCountingWarehouseRepository(TechnicianWarehouseRepository):
    def __init__(self, inner: InMemoryTechnicianWarehouseRepository) -> None:
        self._inner = inner
        self.save_calls = 0

    def get(self, technician_id: TechnicianId) -> TechnicianWarehouse:
        return self._inner.get(technician_id)

    def save(self, warehouse: TechnicianWarehouse, *, expected_version: int) -> None:
        self.save_calls += 1
        self._inner.save(warehouse, expected_version=expected_version)

    def has_finalized_transfers_for_session(
        self,
        technician_id: TechnicianId,
        *,
        session_id: str,
    ) -> bool:
        return self._inner.has_finalized_transfers_for_session(
            technician_id,
            session_id=session_id,
        )


def test_executor_skips_save_when_command_emits_no_events() -> None:
    inner = InMemoryTechnicianWarehouseRepository(
        event_store=InMemoryTechnicianWarehouseEventStore(),
    )
    warehouse = inner.get(_TECHNICIAN_ID)
    warehouse.count_inventory(
        inventory_id="inv-1",
        form_token="token-1",
        counted_at=_NOW,
        actual_by_sku={"coffee": Decimal("10")},
        baseline=False,
    )
    inner.save(warehouse, expected_version=0)

    repository = SaveCountingWarehouseRepository(inner)
    executor = TechnicianWarehouseExecutor(repository=repository)
    executor.execute(
        _TECHNICIAN_ID,
        lambda loaded: loaded.count_inventory(
            inventory_id="inv-1",
            form_token="token-1",
            counted_at=_NOW,
            actual_by_sku={"coffee": Decimal("10")},
            baseline=False,
        ),
    )
    assert repository.save_calls == 0


def test_executor_reloads_and_retries_after_concurrency() -> None:
    repository = ConflictOnceWarehouseRepository()
    executor = TechnicianWarehouseExecutor(repository=repository, max_attempts=3)
    event = executor.execute(
        _TECHNICIAN_ID,
        lambda warehouse: warehouse.count_inventory(
            inventory_id="inv-1",
            form_token="token-1",
            counted_at=_NOW,
            actual_by_sku={"coffee": Decimal("10")},
            baseline=False,
        ),
    )
    assert event.inventory_id == "inv-1"
    assert repository.save_calls == 2


def test_executor_raises_after_retry_budget() -> None:
    executor = TechnicianWarehouseExecutor(
        repository=AlwaysConflictingWarehouseRepository(),
        max_attempts=3,
    )
    with pytest.raises(TechnicianWarehouseConcurrencyError):
        executor.execute(
            _TECHNICIAN_ID,
            lambda warehouse: warehouse.count_inventory(
                inventory_id="inv-1",
                form_token="token-1",
                counted_at=_NOW,
                actual_by_sku={"coffee": Decimal("10")},
                baseline=False,
            ),
        )


class _CollectingPublisher:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


def test_executor_publishes_inventory_counted_after_save() -> None:
    repository = InMemoryTechnicianWarehouseRepository(
        event_store=InMemoryTechnicianWarehouseEventStore(),
    )
    publisher = _CollectingPublisher()
    executor = TechnicianWarehouseExecutor(repository=repository, publisher=publisher)

    result = executor.execute(
        _TECHNICIAN_ID,
        lambda wh: wh.count_inventory(
            inventory_id="inv-pub-1",
            form_token="token-pub-1",
            counted_at=_NOW,
            actual_by_sku={"coffee": Decimal("10")},
            baseline=False,
        ),
    )

    assert isinstance(result, TechnicianWarehouseInventoryCounted)
    assert publisher.events == [result]


def test_executor_does_not_publish_loading_or_transfer_pending() -> None:
    repository = InMemoryTechnicianWarehouseRepository(
        event_store=InMemoryTechnicianWarehouseEventStore(),
    )
    baseline_wh = repository.get(_TECHNICIAN_ID)
    baseline_wh.count_inventory(
        inventory_id="inv-base",
        form_token="token-base",
        counted_at=_NOW,
        actual_by_sku={"coffee": Decimal("10")},
        baseline=False,
    )
    repository.save(baseline_wh, expected_version=0)

    publisher = _CollectingPublisher()
    executor = TechnicianWarehouseExecutor(repository=repository, publisher=publisher)

    loading_event = TechnicianWarehouseLoadingObserved(
        event_id=EventId("evt-load-pub-1"),
        technician_id=_TECHNICIAN_ID,
        occurred_at=_NOW,
        source_event_id="loading-pub-1",
        machine_id=MachineId("vm-01"),
        submitted_at=_NOW,
        lines=(TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal("1")),),
    )
    loading = executor.execute(
        _TECHNICIAN_ID,
        lambda wh: wh.observe_loading(loading_event),
    )
    assert isinstance(loading, TechnicianWarehouseLoadingObserved)
    assert publisher.events == []

    transfer_event = TechnicianWarehouseTransferObserved(
        event_id=EventId("evt-xfer-pub-1"),
        technician_id=_TECHNICIAN_ID,
        occurred_at=_NOW,
        external_document_id="move-pub-1",
        moment=_NOW,
        updated_at=_NOW,
        observed_at=_NOW,
        content_hash="hash-pub-1",
        direction=TransferDirection.SUPPLY_IN,
        lines=(TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal("2")),),
    )
    transfer = executor.execute(
        _TECHNICIAN_ID,
        lambda wh: wh.observe_transfer(transfer_event),
    )
    assert isinstance(transfer, TechnicianWarehouseTransferObserved)
    assert publisher.events == []


def test_executor_republishes_idempotent_inventory_counted() -> None:
    repository = InMemoryTechnicianWarehouseRepository(
        event_store=InMemoryTechnicianWarehouseEventStore(),
    )
    first = TechnicianWarehouseExecutor(repository=repository).execute(
        _TECHNICIAN_ID,
        lambda wh: wh.count_inventory(
            inventory_id="inv-idem-1",
            form_token="token-idem-1",
            counted_at=_NOW,
            actual_by_sku={"coffee": Decimal("4")},
            baseline=False,
        ),
    )
    publisher = _CollectingPublisher()
    executor = TechnicianWarehouseExecutor(repository=repository, publisher=publisher)

    again = executor.execute(
        _TECHNICIAN_ID,
        lambda wh: wh.count_inventory(
            inventory_id="inv-idem-1",
            form_token="token-idem-1",
            counted_at=_NOW,
            actual_by_sku={"coffee": Decimal("4")},
            baseline=False,
        ),
    )

    assert again.event_id == first.event_id
    assert publisher.events == [again]


def test_executor_publishes_inventory_counted_enqueues_telegram_handler() -> None:
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    publisher.subscribe(
        TechnicianWarehouseInventoryCounted,
        TECHNICIAN_WAREHOUSE_INVENTORY_TELEGRAM_HANDLER_ID,
    )
    repository = InMemoryTechnicianWarehouseRepository(
        event_store=InMemoryTechnicianWarehouseEventStore(),
    )
    executor = TechnicianWarehouseExecutor(repository=repository, publisher=publisher)

    result = executor.execute(
        _TECHNICIAN_ID,
        lambda wh: wh.count_inventory(
            inventory_id="inv-enqueue-1",
            form_token="token-enqueue-1",
            counted_at=_NOW,
            actual_by_sku={"coffee": Decimal("2")},
            baseline=False,
        ),
    )

    entries = list(store._entries.values())
    assert len(entries) == 1
    entry = entries[0]
    assert entry["handler_id"] == TECHNICIAN_WAREHOUSE_INVENTORY_TELEGRAM_HANDLER_ID
    assert entry["event_id"] == result.event_id.value
    restored = event_from_outbox_document(entry["event_document"])
    assert isinstance(restored, TechnicianWarehouseInventoryCounted)
    assert restored.event_id == result.event_id
