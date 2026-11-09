from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.application.micromarket_loading.repair_loading_move import (
    RepairMicromarketLoadingMove,
    RepairMoveRejected,
    RepairMoveResult,
)
from src.domain.micromarket_loading.order import DraftLine, MicromarketLoadingCycle, OrderStatus

_TZ = ZoneInfo("Europe/Moscow")
_AT = datetime(2026, 10, 28, 10, 0, tzinfo=_TZ)


class _MemoryCycleStore:
    def __init__(self) -> None:
        self.cycles: dict[str, MicromarketLoadingCycle] = {}

    def load(self, machine_code: str) -> MicromarketLoadingCycle | None:
        return self.cycles.get(machine_code)

    def save(self, cycle: MicromarketLoadingCycle) -> None:
        self.cycles[cycle.machine_code] = cycle


class _FakeGateway:
    def __init__(self, *, move_id: str) -> None:
        self.move_id = move_id
        self.create_calls: list[str] = []

    def warehouse_qty(self, product_code: str) -> Decimal:
        return Decimal("10")

    def warehouse_qty_by_codes(self, product_codes: Sequence[str]) -> dict[str, Decimal]:
        return {code: Decimal("10") for code in product_codes}

    def create_move(
        self,
        *,
        order_id: str,
        machine_code: str,
        positions: Sequence[tuple[str, Decimal]],
    ) -> str:
        del machine_code, positions
        self.create_calls.append(order_id)
        return self.move_id

    def delete_move(self, *, move_id: str) -> None:
        del move_id

    def move_moment(self, *, move_id: str) -> datetime | None:
        del move_id
        return None

    def existing_move_for_order_is_stale(
        self,
        *,
        order_id: str,
        now: datetime,
    ) -> bool:
        del order_id, now
        return False


def _open(store: _MemoryCycleStore, *, move_id: str = "move-old") -> None:
    cycle = MicromarketLoadingCycle(machine_code="704")
    cycle.save_draft(
        (
            DraftLine(
                product_code="2311",
                target_qty=4,
                stock_qty=Decimal("1"),
                need_qty=Decimal("3"),
                launch_qty=Decimal("2"),
            ),
        ),
    )
    cycle.open_order(
        order_id="order-1",
        move_id=move_id,
        lines=cycle.lines,
        opened_at=_AT,
        timezone=_TZ,
        day_end_hour=6,
    )
    store.save(cycle)


def test_repair_reuses_same_move_id_without_domain_event() -> None:
    store = _MemoryCycleStore()
    _open(store, move_id="move-old")
    gateway = _FakeGateway(move_id="move-old")
    result = RepairMicromarketLoadingMove(cycle_store=store, gateway=gateway).execute(
        machine_code="704",
    )
    assert isinstance(result, RepairMoveResult)
    assert result.move_id == "move-old"
    assert result.domain_updated is False
    assert gateway.create_calls == ["order-1"]


def test_repair_updates_domain_when_ms_returns_new_move_id() -> None:
    store = _MemoryCycleStore()
    _open(store, move_id="move-old")
    gateway = _FakeGateway(move_id="move-new")
    result = RepairMicromarketLoadingMove(cycle_store=store, gateway=gateway).execute(
        machine_code="704",
    )
    assert isinstance(result, RepairMoveResult)
    assert result.move_id == "move-new"
    assert result.domain_updated is True
    loaded = store.load("704")
    assert loaded is not None
    assert loaded.status is OrderStatus.OPEN
    assert loaded.move_id == "move-new"


def test_repair_rejected_when_not_open() -> None:
    store = _MemoryCycleStore()
    result = RepairMicromarketLoadingMove(
        cycle_store=store,
        gateway=_FakeGateway(move_id="x"),
    ).execute(machine_code="704")
    assert isinstance(result, RepairMoveRejected)
    assert result.reason == "order_not_open"
