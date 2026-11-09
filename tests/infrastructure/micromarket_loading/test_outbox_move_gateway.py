from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.domain.micromarket_loading.move_command_event import MicromarketLoadingMoveCommandRequested
from src.infrastructure.micromarket_loading.move_command_store import (
    InMemoryMicromarketLoadingMoveCommandStore,
)
from src.infrastructure.micromarket_loading.outbox_move_gateway import OutboxMicromarketMoveGateway
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketWarehouseStockSnapshotStore,
)


class _RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[MicromarketLoadingMoveCommandRequested] = []

    def publish(self, event: object) -> None:
        assert isinstance(event, MicromarketLoadingMoveCommandRequested)
        self.events.append(event)


class _SyncMoveClient:
    def create_move(
        self,
        *,
        order_id: str,
        machine_code: str,
        positions: tuple[tuple[str, Decimal], ...],
    ) -> str:
        del machine_code, positions
        return f"ms-{order_id}"

    def delete_move(self, *, move_id: str) -> None:
        del move_id

    def move_moment(self, *, move_id: str) -> datetime | None:
        del move_id
        return None

    def existing_move_for_order_is_stale(self, *, order_id: str, now: datetime) -> bool:
        del order_id, now
        return False

    def warehouse_qty(self, product_code: str) -> Decimal:
        del product_code
        return Decimal("0")

    def warehouse_qty_by_codes(self, product_codes: list[str]) -> dict[str, Decimal]:
        return {code: Decimal("0") for code in product_codes}


def test_outbox_gateway_sync_execute_completes_without_poll_sleep() -> None:
    store = InMemoryMicromarketLoadingMoveCommandStore()
    publisher = _RecordingPublisher()
    from src.application.outbox.micromarket_loading_move import MicromarketLoadingMoveOutboxHandler

    handler = MicromarketLoadingMoveOutboxHandler(
        command_store=store,
        move_client=_SyncMoveClient(),
        clock=lambda: datetime(2026, 10, 30, tzinfo=UTC),
    )
    gateway = OutboxMicromarketMoveGateway(
        command_store=store,
        publisher=publisher,
        warehouse_stock=InMemoryMicromarketWarehouseStockSnapshotStore(),
        poll_interval_seconds=10.0,
        poll_timeout_seconds=90.0,
        sync_execute=handler.process,
        clock=lambda: datetime(2026, 10, 30, tzinfo=UTC),
    )
    move_id = gateway.create_move(
        order_id="ord-1",
        machine_code="711",
        positions=(("2311", Decimal("1")),),
    )
    assert move_id == "ms-ord-1"
    assert len(publisher.events) == 1
    assert publisher.events[0].command_id is not None
