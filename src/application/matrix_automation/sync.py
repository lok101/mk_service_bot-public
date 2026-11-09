from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.matrix_automation.models import MatrixParseState
from src.application.matrix_automation.ports import SnackMachineLayoutStore
from src.application.matrix_automation.provider import MatrixReferenceDataProvider
from src.application.reference_data import ReferenceDataSnapshotStore, ReferenceDataSourceId


@beartype
@dataclass(frozen=True, slots=True)
class SyncGlobalAbort:
    reason: str


@runtime_checkable
class MatrixCatalogTabReader(Protocol):
    def list_catalog_tabs(self) -> list[tuple[str, list[list[str]]]]: ...


@runtime_checkable
class MatrixUtilitySync(Protocol):
    store: ReferenceDataSnapshotStore

    def sync_source(self, source_id: ReferenceDataSourceId) -> None: ...


@beartype
@dataclass(slots=True)
class MatrixReferenceSync:
    utility_sync: MatrixUtilitySync
    provider: MatrixReferenceDataProvider
    catalog_reader: MatrixCatalogTabReader
    utility_source_ids: tuple[ReferenceDataSourceId, ...]
    layout_master_enabled: bool = False
    layout_store: SnackMachineLayoutStore | None = None

    @beartype
    def sync(self) -> MatrixParseState | SyncGlobalAbort:
        self.provider.reset_catalog_parse()
        for source_id in self.utility_source_ids:
            try:
                self.utility_sync.sync_source(source_id)
            except Exception as exc:  # noqa: BLE001
                self.provider.reset_catalog_parse()
                return SyncGlobalAbort(reason=str(exc))
            snapshot = self.utility_sync.store.get(source_id)
            if snapshot is not None and snapshot.last_sync_error is not None:
                self.provider.reset_catalog_parse()
                return SyncGlobalAbort(reason=snapshot.last_sync_error.message)
        if self.layout_master_enabled:
            layouts = () if self.layout_store is None else self.layout_store.list_all()
            for layout in layouts:
                self.provider.apply_snack_layout(layout)
            return self.provider.build_parse_state()
        try:
            for title, rows in self.catalog_reader.list_catalog_tabs():
                self.provider.apply_catalog_tab(title, rows)
        except ValueError as exc:
            self.provider.reset_catalog_parse()
            return SyncGlobalAbort(reason=str(exc))
        return self.provider.build_parse_state()
