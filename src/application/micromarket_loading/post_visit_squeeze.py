from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.micromarket_loading.alert_sweep import MicromarketLoadingAlerter
from src.application.micromarket_loading.assembly_orders import AssemblyOrderRejected
from src.application.micromarket_loading.launch_loading import LaunchRejected, LoadingDisabled
from src.application.micromarket_loading.planogram import (
    remove_pending_exit_lines_for_explicit_zeros,
)
from src.application.micromarket_loading.ports import (
    MicromarketDeviceStockStore,
    MicromarketPlanogramStore,
    MicromarketSalesAfterPort,
    PendingMicromarketInventStore,
    ShopListLastSucceededSnapshotStore,
    ShopListPublishJournal,
)
from src.application.micromarket_loading.publish_job import (
    AlreadyPublishing,
    Enqueued,
    MissingGroup,
    NothingToSend,
    PriceRequired,
    ShopListPublishEventPublisher,
    enqueue_micromarket_shop_list_publish,
)
from src.application.micromarket_loading.save_draft import MicromarketLoadingCycleStore
from src.application.micromarket_loading.shop_list_publish_journal import ShopListPublishTrigger
from src.application.product_identity.ports import DomainProductStore
from src.domain.micromarket_loading import MicromarketDeviceStock, MicromarketStockConcurrencyError
from src.domain.micromarket_loading.events import MicromarketStockEvent
from src.domain.micromarket_loading.order import MicromarketLoadingCycle, OrderStatus
from src.domain.micromarket_loading.pending_invent import PendingMicromarketInvent

_STOCK_SAVE_ATTEMPTS = 3
_SYSTEM_ACTOR = "system"
_logger = logging.getLogger(__name__)


@beartype
class PostVisitSqueezeStageFailed(RuntimeError):
    """Stoppable stage failure after alert; outbox must leave the entry pending for retry."""


@runtime_checkable
class LaunchFromAssemblyPort(Protocol):
    def execute(
        self,
        *,
        machine_code: str,
        actor: str = "curator",
    ) -> None | LoadingDisabled | LaunchRejected | AssemblyOrderRejected: ...


@beartype
def _nonzero_deltas(
    *,
    quantities: Mapping[str, Decimal],
    shelf_before: Mapping[str, Decimal],
    launch_by_code: Mapping[str, Decimal],
) -> tuple[tuple[str, Decimal], ...]:
    nonzero: list[tuple[str, Decimal]] = []
    for product_code, form_qty in quantities.items():
        expectation = shelf_before.get(product_code, Decimal("0")) + launch_by_code.get(
            product_code,
            Decimal("0"),
        )
        delta = form_qty - expectation
        if delta != 0:
            nonzero.append((product_code, delta))
    return tuple(nonzero)


@beartype
def _shelf_before_tuple(shelf_before: Mapping[str, Decimal]) -> tuple[tuple[str, Decimal], ...]:
    return tuple(sorted(shelf_before.items(), key=lambda item: item[0]))


@beartype
@dataclass(slots=True)
class _OverlayStockStore:
    """Read-only stock view for publish snapshot (pending invent overlay, not persisted)."""

    stock: MicromarketDeviceStock | None

    @beartype
    def load(self, machine_code: str) -> MicromarketDeviceStock | None:
        del machine_code
        return self.stock

    @beartype
    def save(self, stock: MicromarketDeviceStock) -> None:
        del stock
        raise RuntimeError("overlay stock store is read-only")

    @beartype
    def list_events(self, machine_code: str) -> Sequence[MicromarketStockEvent]:
        del machine_code
        return ()


@beartype
@dataclass(slots=True)
class PostVisitSqueeze:
    """Idempotent Load → publish ``post_visit_squeeze`` → post invent (effects drain)."""

    pending_store: PendingMicromarketInventStore
    launch_from_assembly: LaunchFromAssemblyPort
    stock_store: MicromarketDeviceStockStore
    sales_after: MicromarketSalesAfterPort
    alerter: MicromarketLoadingAlerter
    cycle_store: MicromarketLoadingCycleStore | None = None
    planogram_store: MicromarketPlanogramStore | None = None
    publisher: ShopListPublishEventPublisher | None = None
    products: DomainProductStore | None = None
    journal: ShopListPublishJournal | None = None
    baseline_store: ShopListLastSucceededSnapshotStore | None = None
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC)

    @beartype
    def run(self, *, machine_code: str, inventory_id: str) -> None:
        pending = self.pending_store.get_for_machine(machine_code)
        if pending is None or pending.inventory_id != inventory_id:
            _logger.info(
                "post_visit_squeeze_noop",
                extra={
                    "machine_code": machine_code,
                    "inventory_id": inventory_id,
                    "reason": "pending_missing_or_mismatch",
                },
            )
            return

        self._stage_load(machine_code=machine_code)
        self._stage_publish(machine_code=machine_code, pending=pending)
        self._stage_post(machine_code=machine_code, pending=pending)

    @beartype
    def _stage_load(self, *, machine_code: str) -> None:
        result = self.launch_from_assembly.execute(
            machine_code=machine_code,
            actor=_SYSTEM_ACTOR,
        )
        if result is None:
            _logger.info(
                "post_visit_squeeze_load_ok",
                extra={"machine_code": machine_code, "actor": _SYSTEM_ACTOR},
            )
            return
        if isinstance(result, AssemblyOrderRejected) and result.reason == "empty_session":
            _logger.info(
                "post_visit_squeeze_load_skip",
                extra={"machine_code": machine_code, "reason": "empty_session"},
            )
            return
        if isinstance(result, LoadingDisabled):
            # Spec: execute disabled + open session → alert AND continue publish+post.
            self._alert(
                machine_code=machine_code,
                stage="load",
                reason=_load_failure_reason(result),
            )
            return
        self._alert_and_stop(
            machine_code=machine_code,
            stage="load",
            reason=_load_failure_reason(result),
        )

    @beartype
    def _stage_publish(
        self,
        *,
        machine_code: str,
        pending: PendingMicromarketInvent,
    ) -> None:
        if self.publisher is None or self.planogram_store is None:
            self._alert(
                machine_code=machine_code,
                stage="publish",
                reason="publisher_or_planogram_missing",
            )
            return
        if self.planogram_store.get(machine_code) is None:
            self._alert(
                machine_code=machine_code,
                stage="publish",
                reason="planogram_missing",
            )
            return

        overlay = self._overlay_stock_for_publish(machine_code=machine_code, pending=pending)
        try:
            result = enqueue_micromarket_shop_list_publish(
                store=self.planogram_store,
                publisher=self.publisher,
                machine_code=machine_code,
                now=self.now_factory(),
                products=self.products,
                stock_store=_OverlayStockStore(stock=overlay),
                journal=self.journal,
                trigger=ShopListPublishTrigger.POST_VISIT_SQUEEZE,
                baseline_store=self.baseline_store,
            )
        except Exception as error:
            self._alert_and_stop(
                machine_code=machine_code,
                stage="publish",
                reason=f"enqueue_failed: {error}",
                cause=error,
            )

        if isinstance(result, (Enqueued, AlreadyPublishing, NothingToSend)):
            _logger.info(
                "post_visit_squeeze_publish_ok",
                extra={
                    "machine_code": machine_code,
                    "result": type(result).__name__,
                    "trigger": ShopListPublishTrigger.POST_VISIT_SQUEEZE.value,
                },
            )
            return
        if isinstance(result, (MissingGroup, PriceRequired)):
            self._alert_and_stop(
                machine_code=machine_code,
                stage="publish",
                reason=f"{type(result).__name__}:{result.product_code}",
            )
        self._alert_and_stop(
            machine_code=machine_code,
            stage="publish",
            reason=f"unexpected:{type(result).__name__}",
        )

    @beartype
    def _overlay_stock_for_publish(
        self,
        *,
        machine_code: str,
        pending: PendingMicromarketInvent,
    ) -> MicromarketDeviceStock:
        stock = self.stock_store.load(machine_code)
        if stock is None:
            stock = MicromarketDeviceStock(machine_code=machine_code)
        stock.apply_inventory(
            as_of=pending.submitted_at,
            quantities=pending.quantity_map(),
            inventory_id=pending.inventory_id,
            partial=False,
        )
        return stock

    @beartype
    def _stage_post(
        self,
        *,
        machine_code: str,
        pending: PendingMicromarketInvent,
    ) -> None:
        quantities = pending.quantity_map()
        try:
            self._apply_pending_inventory(
                machine_code=machine_code,
                pending=pending,
                quantities=quantities,
            )
        except Exception as error:
            self._alert_and_stop(
                machine_code=machine_code,
                stage="post",
                reason=str(error),
                cause=error,
            )

        if self.planogram_store is not None:
            remove_pending_exit_lines_for_explicit_zeros(
                planogram_store=self.planogram_store,
                machine_code=machine_code,
                quantities=quantities,
                products=self.products,
                now=self.now_factory(),
            )

        self.pending_store.clear(machine_code)
        _logger.info(
            "post_visit_squeeze_post_ok",
            extra={
                "machine_code": machine_code,
                "inventory_id": pending.inventory_id,
            },
        )

    @beartype
    def _apply_pending_inventory(
        self,
        *,
        machine_code: str,
        pending: PendingMicromarketInvent,
        quantities: Mapping[str, Decimal],
    ) -> None:
        for _attempt in range(_STOCK_SAVE_ATTEMPTS):
            stock = self.stock_store.load(machine_code)
            if stock is None:
                stock = MicromarketDeviceStock(machine_code=machine_code)

            cycle: MicromarketLoadingCycle | None = None
            deltas: tuple[tuple[str, Decimal], ...] = ()
            shelf_before_map: dict[str, Decimal] = {}
            if self.cycle_store is not None:
                cycle = self.cycle_store.load(machine_code)
                if cycle is not None and cycle.status is OrderStatus.OPEN:
                    shelf_before_map = {
                        code: stock.qty(code)
                        for code in {
                            *(line.product_code for line in cycle.lines),
                            *quantities,
                        }
                    }
                    launch_by_code = {line.product_code: line.launch_qty for line in cycle.lines}
                    deltas = _nonzero_deltas(
                        quantities=quantities,
                        shelf_before=shelf_before_map,
                        launch_by_code=launch_by_code,
                    )

            stock.apply_inventory(
                as_of=pending.submitted_at,
                quantities=quantities,
                inventory_id=pending.inventory_id,
                partial=False,
            )

            affected_codes = set(quantities)
            for sale in self.sales_after.query(machine_code, pending.submitted_at):
                if sale.product_code not in affected_codes:
                    continue
                if sale.occurred_at <= pending.submitted_at:
                    continue
                stock.apply_sale_deduct(
                    sale_source_id=sale.sale_source_id,
                    product_code=sale.product_code,
                    qty=sale.qty,
                    occurred_at=sale.occurred_at,
                )

            try:
                self.stock_store.save(stock)
            except MicromarketStockConcurrencyError:
                continue

            now = self.now_factory()
            if (
                self.cycle_store is not None
                and cycle is not None
                and cycle.status is OrderStatus.OPEN
            ):
                cycle.mark_recounted(
                    at=pending.submitted_at,
                    deltas=deltas,
                    shelf_before=_shelf_before_tuple(shelf_before_map),
                )
                cycle.close(at=now)
                self.cycle_store.save(cycle)
                _logger.info(
                    "micromarket_loading_closed_after_post_visit_squeeze",
                    extra={
                        "machine_code": machine_code,
                        "order_id": cycle.order_id,
                        "inventory_id": pending.inventory_id,
                    },
                )
            elif (
                self.cycle_store is not None
                and cycle is not None
                and cycle.status is OrderStatus.RECOUNTED
            ):
                cycle.close(at=now)
                self.cycle_store.save(cycle)
                _logger.info(
                    "micromarket_loading_closed_after_post_visit_squeeze",
                    extra={
                        "machine_code": machine_code,
                        "order_id": cycle.order_id,
                        "inventory_id": pending.inventory_id,
                    },
                )
            return

        raise MicromarketStockConcurrencyError(machine_code=machine_code)

    @beartype
    def _alert(self, *, machine_code: str, stage: str, reason: str) -> None:
        text = f"post_visit_squeeze failed: machine={machine_code} stage={stage} reason={reason}"
        self.alerter.send(text)
        _logger.warning(
            "post_visit_squeeze_failed",
            extra={"machine_code": machine_code, "stage": stage, "reason": reason},
        )

    @beartype
    def _alert_and_stop(
        self,
        *,
        machine_code: str,
        stage: str,
        reason: str,
        cause: BaseException | None = None,
    ) -> None:
        self._alert(machine_code=machine_code, stage=stage, reason=reason)
        error = PostVisitSqueezeStageFailed(
            f"post_visit_squeeze stopped: machine={machine_code} stage={stage} reason={reason}"
        )
        if cause is not None:
            raise error from cause
        raise error


@beartype
def _load_failure_reason(
    result: LoadingDisabled | LaunchRejected | AssemblyOrderRejected,
) -> str:
    if isinstance(result, LoadingDisabled):
        return f"LoadingDisabled:{result.message}"
    if isinstance(result, LaunchRejected):
        return f"LaunchRejected:{result.reason}"
    return f"AssemblyOrderRejected:{result.reason}"
