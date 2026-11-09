from __future__ import annotations

from src.application.outbox.admin import (
    GetFailedOutboxEntryService,
    ListFailedOutboxEntriesQuery,
    ListFailedOutboxEntriesService,
    RequeueFailedOutboxEntryError,
    RequeueFailedOutboxEntryService,
)
from src.application.outbox.handler_ids import (
    DAILY_SALES_DEMAND_HANDLER_ID,
    LOADING_PHOTOS_HANDLER_ID,
    LOADING_PHOTOS_INTEGRITY_HANDLER_ID,
    LOADING_PHOTOS_TELEGRAM_HANDLER_ID,
    LOADING_TELEGRAM_HANDLER_ID,
    MACHINE_PNL_MONTH_HANDLER_ID,
    MACHINE_PNL_PERIOD_HANDLER_ID,
    PERIOD_RECONCILIATION_HANDLER_ID,
    REVISION_TELEGRAM_HANDLER_ID,
    SETTLEMENT_PORTION_HANDLER_IDS,
    SETTLEMENT_PORTION_RECONCILE_HANDLER_ID,
    SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID,
    SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID,
    TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID,
)
from src.application.outbox.technician_warehouse_loading import (
    FormSubmissionSnapshotMissingError,
    FormSubmissionSnapshotPurposeError,
    TechnicianWarehouseLoadingHandler,
)
from src.application.outbox.terminal_failure_notifier import OutboxTerminalFailureNotifier

__all__ = [
    "DAILY_SALES_DEMAND_HANDLER_ID",
    "FormSubmissionSnapshotMissingError",
    "FormSubmissionSnapshotPurposeError",
    "GetFailedOutboxEntryService",
    "LOADING_PHOTOS_HANDLER_ID",
    "LOADING_PHOTOS_INTEGRITY_HANDLER_ID",
    "LOADING_PHOTOS_TELEGRAM_HANDLER_ID",
    "LOADING_TELEGRAM_HANDLER_ID",
    "ListFailedOutboxEntriesQuery",
    "ListFailedOutboxEntriesService",
    "MACHINE_PNL_MONTH_HANDLER_ID",
    "MACHINE_PNL_PERIOD_HANDLER_ID",
    "OutboxTerminalFailureNotifier",
    "PERIOD_RECONCILIATION_HANDLER_ID",
    "REVISION_TELEGRAM_HANDLER_ID",
    "RequeueFailedOutboxEntryError",
    "RequeueFailedOutboxEntryService",
    "SETTLEMENT_PORTION_HANDLER_IDS",
    "SETTLEMENT_PORTION_RECONCILE_HANDLER_ID",
    "SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID",
    "SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID",
    "TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID",
    "TechnicianWarehouseLoadingHandler",
]
