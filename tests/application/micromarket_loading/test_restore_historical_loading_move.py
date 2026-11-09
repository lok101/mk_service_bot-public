from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.application.micromarket_loading.restore_historical_loading_move import (
    RestoreHistoricalMicromarketLoadingMove,
    RestoreHistoricalMoveRejected,
    RestoreHistoricalMoveResult,
)
from src.domain.micromarket_loading.order_events import DraftLine, OrderOpened

_TZ = ZoneInfo("Europe/Moscow")
_AT = datetime(2026, 10, 23, 10, 0, tzinfo=_TZ)


class _Lookup:
    def __init__(self, opened: OrderOpened | None) -> None:
        self.opened = opened

    def find_opened(self, *, machine_code: str, order_id: str) -> OrderOpened | None:
        del machine_code, order_id
        return self.opened


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


def _opened(*, move_id: str = "move-oct23") -> OrderOpened:
    return OrderOpened(
        order_id="order-oct23",
        move_id=move_id,
        lines=(
            DraftLine(
                product_code="2311",
                target_qty=4,
                stock_qty=Decimal("1"),
                need_qty=Decimal("3"),
                launch_qty=Decimal("2"),
            ),
        ),
        opened_at=_AT,
        opened_operational_day=date(2026, 10, 23),
    )


def test_restore_historical_creates_when_ids_differ() -> None:
    gateway = _FakeGateway(move_id="move-new")
    result = RestoreHistoricalMicromarketLoadingMove(
        opened_lookup=_Lookup(_opened()),
        gateway=gateway,
    ).execute(machine_code="704", order_id="order-oct23")
    assert isinstance(result, RestoreHistoricalMoveResult)
    assert result.move_id == "move-new"
    assert result.created_or_reused == "created_or_replaced"
    assert gateway.create_calls == ["order-oct23"]


def test_restore_historical_reused_same_id() -> None:
    gateway = _FakeGateway(move_id="move-oct23")
    result = RestoreHistoricalMicromarketLoadingMove(
        opened_lookup=_Lookup(_opened()),
        gateway=gateway,
    ).execute(machine_code="704", order_id="order-oct23")
    assert isinstance(result, RestoreHistoricalMoveResult)
    assert result.created_or_reused == "reused"


def test_restore_historical_missing_event() -> None:
    result = RestoreHistoricalMicromarketLoadingMove(
        opened_lookup=_Lookup(None),
        gateway=_FakeGateway(move_id="x"),
    ).execute(machine_code="704", order_id="missing")
    assert isinstance(result, RestoreHistoricalMoveRejected)
    assert result.reason == "order_opened_not_found"
