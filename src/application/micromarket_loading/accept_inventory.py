from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.micromarket_loading.planogram import (
    _stock_key_for_pending_exit,
    remove_pending_exit_lines_for_explicit_zeros,
)
from src.application.micromarket_loading.ports import (
    CompleteOpenVisitTaskPort,
    EnqueuePostVisitSqueezePort,
    EnsureOpenVisitTaskPort,
    MicromarketDeviceStockStore,
    MicromarketPlanogramStore,
    MicromarketSalesAfterPort,
    PendingMicromarketInventStore,
    ShopListLastSucceededSnapshotStore,
    ShopListPublishJournal,
    VisitFinalizedForDayPort,
)
from src.application.micromarket_loading.save_draft import MicromarketLoadingCycleStore
from src.application.product_identity.ports import DomainProductStore
from src.domain.calendar import operational_day
from src.domain.micromarket_loading import MicromarketDeviceStock, MicromarketStockConcurrencyError
from src.domain.micromarket_loading.order import MicromarketLoadingCycle, OrderStatus
from src.domain.micromarket_loading.pending_invent import PendingMicromarketInvent

MicromarketInventoryMode = Literal["now", "as_of"]

_STOCK_SAVE_ATTEMPTS = 3
_logger = logging.getLogger(__name__)


@beartype
class VisitFinalizedRecountRejected(ValueError):
    """Raised when micromarket now is submitted after visit final for the ops day."""


@beartype
@dataclass(slots=True)
class AcceptMicromarketInventory:
    stock_store: MicromarketDeviceStockStore
    sales_after: MicromarketSalesAfterPort
    cycle_store: MicromarketLoadingCycleStore | None = None
    planogram_store: MicromarketPlanogramStore | None = None
    publisher: object | None = None
    products: DomainProductStore | None = None
    journal: ShopListPublishJournal | None = None
    baseline_store: ShopListLastSucceededSnapshotStore | None = None
    visit_finalized: VisitFinalizedForDayPort | None = None
    ensure_open_visit: EnsureOpenVisitTaskPort | None = None
    complete_open_visit: CompleteOpenVisitTaskPort | None = None
    enqueue_squeeze: EnqueuePostVisitSqueezePort | None = None
    pending_store: PendingMicromarketInventStore | None = None
    timezone: ZoneInfo | None = None
    day_end_hour: int = 6
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC)

    @beartype
    def execute(
        self,
        *,
        machine_code: str,
        mode: MicromarketInventoryMode,
        submitted_at: datetime,
        quantities: Mapping[str, Decimal],
        inventory_id: str,
        as_of_from_form: datetime | None,
        performed_technician_id: str = "",
        performed_technician_name: str = "",
        assigned_technician_id: str = "",
        assigned_technician_name: str = "",
        machine_name: str = "",
        partial: bool = True,
    ) -> None:
        if mode == "now":
            self._execute_now(
                machine_code=machine_code,
                submitted_at=submitted_at,
                quantities=quantities,
                inventory_id=inventory_id,
                performed_technician_id=performed_technician_id,
                performed_technician_name=performed_technician_name,
                assigned_technician_id=assigned_technician_id,
                assigned_technician_name=assigned_technician_name,
                machine_name=machine_name,
            )
            return

        if as_of_from_form is None:
            raise ValueError("as_of_from_form is required for micromarket inventory mode as_of")
        self._execute_as_of(
            machine_code=machine_code,
            anchor=as_of_from_form,
            quantities=quantities,
            inventory_id=inventory_id,
            partial=partial,
        )

    @beartype
    def _execute_now(
        self,
        *,
        machine_code: str,
        submitted_at: datetime,
        quantities: Mapping[str, Decimal],
        inventory_id: str,
        performed_technician_id: str,
        performed_technician_name: str,
        assigned_technician_id: str,
        assigned_technician_name: str,
        machine_name: str,
    ) -> None:
        if self.visit_finalized is not None and self.visit_finalized.is_finalized(
            machine_code,
            submitted_at,
        ):
            raise VisitFinalizedRecountRejected(
                f"visit finalized for machine {machine_code}; recount rejected",
            )
        if self.pending_store is None:
            raise ValueError("pending invent store required for micromarket inventory mode now")
        if self.timezone is None:
            raise ValueError("timezone required for micromarket inventory mode now")

        ops_day = operational_day(submitted_at, self.timezone, self.day_end_hour)
        existing = self.pending_store.get_for_machine(machine_code)
        if (
            existing is not None
            and existing.operational_day == ops_day
            and existing.inventory_id != inventory_id
        ):
            raise VisitFinalizedRecountRejected(
                f"pending invent already accepted for machine {machine_code} "
                f"on operational day {ops_day.isoformat()}",
            )
        pending = PendingMicromarketInvent(
            machine_code=machine_code,
            inventory_id=inventory_id,
            quantities=tuple(sorted(quantities.items(), key=lambda item: item[0])),
            submitted_at=submitted_at,
            operational_day=ops_day,
            performed_technician_id=performed_technician_id,
            performed_technician_name=performed_technician_name,
            assigned_technician_id=assigned_technician_id,
            assigned_technician_name=assigned_technician_name,
            machine_name=machine_name,
        )
        self.pending_store.save(pending)

        cycle = self.cycle_store.load(machine_code) if self.cycle_store is not None else None
        self._lazy_ensure_visit(
            machine_code=machine_code,
            submitted_at=submitted_at,
            cycle=cycle,
        )
        # ADR-0096: Accept does not complete VisitTask; freeze is via pending /
        # VisitFinalizedForDay (pending same ops day). Enqueue squeeze only.
        if self.enqueue_squeeze is not None:
            self.enqueue_squeeze.enqueue(
                machine_code=machine_code,
                inventory_id=inventory_id,
            )
        _logger.info(
            "micromarket_invent_accepted_pending",
            extra={
                "machine_code": machine_code,
                "machine_name": machine_name,
                "inventory_id": inventory_id,
                "operational_day": ops_day.isoformat(),
                "performed_technician_id": performed_technician_id,
                "assigned_technician_id": assigned_technician_id,
            },
        )

    @beartype
    def _execute_as_of(
        self,
        *,
        machine_code: str,
        anchor: datetime,
        quantities: Mapping[str, Decimal],
        inventory_id: str,
        partial: bool,
    ) -> None:
        for _attempt in range(_STOCK_SAVE_ATTEMPTS):
            stock = self.stock_store.load(machine_code)
            if stock is None:
                stock = MicromarketDeviceStock(machine_code=machine_code)

            pre_accept_factual_zero = {
                code for code in quantities if stock.last_factual_qty(code) == Decimal("0")
            }

            stock.apply_inventory(
                as_of=anchor,
                quantities=quantities,
                inventory_id=inventory_id,
                partial=partial,
            )

            affected_codes = set(quantities)
            for sale in self.sales_after.query(machine_code, anchor):
                if sale.product_code not in affected_codes:
                    continue
                if sale.occurred_at <= anchor:
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

            pending_exit_removed = self._maybe_remove_pending_exit_lines(
                machine_code=machine_code,
                quantities=quantities,
            )
            self._maybe_enqueue_shop_list_on_availability_boundary(
                machine_code=machine_code,
                quantities=quantities,
                pre_accept_factual_zero=pre_accept_factual_zero,
                pending_exit_removed=pending_exit_removed,
            )
            return

        raise MicromarketStockConcurrencyError(machine_code=machine_code)

    @beartype
    def _lazy_ensure_visit(
        self,
        *,
        machine_code: str,
        submitted_at: datetime,
        cycle: MicromarketLoadingCycle | None,
    ) -> None:
        if self.ensure_open_visit is None:
            return
        # Closed / rolled_back cycles keep order_id (and often visit_id). Do not
        # attach that terminal order to a new day's VisitTask or attempt relink.
        if (
            cycle is not None
            and cycle.order_id is not None
            and cycle.status in (OrderStatus.OPEN, OrderStatus.RECOUNTED)
        ):
            loading_order_id = cycle.order_id
            active_loading = True
        else:
            loading_order_id = None
            active_loading = False
        visit_id = self.ensure_open_visit.ensure_open(
            machine_code=machine_code,
            at=submitted_at,
            source="field_activity",
            loading_order_id=loading_order_id,
        )
        if self.cycle_store is None or cycle is None or not active_loading:
            return
        if cycle.visit_id == visit_id:
            return
        cycle.link_visit(visit_id)
        self.cycle_store.save(cycle)

    @beartype
    def _maybe_remove_pending_exit_lines(
        self,
        *,
        machine_code: str,
        quantities: Mapping[str, Decimal],
    ) -> bool:
        if self.planogram_store is None:
            return False
        return remove_pending_exit_lines_for_explicit_zeros(
            planogram_store=self.planogram_store,
            machine_code=machine_code,
            quantities=quantities,
            products=self.products,
            now=self.now_factory(),
        )

    def _maybe_enqueue_shop_list_on_availability_boundary(
        self,
        *,
        machine_code: str,
        quantities: Mapping[str, Decimal],
        pre_accept_factual_zero: set[str],
        pending_exit_removed: bool,
    ) -> bool:
        if self.publisher is None or self.planogram_store is None:
            return False
        planogram_codes = self._planogram_stock_keys(machine_code)
        has_zero = False
        has_restore = False
        for code, qty in quantities.items():
            if qty == 0:
                has_zero = True
            elif qty > 0 and code in pre_accept_factual_zero and code in planogram_codes:
                has_restore = True
        if not (pending_exit_removed or has_zero or has_restore):
            return False
        from src.application.micromarket_loading.publish_job import (
            enqueue_micromarket_shop_list_publish,
        )
        from src.application.micromarket_loading.shop_list_publish_journal import (
            ShopListPublishTrigger,
        )

        # Priority: PENDING_EXIT > INVENTORY_RESTORE > INVENTORY_ZERO (one enqueue).
        if pending_exit_removed:
            trigger = ShopListPublishTrigger.PENDING_EXIT
        elif has_restore:
            trigger = ShopListPublishTrigger.INVENTORY_RESTORE
        else:
            trigger = ShopListPublishTrigger.INVENTORY_ZERO

        enqueue_micromarket_shop_list_publish(
            store=self.planogram_store,
            publisher=self.publisher,  # type: ignore[arg-type]
            machine_code=machine_code,
            now=self.now_factory(),
            products=self.products,
            stock_store=self.stock_store,
            journal=self.journal,
            trigger=trigger,
            baseline_store=self.baseline_store,
        )
        return True

    def _planogram_stock_keys(self, machine_code: str) -> set[str]:
        if self.planogram_store is None:
            return set()
        doc = self.planogram_store.get(machine_code)
        if doc is None:
            return set()
        return {
            key for line in doc.lines if (key := _stock_key_for_pending_exit(line, self.products))
        }
