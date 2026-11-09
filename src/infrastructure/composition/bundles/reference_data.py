from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.master_data import (
    CoffeeEquipmentCatalogs,
)
from src.application.master_data import (
    MasterDataStores as _MDStores,
)
from src.application.master_data import (
    SystemUserStore as _SUStore,
)
from src.application.master_data import (
    TechnicianStore as _TechStore,
)
from src.application.reference_data.ports import (
    LocationRosterDraftStore,
    LocationRosterStore,
    ReferenceDataSnapshotStore,
)
from src.application.reference_data.provider import ReferenceDataProvider
from src.application.reference_data.sync import SyncReferenceData
from src.infrastructure.reference_data.product_catalog_ms_worker import (
    ProductCatalogMsSyncWorker,
)
from src.infrastructure.reference_data.worker import ReferenceDataSyncWorker


@beartype
@dataclass(frozen=True, slots=True)
class ReferenceDataBundle:
    provider: ReferenceDataProvider
    store: ReferenceDataSnapshotStore
    roster_store: LocationRosterStore
    roster_draft_store: LocationRosterDraftStore
    master_data_stores: _MDStores
    system_user_store: _SUStore
    technician_store: _TechStore
    sync: SyncReferenceData
    worker: ReferenceDataSyncWorker
    product_catalog_ms_worker: ProductCatalogMsSyncWorker | None = None
    coffee_equipment_stores: CoffeeEquipmentCatalogs | None = None
