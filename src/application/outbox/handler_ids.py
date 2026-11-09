from __future__ import annotations

REVISION_TELEGRAM_HANDLER_ID = "revision_telegram"
LOADING_TELEGRAM_HANDLER_ID = "loading_telegram"
LOADING_PHOTOS_HANDLER_ID = "loading_photos"
LOADING_PHOTOS_INTEGRITY_HANDLER_ID = "loading_photos_integrity"
LOADING_PHOTOS_TELEGRAM_HANDLER_ID = "loading_photos_telegram"
VISIT_PHOTO_GROUPING_HANDLER_ID = "visit_photo_grouping"
TECHNICIAN_WAREHOUSE_INVENTORY_TELEGRAM_HANDLER_ID = "technician_warehouse_inventory_telegram"
TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID = "technician_warehouse_loading"
PERIOD_RECONCILIATION_HANDLER_ID = "period_reconciliation"
SALES_MONITORING_AUDIT_HANDLER_ID = "sales_monitoring_audit"
SERVICE_VISIT_ON_MAINTENANCE_HANDLER_ID = "service_visit_on_maintenance"
SERVICE_VISIT_INCIDENT_HANDLER_ID = "service_visit_incident"
VISIT_FORCE_NOTIFY_HANDLER_ID = "visit_force_notify"
MACHINE_PNL_PERIOD_HANDLER_ID = "machine_pnl_period"
MACHINE_PNL_MONTH_HANDLER_ID = "machine_pnl_month"
DAILY_SALES_DEMAND_HANDLER_ID = "daily_sales_demand"
MICROMARKET_SHOP_LIST_PUBLISH_HANDLER_ID = "micromarket_shop_list_publish"
MICROMARKET_LOADING_MOVE_HANDLER_ID = "micromarket_loading_move"
MICROMARKET_POST_VISIT_SQUEEZE_HANDLER_ID = "micromarket_post_visit_squeeze"
NO_SALES_INCIDENT_CONTROL_HANDLER_ID = "no_sales_incident_control"
SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID = "settlement_portion_sync_transfers"
SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID = "settlement_portion_sales_verify"
SETTLEMENT_PORTION_RECONCILE_HANDLER_ID = "settlement_portion_reconcile"
SETTLEMENT_PORTION_HANDLER_IDS: frozenset[str] = frozenset(
    {
        SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID,
        SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID,
        SETTLEMENT_PORTION_RECONCILE_HANDLER_ID,
    }
)
