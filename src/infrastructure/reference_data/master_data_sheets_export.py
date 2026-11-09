from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from beartype import beartype

from src.application.master_data import MasterDataStores, TechnicianStore
from src.application.reference_data.master_data_export import (
    build_locations_directory_export_rows,
    build_machines_mirror_export_rows,
    build_technicians_directory_export_rows,
)
from src.application.reference_data.ports import LocationRosterStore
from src.domain.ids import MachineId, TechnicianId
from src.infrastructure.integrations.google.sheets.sheet_reader import (  # noqa: SLF001
    _get_rate_limiter,
    resolve_sheet_title,
)

_LOGGER = logging.getLogger(__name__)

MASTER_DATA_EXPORT_API_MAX_ATTEMPTS = 3
MASTER_DATA_EXPORT_API_RETRY_DELAY_SECONDS = 1


@runtime_checkable
class MasterDataExportPort(Protocol):
    def export_all(self, stores: MasterDataStores) -> None: ...


@beartype
@dataclass(slots=True)
class RecordingMasterDataExport:
    calls: list[MasterDataStores] = field(default_factory=list)

    @beartype
    def export_all(self, stores: MasterDataStores) -> None:
        self.calls.append(stores)


@beartype
@dataclass(frozen=True, slots=True)
class FailingMasterDataExport:
    message: str = "sheets down"

    @beartype
    def export_all(self, stores: MasterDataStores) -> None:
        raise RuntimeError(self.message)


@beartype
@dataclass(frozen=True, slots=True)
class MasterDataSheetTarget:
    spreadsheet_id: str
    sheet_id: int


@beartype
@dataclass(frozen=True, slots=True)
class GoogleSheetsMasterDataExport:
    service_factory: Callable[[], Any]
    locations: MasterDataSheetTarget
    machines: MasterDataSheetTarget
    roster: LocationRosterStore
    technician_names: dict[TechnicianId, str]
    company_names_provider: Callable[[MasterDataStores], dict[MachineId, str]]
    sleep: Callable[[float], None] = time.sleep

    @beartype
    def export_all(self, stores: MasterDataStores) -> None:
        location_rows = build_locations_directory_export_rows(stores)
        company_names = self.company_names_provider(stores)
        machine_rows = build_machines_mirror_export_rows(
            stores,
            roster=self.roster,
            technician_names=self.technician_names,
            company_names=company_names,
        )
        self._replace_sheet(self.locations, location_rows)
        self._replace_sheet(self.machines, machine_rows)

    @beartype
    def _replace_sheet(
        self,
        target: MasterDataSheetTarget,
        rows: Sequence[Sequence[str]],
    ) -> None:
        body_values = [list(row) for row in rows]

        def _op(service: Any) -> None:
            title = resolve_sheet_title(
                service=service,
                spreadsheet_id=target.spreadsheet_id,
                sheet_id=target.sheet_id,
            )
            service.spreadsheets().values().clear(
                spreadsheetId=target.spreadsheet_id,
                range=f"'{title}'",
            ).execute()
            if not body_values:
                return
            service.spreadsheets().values().update(
                spreadsheetId=target.spreadsheet_id,
                range=f"'{title}'!A1",
                valueInputOption="USER_ENTERED",
                body={"values": body_values},
            ).execute()

        self._with_retry(_op)

    @beartype
    def _with_retry(self, operation: Callable[[Any], None]) -> None:
        last_error: Exception | None = None
        for attempt in range(1, MASTER_DATA_EXPORT_API_MAX_ATTEMPTS + 1):
            _get_rate_limiter().acquire()
            try:
                operation(self.service_factory())
                return
            except Exception as exc:
                last_error = exc
                _LOGGER.warning(
                    "master_data sheets export attempt %s/%s failed: %s",
                    attempt,
                    MASTER_DATA_EXPORT_API_MAX_ATTEMPTS,
                    exc,
                )
                if attempt < MASTER_DATA_EXPORT_API_MAX_ATTEMPTS:
                    self.sleep(MASTER_DATA_EXPORT_API_RETRY_DELAY_SECONDS)
        assert last_error is not None
        raise last_error


@beartype
@dataclass(frozen=True, slots=True)
class GoogleSheetsTechniciansDirectoryExport:
    """Best-effort Sheets mirror for technicians directory (Callable[[], None] hook)."""

    service_factory: Callable[[], Any]
    target: MasterDataSheetTarget
    store: TechnicianStore
    sleep: Callable[[float], None] = time.sleep

    @beartype
    def __call__(self) -> None:
        rows = build_technicians_directory_export_rows(self.store)
        body_values = [list(row) for row in rows]

        def _op(service: Any) -> None:
            title = resolve_sheet_title(
                service=service,
                spreadsheet_id=self.target.spreadsheet_id,
                sheet_id=self.target.sheet_id,
            )
            service.spreadsheets().values().clear(
                spreadsheetId=self.target.spreadsheet_id,
                range=f"'{title}'",
            ).execute()
            if not body_values:
                return
            service.spreadsheets().values().update(
                spreadsheetId=self.target.spreadsheet_id,
                range=f"'{title}'!A1",
                valueInputOption="USER_ENTERED",
                body={"values": body_values},
            ).execute()

        last_error: Exception | None = None
        for attempt in range(1, MASTER_DATA_EXPORT_API_MAX_ATTEMPTS + 1):
            try:
                _op(self.service_factory())
                return
            except Exception as exc:
                last_error = exc
                _LOGGER.warning(
                    "technicians directory sheets export attempt %s/%s failed: %s",
                    attempt,
                    MASTER_DATA_EXPORT_API_MAX_ATTEMPTS,
                    exc,
                )
                if attempt < MASTER_DATA_EXPORT_API_MAX_ATTEMPTS:
                    self.sleep(MASTER_DATA_EXPORT_API_RETRY_DELAY_SECONDS)
        assert last_error is not None
        raise last_error
