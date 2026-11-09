from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.micromarket_loading.move_command import MicromarketLoadingMoveCommand
from src.application.outbox.micromarket_loading_move import MicromarketLoadingMoveOutboxHandler
from src.domain.ids import EventId
from src.domain.micromarket_loading.move_command_event import MicromarketLoadingMoveCommandRequested
from src.infrastructure.micromarket_loading.move_command_store import (
    InMemoryMicromarketLoadingMoveCommandStore,
)


class _FakeMoveClient:
    def __init__(self) -> None:
        self.created: list[tuple[str, str, tuple[tuple[str, Decimal], ...]]] = []

    def create_move(
        self,
        *,
        order_id: str,
        machine_code: str,
        positions: tuple[tuple[str, Decimal], ...],
    ) -> str:
        self.created.append((order_id, machine_code, positions))
        return f"move-{order_id}"

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


def test_move_outbox_handler_creates_move_and_marks_command_succeeded() -> None:
    store = InMemoryMicromarketLoadingMoveCommandStore()
    client = _FakeMoveClient()
    handler = MicromarketLoadingMoveOutboxHandler(
        command_store=store,
        move_client=client,
        clock=lambda: datetime(2026, 10, 30, tzinfo=UTC),
    )
    store.create_pending(
        MicromarketLoadingMoveCommand(
            command_id="cmd-1",
            kind="create",
            status="pending",
            order_id="ord-1",
            machine_code="711",
            positions=(("2311", Decimal("2")),),
        ),
    )
    handler.process(
        MicromarketLoadingMoveCommandRequested(
            event_id=EventId("evt-1"),
            command_id="cmd-1",
            occurred_at=datetime(2026, 10, 30, tzinfo=UTC),
        ),
    )
    updated = store.get("cmd-1")
    assert updated is not None
    assert updated.status == "succeeded"
    assert updated.move_id == "move-ord-1"
    assert client.created == [("ord-1", "711", (("2311", Decimal("2")),))]
