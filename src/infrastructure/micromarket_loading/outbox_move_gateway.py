from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from beartype import beartype

from src.application.machine_operations.ports import DomainEventPublisher
from src.application.micromarket_loading.move_command import (
    MicromarketLoadingMoveCommand,
    MicromarketLoadingMoveCommandStore,
)
from src.application.micromarket_loading.ports import MicromarketWarehouseStockSnapshotPort
from src.domain.ids import EventId
from src.domain.micromarket_loading.move_command_event import MicromarketLoadingMoveCommandRequested

SyncMoveCommandExecute = Callable[[MicromarketLoadingMoveCommandRequested], None]


class MicromarketLoadingMoveCommandTimeout(Exception):
    """Move command was not completed before the poll deadline."""

    def __init__(self, command_id: str) -> None:
        self.command_id = command_id
        super().__init__(
            "Перемещение в МойСклад не выполнено в срок "
            f"(command_id={command_id}). Проверьте effects-worker и логи move.",
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)


@beartype
@dataclass(frozen=True, slots=True)
class OutboxMicromarketMoveGateway:
    command_store: MicromarketLoadingMoveCommandStore
    publisher: DomainEventPublisher
    warehouse_stock: MicromarketWarehouseStockSnapshotPort
    poll_interval_seconds: float
    poll_timeout_seconds: float
    sync_execute: SyncMoveCommandExecute | None = None
    clock: Callable[[], datetime] = _utc_now

    @beartype
    def create_move(
        self,
        *,
        order_id: str,
        machine_code: str,
        positions: Sequence[tuple[str, Decimal]],
    ) -> str:
        move_id = self._run_command(
            MicromarketLoadingMoveCommand(
                command_id=str(uuid.uuid4()),
                kind="create",
                status="pending",
                order_id=order_id,
                machine_code=machine_code,
                positions=tuple(positions),
            ),
        )
        if move_id is None:
            raise RuntimeError("create_move succeeded without move_id")
        return move_id

    @beartype
    def delete_move(self, *, move_id: str) -> None:
        self._run_command(
            MicromarketLoadingMoveCommand(
                command_id=str(uuid.uuid4()),
                kind="delete",
                status="pending",
                move_id=move_id,
            ),
        )

    @beartype
    def move_moment(self, *, move_id: str) -> datetime | None:
        del move_id
        return None

    @beartype
    def existing_move_for_order_is_stale(
        self,
        *,
        order_id: str,
        now: datetime,
    ) -> bool:
        # Outbox path: skip extra MS round-trip; create_move is idempotent by externalCode.
        del order_id, now
        return False

    @beartype
    def warehouse_qty(self, product_code: str) -> Decimal:
        return self.warehouse_qty_by_codes([product_code]).get(product_code, Decimal("0"))

    @beartype
    def warehouse_qty_by_codes(
        self,
        product_codes: Sequence[str],
    ) -> Mapping[str, Decimal]:
        snapshot = self.warehouse_stock.get()
        if snapshot is None:
            return {code: Decimal("0") for code in product_codes}
        return {
            code: snapshot.qty_by_catalog_code.get(code, Decimal("0")) for code in product_codes
        }

    @beartype
    def _run_command(self, command: MicromarketLoadingMoveCommand) -> str | None:
        self.command_store.create_pending(command)
        event = MicromarketLoadingMoveCommandRequested(
            event_id=EventId(str(uuid.uuid4())),
            command_id=command.command_id,
            occurred_at=self.clock(),
        )
        self.publisher.publish(event)
        if self.sync_execute is not None:
            self.sync_execute(event)
        return self._wait_for_terminal(command_id=command.command_id)

    @beartype
    def _wait_for_terminal(self, *, command_id: str) -> str | None:
        deadline = time.monotonic() + self.poll_timeout_seconds
        while True:
            current = self.command_store.get(command_id)
            if current is None:
                raise RuntimeError(f"move command missing: {command_id}")
            if current.status == "succeeded":
                return current.move_id
            if current.status == "failed":
                raise RuntimeError(current.error or "move command failed")
            if time.monotonic() >= deadline:
                raise MicromarketLoadingMoveCommandTimeout(command_id)
            time.sleep(self.poll_interval_seconds)
