from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.matrix_automation import (
    MatrixCatalogTabReader,
    MatrixReferenceDataProvider,
    MatrixReferenceSync,
    SyncGlobalAbort,
)
from src.application.matrix_automation.models import MatrixParseState
from src.application.matrix_automation.ports import SnackMachineLayoutStore
from src.application.reference_data import (
    ReferenceDataProvider,
    ReferenceDataSourceId,
    SyncReferenceData,
)
from src.application.reference_data.migrate_product_vitrine import (
    migrate_sheets_product_catalog_to_vitrine,
)
from src.application.reference_data.ports import ReferenceDataSnapshotStore
from src.config.matrix_automation import MatrixAutomationSettings
from src.config.settings import Settings
from src.infrastructure.mongodb.connection import MongoDatabaseSource
from src.infrastructure.mongodb.snack_machine_layouts import MongoSnackMachineLayoutStore
from src.infrastructure.reference_data.sheets_source_reader import SheetsReferenceDataSourceReader


@beartype
def build_matrix_reference_data_source_map(
    settings: MatrixAutomationSettings,
    *,
    sku_catalog_master_enabled: bool = False,
) -> dict[ReferenceDataSourceId, tuple[str, int]]:
    matrix = settings
    if not matrix.google_sheets_spreadsheet_id:
        return {}
    spreadsheet_id = matrix.google_sheets_spreadsheet_id.strip()
    source_map: dict[ReferenceDataSourceId, tuple[str, int]] = {}
    if not sku_catalog_master_enabled:
        assert matrix.product_multipliers_sheet_id is not None
        source_map[ReferenceDataSourceId.PRODUCT_MULTIPLIERS] = (
            spreadsheet_id,
            matrix.product_multipliers_sheet_id,
        )
    return source_map


@beartype
def build_matrix_reference_data_provider(
    settings: MatrixAutomationSettings,
) -> MatrixReferenceDataProvider:
    return MatrixReferenceDataProvider(
        product_multiplier_min=settings.product_multiplier_min,
        product_multiplier_max=settings.product_multiplier_max,
        matrix_multiplier_min=settings.matrix_multiplier_min,
        matrix_multiplier_max=settings.matrix_multiplier_max,
    )


@beartype
@dataclass(slots=True)
class MsCatalogHydratingMatrixSync:
    """Hydrate MS product_catalog → matrix name_to_code before utility/catalog sync."""

    inner: MatrixReferenceSync
    store: ReferenceDataSnapshotStore

    @beartype
    def sync(self) -> MatrixParseState | SyncGlobalAbort:
        migrate_sheets_product_catalog_to_vitrine(self.store)
        ref = ReferenceDataProvider()
        ref.hydrate_from_store(self.store)
        ms = ref.product_catalog_or_none()
        self.inner.provider.set_name_to_code(
            dict(ms.name_to_code) if ms is not None else {},
        )
        return self.inner.sync()


@beartype
def build_matrix_reference_sync(
    settings: Settings,
    *,
    store: ReferenceDataSnapshotStore,
    provider: MatrixReferenceDataProvider,
    catalog_reader: MatrixCatalogTabReader,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> MsCatalogHydratingMatrixSync:
    matrix_settings = settings.matrix_automation
    source_map = build_matrix_reference_data_source_map(
        matrix_settings,
        sku_catalog_master_enabled=matrix_settings.sku_catalog_master_enabled,
    )
    utility_sync = SyncReferenceData(
        reader=SheetsReferenceDataSourceReader(
            credentials_file=settings.google_sheets.credentials_file.strip(),
            sources=source_map,
        ),
        store=store,
        provider=provider,
        source_ids=tuple(source_map.keys()),
    )
    layout_store: SnackMachineLayoutStore | None = None
    # Not gated on MATRIX_WORKER_ENABLED — seed/import need the store when cron is off.
    if settings.mongodb.is_configured:
        layout_store = MongoSnackMachineLayoutStore.from_settings(
            settings.mongodb,
            client=client,
        )
    inner = MatrixReferenceSync(
        utility_sync=utility_sync,
        provider=provider,
        catalog_reader=catalog_reader,
        utility_source_ids=tuple(source_map.keys()),
        layout_master_enabled=matrix_settings.layout_master_enabled,
        layout_store=layout_store,
    )
    return MsCatalogHydratingMatrixSync(inner=inner, store=store)
