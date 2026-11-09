from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.inventory_reconciliation.company_occupancy import (
    MachineCompanyOccupancyStore,
)
from src.infrastructure.integrations.kitshop.reference_snapshot import (
    KitShopReferenceSnapshotStore,
)
from src.infrastructure.kitshop_reference_snapshot_worker import (
    KitShopReferenceSnapshotWorker,
)
from src.infrastructure.kitshop_sales_ingest_worker import KitShopSalesIngestWorker
from src.infrastructure.sales_ingest_worker import SalesIngestWorker


@beartype
@dataclass(frozen=True, slots=True)
class SettlementBundle:
    sales_ingest_worker: SalesIngestWorker | None
    kitshop_sales_ingest_worker: KitShopSalesIngestWorker | None
    kitvending_client: object
    company_occupancy_store: MachineCompanyOccupancyStore
    kitshop_reference_snapshot_store: KitShopReferenceSnapshotStore | None = None
    kitshop_reference_snapshot_worker: KitShopReferenceSnapshotWorker | None = None
