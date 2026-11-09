from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.micromarket_loading.move_gateway import MicromarketMoveGateway
from src.application.micromarket_loading.ms_catalog_code import resolve_ms_catalog_code
from src.application.product_identity.ports import DomainProductStore
from src.domain.micromarket_loading.order_events import DraftLine, OrderOpened

_logger = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class RestoreHistoricalMoveRejected:
    reason: str


@beartype
@dataclass(frozen=True, slots=True)
class RestoreHistoricalMoveResult:
    machine_code: str
    order_id: str
    historical_move_id: str
    move_id: str
    created_or_reused: str


@runtime_checkable
class HistoricalOrderOpenedLookup(Protocol):
    def find_opened(
        self,
        *,
        machine_code: str,
        order_id: str,
    ) -> OrderOpened | None: ...


@beartype
@dataclass(slots=True)
class RestoreHistoricalMicromarketLoadingMove:
    opened_lookup: HistoricalOrderOpenedLookup
    gateway: MicromarketMoveGateway
    products: DomainProductStore | None = None

    @beartype
    def execute(
        self,
        *,
        machine_code: str,
        order_id: str,
    ) -> RestoreHistoricalMoveResult | RestoreHistoricalMoveRejected:
        opened = self.opened_lookup.find_opened(
            machine_code=machine_code,
            order_id=order_id,
        )
        if opened is None:
            return RestoreHistoricalMoveRejected("order_opened_not_found")
        if opened.order_id != order_id:
            return RestoreHistoricalMoveRejected("order_id_mismatch")

        positions = _positions_from_lines(
            lines=opened.lines,
            products=self.products,
        )
        if not positions:
            return RestoreHistoricalMoveRejected("no_catalog_positions")

        move_id = self.gateway.create_move(
            order_id=order_id,
            machine_code=machine_code,
            positions=positions,
        )
        created_or_reused = "reused" if move_id == opened.move_id else "created_or_replaced"
        _logger.info(
            "micromarket_loading_historical_move_restored",
            extra={
                "machine_code": machine_code,
                "order_id": order_id,
                "historical_move_id": opened.move_id,
                "move_id": move_id,
                "created_or_reused": created_or_reused,
            },
        )
        return RestoreHistoricalMoveResult(
            machine_code=machine_code,
            order_id=order_id,
            historical_move_id=opened.move_id,
            move_id=move_id,
            created_or_reused=created_or_reused,
        )


@beartype
def _positions_from_lines(
    *,
    lines: Sequence[DraftLine],
    products: DomainProductStore | None,
) -> tuple[tuple[str, Decimal], ...]:
    positions: list[tuple[str, Decimal]] = []
    for line in lines:
        if line.launch_qty <= 0:
            continue
        catalog_code = resolve_ms_catalog_code(products, line.product_code)
        if catalog_code is None:
            continue
        positions.append((catalog_code, line.launch_qty))
    return tuple(positions)
