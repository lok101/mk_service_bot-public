from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.machine_operations.ports import DomainEventPublisher
from src.application.master_data import MachineKind
from src.application.master_data.ports import MasterMachineStore
from src.application.micromarket_loading import (
    ApplyMicromarketSaleToStock,
    MachineKindLookup,
    MicromarketDeviceStockStore,
    MicromarketPlanogramStore,
)
from src.application.micromarket_loading.move_command import MicromarketLoadingMoveCommandStore
from src.application.micromarket_loading.move_gateway import MicromarketMoveGateway
from src.application.micromarket_loading.ports import (
    MicromarketAssemblyOrderStore,
    MicromarketSupplyOrderStore,
    MicromarketWarehouseStockSnapshotPort,
    PendingMicromarketInventStore,
    ShopListLastSucceededSnapshotStore,
    ShopListPublishJournal,
    SupplyOrderCategoryFactsSnapshotPort,
)
from src.application.outbox.micromarket_loading_move import MicromarketLoadingMoveOutboxHandler
from src.config.settings import Settings
from src.domain.ids import MachineId
from src.infrastructure.composition.factories.integrations import build_moysklad_client
from src.infrastructure.integrations.moysklad.client_protocol import MoySkladClientPort
from src.infrastructure.micromarket_loading.move_command_store import (
    InMemoryMicromarketLoadingMoveCommandStore,
    MongoMicromarketLoadingMoveCommandStore,
)
from src.infrastructure.micromarket_loading.ms_move import MoySkladMicromarketMoveClient
from src.infrastructure.micromarket_loading.outbox_move_gateway import OutboxMicromarketMoveGateway
from src.infrastructure.mongodb.micromarket_assembly_orders import (
    MongoMicromarketAssemblyOrderStore,
)
from src.infrastructure.mongodb.micromarket_pending_invent import (
    MongoPendingMicromarketInventStore,
)
from src.infrastructure.mongodb.micromarket_planograms import MongoMicromarketPlanogramStore
from src.infrastructure.mongodb.micromarket_stock import MongoMicromarketDeviceStockStore
from src.infrastructure.mongodb.micromarket_supply_order_category_snapshot import (
    MongoSupplyOrderCategoryFactsSnapshotStore,
)
from src.infrastructure.mongodb.micromarket_supply_orders import MongoMicromarketSupplyOrderStore
from src.infrastructure.mongodb.micromarket_warehouse_stock_snapshot import (
    MongoMicromarketWarehouseStockSnapshotStore,
)
from src.infrastructure.mongodb.shop_list_last_succeeded_snapshot import (
    MongoShopListLastSucceededSnapshotStore,
)
from src.infrastructure.mongodb.shop_list_publish_journal import MongoShopListPublishJournal
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketAssemblyOrderStore,
    InMemoryMicromarketDeviceStockStore,
    InMemoryMicromarketPlanogramStore,
    InMemoryMicromarketSupplyOrderStore,
    InMemoryMicromarketWarehouseStockSnapshotStore,
    InMemoryPendingMicromarketInventStore,
    InMemoryShopListLastSucceededSnapshotStore,
    InMemoryShopListPublishJournal,
    InMemorySupplyOrderCategoryFactsSnapshotStore,
)


@beartype
@dataclass(frozen=True, slots=True)
class MasterDataMachineKindLookup(MachineKindLookup):
    _machines: MasterMachineStore

    @beartype
    def kind_of(self, machine_code: str) -> MachineKind | None:
        machine = self._machines.get(MachineId(machine_code))
        if machine is None:
            return None
        return machine.kind


@beartype
def build_micromarket_device_stock_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> MicromarketDeviceStockStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoMicromarketDeviceStockStore.from_settings(mongo, client=client)
    return InMemoryMicromarketDeviceStockStore()


@beartype
def build_micromarket_planogram_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> MicromarketPlanogramStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoMicromarketPlanogramStore.from_settings(mongo, client=client)
    return InMemoryMicromarketPlanogramStore()


@beartype
def build_shop_list_publish_journal(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> ShopListPublishJournal:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoShopListPublishJournal.from_settings(mongo, client=client)
    return InMemoryShopListPublishJournal()


@beartype
def build_shop_list_baseline_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> ShopListLastSucceededSnapshotStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoShopListLastSucceededSnapshotStore.from_settings(mongo, client=client)
    return InMemoryShopListLastSucceededSnapshotStore()


@beartype
def build_micromarket_supply_order_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> MicromarketSupplyOrderStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoMicromarketSupplyOrderStore.from_settings(mongo, client=client)
    return InMemoryMicromarketSupplyOrderStore()


@beartype
def build_micromarket_warehouse_stock_snapshot_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> MicromarketWarehouseStockSnapshotPort:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoMicromarketWarehouseStockSnapshotStore.from_settings(mongo, client=client)
    return InMemoryMicromarketWarehouseStockSnapshotStore()


@beartype
def build_supply_order_category_facts_snapshot_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> SupplyOrderCategoryFactsSnapshotPort:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoSupplyOrderCategoryFactsSnapshotStore.from_settings(mongo, client=client)
    return InMemorySupplyOrderCategoryFactsSnapshotStore()


@beartype
def build_micromarket_assembly_order_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> MicromarketAssemblyOrderStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoMicromarketAssemblyOrderStore.from_settings(mongo, client=client)
    return InMemoryMicromarketAssemblyOrderStore()


@beartype
def build_pending_micromarket_invent_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> PendingMicromarketInventStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoPendingMicromarketInventStore.from_settings(mongo, client=client)
    return InMemoryPendingMicromarketInventStore()


@beartype
def build_apply_micromarket_sale_to_stock(
    settings: Settings,
    *,
    machine_store: MasterMachineStore,
    client: MongoClient[dict[str, Any]] | None = None,
    stock_store: MicromarketDeviceStockStore | None = None,
) -> ApplyMicromarketSaleToStock:
    # LOK-160: call apply_micromarket_sale_to_stock.execute(...) after persist
    # shop sale with machine_code from ShopName.
    resolved_stock = stock_store or build_micromarket_device_stock_store(
        settings,
        client=client,
    )
    return ApplyMicromarketSaleToStock(
        stock_store=resolved_stock,
        machine_kind_lookup=MasterDataMachineKindLookup(_machines=machine_store),
    )


@beartype
def build_micromarket_loading_move_command_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> MicromarketLoadingMoveCommandStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoMicromarketLoadingMoveCommandStore.from_settings(mongo, client=client)
    return InMemoryMicromarketLoadingMoveCommandStore()


@beartype
def build_moysklad_micromarket_move_client(
    settings: Settings,
    moysklad_client: MoySkladClientPort | None,
) -> MoySkladMicromarketMoveClient | None:
    if moysklad_client is None:
        return None
    mm_loading = settings.micromarket_loading
    if (
        mm_loading.main_warehouse_id is None
        or mm_loading.organization_id is None
        or mm_loading.project_id is None
        or not mm_loading.warehouses_path.strip()
    ):
        return None
    return MoySkladMicromarketMoveClient(
        client=moysklad_client,
        main_warehouse_id=mm_loading.main_warehouse_id,
        organization_id=mm_loading.organization_id,
        project_id=mm_loading.project_id,
        warehouses_path=mm_loading.warehouses_path,
        warehouses_recursive=mm_loading.warehouses_recursive,
    )


@beartype
def build_admin_micromarket_loading_move_gateway(
    settings: Settings,
    *,
    publisher: DomainEventPublisher,
    warehouse_stock: MicromarketWarehouseStockSnapshotPort,
    move_command_store: MicromarketLoadingMoveCommandStore,
) -> MicromarketMoveGateway | None:
    if not settings.micromarket_loading.execute_enabled:
        return None
    if settings.micromarket_loading.require_execute_dependencies():
        return None  # incomplete execute env → admin keeps 503 guard
    mm = settings.micromarket_loading
    sync_execute = None
    move_client = build_moysklad_micromarket_move_client(
        settings,
        build_moysklad_client(settings.moysklad),
    )
    if move_client is not None:
        handler = MicromarketLoadingMoveOutboxHandler(
            command_store=move_command_store,
            move_client=move_client,
            clock=lambda: datetime.now(UTC),
        )
        sync_execute = handler.process
    return OutboxMicromarketMoveGateway(
        command_store=move_command_store,
        publisher=publisher,
        warehouse_stock=warehouse_stock,
        poll_interval_seconds=mm.move_outbox_poll_interval_seconds,
        poll_timeout_seconds=mm.move_outbox_poll_timeout_seconds,
        sync_execute=sync_execute,
    )
