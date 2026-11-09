from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast
from zoneinfo import ZoneInfo

from beartype import beartype
from google.oauth2 import service_account
from googleapiclient.discovery import build
from pymongo import MongoClient

from src.application.reference_data import (
    ReferenceDataProvider,
    ReferenceDataSnapshotStore,
    SyncReferenceData,
)
from src.application.reference_data.product_display_names import (
    build_product_display_name_map,
)
from src.application.sales_monitoring import ExportSalesToSheet, SalesSheetExportResult
from src.application.sheets.technician_locations import list_all_machines_from_snapshot
from src.config.settings import Settings
from src.domain.ids import MachineId
from src.infrastructure.composition.factories import warm_up_reference_data_provider
from src.infrastructure.integrations.google.sheets.sheet_reader import (
    GOOGLE_SHEETS_WRITE_SCOPE,
)
from src.infrastructure.mongodb.sales_sheet_export_cursor import (
    MongoSalesSheetExportCursorStore,
)
from src.infrastructure.sales_monitoring.mongo_sales_for_sheet_export import (
    MongoSalesForSheetExportLoader,
)
from src.infrastructure.sales_monitoring.sales_sheet_export_writer import (
    GoogleSheetsSalesSheetExportWriter,
)
from src.infrastructure.sales_monitoring.telegram_notifiers import (
    TelegramSalesMonitoringAlertNotifier,
)

_logger = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class _MapMachineDisplayLookup:
    names: dict[MachineId, str]

    @beartype
    def name_for(self, machine_id: MachineId) -> str | None:
        return self.names.get(machine_id)


@beartype
@dataclass(frozen=True, slots=True)
class _MapProductDisplayLookup:
    names: dict[str, str]

    @beartype
    def name_for(self, product_code: str) -> str | None:
        return self.names.get(product_code.strip().casefold())


@beartype
def _machine_names_from_provider(provider: ReferenceDataProvider) -> dict[MachineId, str]:
    """Display names for sheet export: coffee∪snack∪micromarket catalog, then directory gaps.

    After master hydrate the catalog includes micromarket. ``locations_directory``
    still ``setdefault``s only for ids missing from the catalog (holes / other kinds).
    A catalog entry always wins over directory.
    """
    names: dict[MachineId, str] = {}
    snapshot = provider.locations_catalog_or_none()
    if snapshot is not None:
        names.update(
            {machine.id: machine.name for machine in list_all_machines_from_snapshot(snapshot)},
        )
    directory = provider.locations_directory_or_none()
    if directory is None:
        return names
    for placement in directory.placements:
        if placement.removed_on is not None:
            continue
        label = placement.name.strip()
        if not label:
            continue
        # Catalog wins; directory only fills gaps.
        names.setdefault(placement.machine_id, label)
    return names


@beartype
def _product_names_from_provider(provider: ReferenceDataProvider) -> dict[str, str]:
    return build_product_display_name_map(
        ms=provider.product_catalog_or_none(),
        vitrine=provider.product_vitrine_or_none(),
    )


@beartype
def run_sales_sheet_export_tick(
    *,
    execute: Callable[[], SalesSheetExportResult],
    notify_alert: Callable[[str], None],
) -> SalesSheetExportResult:
    _logger.info("sales_sheet_export_started")
    try:
        result = execute()
    except Exception:
        _logger.exception("sales_sheet_export_failed")
        try:
            notify_alert("sales_monitoring sales_sheet_export failed")
        except Exception:
            _logger.exception("sales_sheet_export_alert_failed")
        raise
    _logger.info(
        "sales_sheet_export_completed mode=%s exported_count=%s trimmed_count=%s "
        "pages=%s cursor_occurred_at=%s cursor_source_id=%s",
        result.mode,
        result.exported_count,
        result.trimmed_count,
        result.pages,
        result.cursor_occurred_at,
        result.cursor_source_id,
    )
    return result


@beartype
def build_sales_sheet_export_tick(
    settings: Settings,
    *,
    mongo_client: MongoClient[dict[str, Any]] | object,
    reference_data_provider: ReferenceDataProvider,
    reference_store: ReferenceDataSnapshotStore,
    reference_sync: SyncReferenceData,
    alert_notifier: TelegramSalesMonitoringAlertNotifier,
) -> Callable[[], None] | None:
    sm = settings.sales_monitoring
    if not sm.sales_sheet_export_enabled:
        return None

    spreadsheet_id = sm.sales_sheet_spreadsheet_id
    sheet_gid = sm.sales_sheet_gid
    assert spreadsheet_id is not None
    assert sheet_gid is not None

    typed_client = cast(MongoClient[dict[str, Any]], mongo_client)
    sales_loader = MongoSalesForSheetExportLoader.from_settings(
        settings.mongodb,
        client=typed_client,
    )
    cursor_store = MongoSalesSheetExportCursorStore.from_settings(
        settings.mongodb,
        client=typed_client,
    )

    credentials_file = settings.google_sheets.credentials_file.strip()

    def _service() -> Any:
        credentials = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
            credentials_file,
            scopes=[GOOGLE_SHEETS_WRITE_SCOPE],
        )
        return build("sheets", "v4", credentials=credentials)

    sheet_writer = GoogleSheetsSalesSheetExportWriter(
        service_factory=_service,
        spreadsheet_id=spreadsheet_id,
        sheet_id=sheet_gid,
    )
    timezone = ZoneInfo(sm.tz)
    max_rows = sm.sales_sheet_max_rows

    def export_tick() -> None:
        warm_up_reference_data_provider(
            provider=reference_data_provider,
            store=reference_store,
            sync=reference_sync,
        )
        use_case = ExportSalesToSheet(
            sales=sales_loader,
            cursor=cursor_store,
            sheet=sheet_writer,
            machines=_MapMachineDisplayLookup(
                names=_machine_names_from_provider(reference_data_provider),
            ),
            products=_MapProductDisplayLookup(
                names=_product_names_from_provider(reference_data_provider),
            ),
            timezone=timezone,
            max_rows=max_rows,
        )
        run_sales_sheet_export_tick(
            execute=use_case.execute,
            notify_alert=alert_notifier.notify_text,
        )

    return export_tick
