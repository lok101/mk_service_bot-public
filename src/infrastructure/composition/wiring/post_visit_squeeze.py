from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from beartype import beartype
from pymongo import MongoClient

from src.application.inventory_reconciliation.ports import MachineSalesStore
from src.application.micromarket_loading.assembly_orders import LaunchFromAssemblyOrders
from src.application.micromarket_loading.launch_loading import LaunchMicromarketLoading
from src.application.micromarket_loading.move_gateway import MicromarketMoveGateway
from src.application.micromarket_loading.ports import (
    MicromarketDeviceStockStore,
    MicromarketPlanogramStore,
    PendingMicromarketInventStore,
    ShopListLastSucceededSnapshotStore,
    ShopListPublishJournal,
)
from src.application.micromarket_loading.post_visit_squeeze import PostVisitSqueeze
from src.application.micromarket_loading.publish_job import ShopListPublishEventPublisher
from src.application.micromarket_loading.save_draft import MicromarketLoadingCycleStore
from src.application.product_identity.ports import DomainProductStore
from src.config.settings import Settings
from src.infrastructure.composition.adapters.micromarket_loading_alerter import (
    build_micromarket_loading_alerter,
)
from src.infrastructure.composition.factories.micromarket_loading import (
    build_admin_micromarket_loading_move_gateway,
    build_micromarket_assembly_order_store,
    build_micromarket_loading_move_command_store,
    build_micromarket_warehouse_stock_snapshot_store,
    build_pending_micromarket_invent_store,
)
from src.infrastructure.micromarket_loading.micromarket_sales_after import (
    MachineSalesMicromarketSalesAfter,
)


class _DisabledMicromarketMoveGateway:
    def warehouse_qty(self, product_code: str) -> Decimal:
        del product_code
        return Decimal("0")

    def warehouse_qty_by_codes(self, product_codes: Sequence[str]) -> dict[str, Decimal]:
        return {code: Decimal("0") for code in product_codes}

    def create_move(
        self,
        *,
        order_id: str,
        machine_code: str,
        positions: Sequence[tuple[str, Decimal]],
    ) -> str:
        del order_id, machine_code, positions
        raise RuntimeError("micromarket loading move gateway is not configured")

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


@beartype
def build_post_visit_squeeze(
    settings: Settings,
    *,
    mongo_client: MongoClient[dict[str, Any]] | None,
    cycle_store: MicromarketLoadingCycleStore | None,
    stock_store: MicromarketDeviceStockStore,
    planogram_store: MicromarketPlanogramStore,
    sales_store: MachineSalesStore,
    publisher: ShopListPublishEventPublisher | None,
    products: DomainProductStore | None,
    journal: ShopListPublishJournal | None,
    baseline_store: ShopListLastSucceededSnapshotStore | None,
    pending_store: PendingMicromarketInventStore | None = None,
    timezone: ZoneInfo | None = None,
    day_end_hour: int | None = None,
) -> PostVisitSqueeze | None:
    """Compose PostVisitSqueeze for effects-worker outbox drain. None if cycle store absent."""
    if cycle_store is None:
        return None
    resolved_tz = timezone if timezone is not None else settings.service_calendar.zone_info()
    resolved_end = (
        day_end_hour if day_end_hour is not None else settings.service_calendar.service_day_end_hour
    )
    resolved_pending = pending_store or build_pending_micromarket_invent_store(
        settings,
        client=mongo_client,
    )
    assembly_store = build_micromarket_assembly_order_store(settings, client=mongo_client)
    warehouse_stock = build_micromarket_warehouse_stock_snapshot_store(
        settings,
        client=mongo_client,
    )
    move_gateway: MicromarketMoveGateway
    if publisher is not None:
        built = build_admin_micromarket_loading_move_gateway(
            settings,
            publisher=publisher,  # type: ignore[arg-type]
            warehouse_stock=warehouse_stock,
            move_command_store=build_micromarket_loading_move_command_store(
                settings,
                client=mongo_client,
            ),
        )
        move_gateway = built if built is not None else _DisabledMicromarketMoveGateway()
    else:
        move_gateway = _DisabledMicromarketMoveGateway()

    launch = LaunchMicromarketLoading(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=move_gateway,
        execute_enabled=settings.micromarket_loading.execute_enabled,
        warehouse_gate_enabled=settings.micromarket_loading.warehouse_gate_enabled,
        timezone=resolved_tz,
        day_end_hour=resolved_end,
        clock=lambda: datetime.now(UTC),
        products=products,
        ensure_open_visit=None,
        warehouse_stock=warehouse_stock,
    )
    return PostVisitSqueeze(
        pending_store=resolved_pending,
        launch_from_assembly=LaunchFromAssemblyOrders(
            assembly_store=assembly_store,
            cycle_store=cycle_store,
            warehouse_stock=warehouse_stock,
            launch=launch,
        ),
        stock_store=stock_store,
        sales_after=MachineSalesMicromarketSalesAfter(sales_store=sales_store),
        alerter=build_micromarket_loading_alerter(settings),
        cycle_store=cycle_store,
        planogram_store=planogram_store,
        publisher=publisher,
        products=products,
        journal=journal,
        baseline_store=baseline_store,
        now_factory=lambda: datetime.now(UTC),
    )
