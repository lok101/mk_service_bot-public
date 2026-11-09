from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from beartype import beartype

from src.application.micromarket_loading.ports import (
    MicromarketDeviceStockStore,
    MicromarketPlanogramStore,
    ShopListLastSucceededSnapshotStore,
    ShopListPublishJournal,
)
from src.application.micromarket_loading.save_draft import MicromarketLoadingCycleStore
from src.application.product_identity.ports import DomainProductStore
from src.domain.micromarket_loading import MicromarketDeviceStock
from src.domain.micromarket_loading.order import OrderStatus
from src.domain.micromarket_loading.order_events import OPS_CONFIRMED_WITHOUT_RECOUNT

_logger = logging.getLogger(__name__)

OpsAcceptStatus = Literal["accepted", "idempotent", "rejected"]


@beartype
@dataclass(frozen=True, slots=True)
class OpsAcceptLoadingResult:
    status: OpsAcceptStatus
    reason: str | None = None


@beartype
@dataclass(slots=True)
class OpsAcceptMicromarketLoading:
    cycle_store: MicromarketLoadingCycleStore
    stock_store: MicromarketDeviceStockStore
    planogram_store: MicromarketPlanogramStore | None = None
    publisher: object | None = None
    products: DomainProductStore | None = None
    journal: ShopListPublishJournal | None = None
    baseline_store: ShopListLastSucceededSnapshotStore | None = None
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC)

    @beartype
    def execute(
        self,
        *,
        machine_code: str,
        actor_id: str | None = None,
    ) -> OpsAcceptLoadingResult:
        cycle = self.cycle_store.load(machine_code)
        if cycle is None:
            return OpsAcceptLoadingResult(status="rejected", reason="no_order")
        if cycle.status is OrderStatus.CLOSED and cycle.close_kind == OPS_CONFIRMED_WITHOUT_RECOUNT:
            _logger.info(
                "micromarket_ops_accept_loading",
                extra={
                    "machine_code": machine_code,
                    "order_id": cycle.order_id,
                    "actor_id": actor_id,
                    "status": "idempotent",
                },
            )
            return OpsAcceptLoadingResult(status="idempotent")
        if cycle.status is not OrderStatus.OPEN:
            return OpsAcceptLoadingResult(
                status="rejected",
                reason=f"order_status_{cycle.status.value if cycle.status else 'none'}",
            )
        if cycle.order_id is None:
            return OpsAcceptLoadingResult(status="rejected", reason="missing_order_id")

        at = self.now_factory()
        launch_lines = {
            line.product_code: line.launch_qty for line in cycle.lines if line.launch_qty != 0
        }
        stock = self.stock_store.load(machine_code) or MicromarketDeviceStock(
            machine_code=machine_code
        )
        if launch_lines:
            applied = stock.apply_loading(
                lines=launch_lines,
                loading_run_id=cycle.order_id,
                occurred_at=at,
            )
            if applied is not None:
                self.stock_store.save(stock)

        cycle.close_without_recount(at=at)
        self.cycle_store.save(cycle)
        _logger.info(
            "micromarket_ops_accept_loading",
            extra={
                "machine_code": machine_code,
                "order_id": cycle.order_id,
                "actor_id": actor_id,
                "status": "accepted",
                "lines": len(launch_lines),
            },
        )
        self._maybe_enqueue_shop_list_on_loading_shelf(machine_code=machine_code)
        return OpsAcceptLoadingResult(status="accepted")

    def _maybe_enqueue_shop_list_on_loading_shelf(self, *, machine_code: str) -> None:
        if self.publisher is None or self.planogram_store is None:
            return
        doc = self.planogram_store.get(machine_code)
        if doc is None:
            return
        from src.application.micromarket_loading.publish_job import (
            enqueue_micromarket_shop_list_publish,
        )
        from src.application.micromarket_loading.shop_list_intended import (
            build_shop_list_intended_lines,
        )
        from src.application.micromarket_loading.shop_list_needs_publish import (
            shop_list_needs_publish,
        )
        from src.application.micromarket_loading.shop_list_publish_journal import (
            ShopListPublishTrigger,
            diff_shop_list_intended,
        )

        stock = self.stock_store.load(machine_code)
        intended = build_shop_list_intended_lines(doc, self.products, stock=stock)
        baseline = None
        if self.baseline_store is not None:
            snap = self.baseline_store.get(machine_code)
            if snap is not None:
                baseline = snap.lines
        effects = diff_shop_list_intended(baseline, intended)
        if not shop_list_needs_publish(status=doc.shop_list_status, effects=effects):
            return
        enqueue_micromarket_shop_list_publish(
            store=self.planogram_store,
            publisher=self.publisher,  # type: ignore[arg-type]
            machine_code=machine_code,
            now=self.now_factory(),
            products=self.products,
            stock_store=self.stock_store,
            journal=self.journal,
            trigger=ShopListPublishTrigger.LOADING_SHELF,
            baseline_store=self.baseline_store,
        )
