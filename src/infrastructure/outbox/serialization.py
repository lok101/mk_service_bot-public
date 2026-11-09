from __future__ import annotations

from typing import Any

from beartype import beartype

from src.domain.events import DomainEvent
from src.domain.inventory_reconciliation.events import DailySalesDemandRequested
from src.domain.machine_pnl.events import MachineMonthPnlRequested, MachinePeriodPnlRequested
from src.domain.micromarket_loading.move_command_event import MicromarketLoadingMoveCommandRequested
from src.domain.micromarket_loading.post_visit_squeeze_event import (
    MicromarketPostVisitSqueezeRequested,
)
from src.domain.micromarket_loading.publish_event import MicromarketShopListPublishRequested
from src.domain.sales_monitoring.control_event import NoSalesIncidentControlRequested
from src.domain.sales_monitoring.events import (
    SalesMonitoringNoSalesStaleCleared,
    SalesMonitoringNoSalesStaleOpened,
    SalesMonitoringOfflineCleared,
    SalesMonitoringOfflineOpened,
    SalesMonitoringTodayNoSales,
    SalesMonitoringYesterdayDecline,
    SalesMonitoringYesterdayNoSales,
)
from src.domain.service_visits import ServiceVisitForceNotifyRequested
from src.domain.technician_settlement.portion_events import (
    SettlementPortionReconcileRequested,
    SettlementPortionSalesVerifyRequested,
    SettlementPortionSyncTransfersRequested,
)
from src.domain.technician_warehouse.events import (
    TechnicianWarehouseInventoryCounted,
    TechnicianWarehouseLoadingObserved,
    TechnicianWarehouseTransferFinalized,
    TechnicianWarehouseTransferObserved,
    TechnicianWarehouseTransferVoided,
)
from src.infrastructure.mongodb.daily_sales_demand_serialization import (
    DAILY_SALES_DEMAND_AGGREGATE_TYPE,
    daily_sales_demand_event_from_document,
    daily_sales_demand_event_to_document,
)
from src.infrastructure.mongodb.machine_pnl_serialization import (
    MACHINE_PNL_AGGREGATE_TYPE,
    machine_pnl_event_from_document,
    machine_pnl_event_to_document,
)
from src.infrastructure.mongodb.micromarket_loading_move_serialization import (
    MICROMARKET_LOADING_MOVE_AGGREGATE_TYPE,
    micromarket_loading_move_event_from_document,
    micromarket_loading_move_event_to_document,
)
from src.infrastructure.mongodb.micromarket_post_visit_squeeze_serialization import (
    MICROMARKET_POST_VISIT_SQUEEZE_AGGREGATE_TYPE,
    micromarket_post_visit_squeeze_event_from_document,
    micromarket_post_visit_squeeze_event_to_document,
)
from src.infrastructure.mongodb.micromarket_shop_list_serialization import (
    MICROMARKET_SHOP_LIST_AGGREGATE_TYPE,
    micromarket_shop_list_event_from_document,
    micromarket_shop_list_event_to_document,
)
from src.infrastructure.mongodb.sales_monitoring_serialization import (
    SALES_MONITORING_AGGREGATE_TYPE,
    sales_monitoring_event_from_document,
    sales_monitoring_event_to_document,
)
from src.infrastructure.mongodb.serialization import (
    document_from_event,
    event_from_bson,
)
from src.infrastructure.mongodb.service_visit_force_notify_serialization import (
    SERVICE_VISIT_FORCE_NOTIFY_AGGREGATE_TYPE,
    service_visit_force_notify_event_from_document,
    service_visit_force_notify_event_to_document,
)
from src.infrastructure.mongodb.settlement_portion_serialization import (
    SETTLEMENT_PORTION_AGGREGATE_TYPE,
    settlement_portion_event_from_document,
    settlement_portion_event_to_document,
)
from src.infrastructure.mongodb.technician_warehouse_serialization import (
    TECHNICIAN_WAREHOUSE_AGGREGATE_TYPE,
    warehouse_event_from_document,
    warehouse_event_to_document,
)

_NON_OUTBOX_WAREHOUSE_EVENTS = (
    TechnicianWarehouseTransferObserved,
    TechnicianWarehouseTransferVoided,
    TechnicianWarehouseLoadingObserved,
    TechnicianWarehouseTransferFinalized,
)

_SALES_MONITORING_EVENTS = (
    SalesMonitoringYesterdayNoSales,
    SalesMonitoringYesterdayDecline,
    SalesMonitoringTodayNoSales,
    SalesMonitoringOfflineOpened,
    SalesMonitoringOfflineCleared,
    SalesMonitoringNoSalesStaleOpened,
    SalesMonitoringNoSalesStaleCleared,
    NoSalesIncidentControlRequested,
)

_SETTLEMENT_PORTION_EVENTS = (
    SettlementPortionSyncTransfersRequested,
    SettlementPortionSalesVerifyRequested,
    SettlementPortionReconcileRequested,
)


@beartype
def event_to_outbox_document(event: DomainEvent) -> dict[str, Any]:
    if isinstance(event, TechnicianWarehouseInventoryCounted):
        return warehouse_event_to_document(event, aggregate_version=0)
    if isinstance(event, _NON_OUTBOX_WAREHOUSE_EVENTS):
        raise TypeError(
            f"Warehouse event type not supported in outbox: {type(event).__name__}",
        )
    if isinstance(event, _SALES_MONITORING_EVENTS):
        return sales_monitoring_event_to_document(event, aggregate_version=0)
    if isinstance(event, (MachinePeriodPnlRequested, MachineMonthPnlRequested)):
        return machine_pnl_event_to_document(event, aggregate_version=0)
    if isinstance(event, DailySalesDemandRequested):
        return daily_sales_demand_event_to_document(event, aggregate_version=0)
    if isinstance(event, _SETTLEMENT_PORTION_EVENTS):
        return settlement_portion_event_to_document(event, aggregate_version=0)
    if isinstance(event, ServiceVisitForceNotifyRequested):
        return service_visit_force_notify_event_to_document(event, aggregate_version=0)
    if isinstance(event, MicromarketShopListPublishRequested):
        return micromarket_shop_list_event_to_document(event, aggregate_version=0)
    if isinstance(event, MicromarketLoadingMoveCommandRequested):
        return micromarket_loading_move_event_to_document(event, aggregate_version=0)
    if isinstance(event, MicromarketPostVisitSqueezeRequested):
        return micromarket_post_visit_squeeze_event_to_document(event, aggregate_version=0)
    return document_from_event(event, aggregate_version=0)


@beartype
def event_from_outbox_document(document: dict[str, Any]) -> DomainEvent:
    if document.get("aggregate_type") == TECHNICIAN_WAREHOUSE_AGGREGATE_TYPE:
        event = warehouse_event_from_document(document)
        if not isinstance(event, TechnicianWarehouseInventoryCounted):
            raise TypeError(
                "Only TechnicianWarehouseInventoryCounted is supported in outbox "
                f"(got {type(event).__name__})",
            )
        return event
    if document.get("aggregate_type") == SALES_MONITORING_AGGREGATE_TYPE:
        return sales_monitoring_event_from_document(document)
    if document.get("aggregate_type") == MACHINE_PNL_AGGREGATE_TYPE:
        return machine_pnl_event_from_document(document)
    if document.get("aggregate_type") == DAILY_SALES_DEMAND_AGGREGATE_TYPE:
        return daily_sales_demand_event_from_document(document)
    if document.get("aggregate_type") == SETTLEMENT_PORTION_AGGREGATE_TYPE:
        return settlement_portion_event_from_document(document)
    if document.get("aggregate_type") == SERVICE_VISIT_FORCE_NOTIFY_AGGREGATE_TYPE:
        return service_visit_force_notify_event_from_document(document)
    if document.get("aggregate_type") == MICROMARKET_SHOP_LIST_AGGREGATE_TYPE:
        return micromarket_shop_list_event_from_document(document)
    if document.get("aggregate_type") == MICROMARKET_LOADING_MOVE_AGGREGATE_TYPE:
        return micromarket_loading_move_event_from_document(document)
    if document.get("aggregate_type") == MICROMARKET_POST_VISIT_SQUEEZE_AGGREGATE_TYPE:
        return micromarket_post_visit_squeeze_event_from_document(document)
    return event_from_bson(document)
