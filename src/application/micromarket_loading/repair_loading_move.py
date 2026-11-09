from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.application.micromarket_loading.move_gateway import MicromarketMoveGateway
from src.application.micromarket_loading.ms_catalog_code import resolve_ms_catalog_code
from src.application.micromarket_loading.save_draft import MicromarketLoadingCycleStore
from src.application.product_identity.ports import DomainProductStore
from src.domain.micromarket_loading.order import OrderStatus

_logger = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class RepairMoveRejected:
    reason: str


@beartype
@dataclass(frozen=True, slots=True)
class RepairMoveResult:
    machine_code: str
    order_id: str
    previous_move_id: str | None
    move_id: str
    created_or_reused: str
    domain_updated: bool


@beartype
@dataclass(slots=True)
class RepairMicromarketLoadingMove:
    cycle_store: MicromarketLoadingCycleStore
    gateway: MicromarketMoveGateway
    products: DomainProductStore | None = None

    @beartype
    def execute(self, *, machine_code: str) -> RepairMoveResult | RepairMoveRejected:
        cycle = self.cycle_store.load(machine_code)
        if cycle is None or cycle.status is not OrderStatus.OPEN:
            return RepairMoveRejected("order_not_open")
        if cycle.order_id is None:
            return RepairMoveRejected("order_id_missing")
        if cycle.move_id is None:
            return RepairMoveRejected("move_id_missing")

        positions: list[tuple[str, Decimal]] = []
        for line in cycle.lines:
            if line.launch_qty <= 0:
                continue
            catalog_code = resolve_ms_catalog_code(self.products, line.product_code)
            if catalog_code is None:
                continue
            positions.append((catalog_code, line.launch_qty))
        if not positions:
            return RepairMoveRejected("no_catalog_positions")

        previous_move_id = cycle.move_id
        move_id = self.gateway.create_move(
            order_id=cycle.order_id,
            machine_code=machine_code,
            positions=tuple(positions),
        )
        created_or_reused = "reused" if move_id == previous_move_id else "created_or_replaced"
        domain_updated = False
        if move_id != previous_move_id:
            cycle.repair_move_id(move_id=move_id)
            self.cycle_store.save(cycle)
            domain_updated = True

        _logger.info(
            "micromarket_loading_move_repaired",
            extra={
                "machine_code": machine_code,
                "order_id": cycle.order_id,
                "previous_move_id": previous_move_id,
                "move_id": move_id,
                "created_or_reused": created_or_reused,
                "domain_updated": domain_updated,
            },
        )
        return RepairMoveResult(
            machine_code=machine_code,
            order_id=cycle.order_id,
            previous_move_id=previous_move_id,
            move_id=move_id,
            created_or_reused=created_or_reused,
            domain_updated=domain_updated,
        )
