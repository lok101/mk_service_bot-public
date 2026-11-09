from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import UUID

from beartype import beartype

from src.application.reference_data.models import (
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
)
from src.application.reference_data.ms_product_catalog import MsProductEntry
from src.domain.ids import MachineId

if TYPE_CHECKING:
    from src.application.reference_data.location_roster import (
        LocationRosterAuditRecord,
        LocationRosterEntry,
    )


@runtime_checkable
class ReferenceDataSnapshotStore(Protocol):
    @beartype
    def get(self, source_id: ReferenceDataSourceId) -> ReferenceDataSnapshot | None: ...

    @beartype
    def put(self, snapshot: ReferenceDataSnapshot) -> None: ...

    @beartype
    def get_by_id(self, snapshot_id: str) -> ReferenceDataSnapshot | None: ...

    @beartype
    def delete_by_id(self, snapshot_id: str) -> None: ...

    @beartype
    def record_sync_error(
        self,
        source_id: ReferenceDataSourceId,
        message: str,
        at: datetime,
    ) -> None: ...


@runtime_checkable
class ReferenceDataSourceReader(Protocol):
    @beartype
    def read_rows(self, source_id: ReferenceDataSourceId) -> list[list[str]]: ...


@runtime_checkable
class ProductCatalogMsAssortmentReader(Protocol):
    @beartype
    async def list_by_folder_ids(
        self,
        *,
        entity_kind: str,  # "product" | "bundle"
        folder_ids: Sequence[UUID],
    ) -> list[MsProductEntry]: ...


@runtime_checkable
class ProductCatalogDrinkSource(Protocol):
    @beartype
    def list_drink_entries(self) -> Sequence[MsProductEntry]: ...


@runtime_checkable
class LocationRosterStore(Protocol):
    @beartype
    def get(self, machine_id: MachineId) -> LocationRosterEntry | None: ...

    @beartype
    def list_all(self) -> tuple[LocationRosterEntry, ...]: ...

    @beartype
    def is_empty(self) -> bool: ...

    @beartype
    def replace_all(self, entries: tuple[LocationRosterEntry, ...]) -> None: ...

    @beartype
    def save_batch(
        self,
        entries: tuple[LocationRosterEntry, ...],
        *,
        actor_telegram_user_id: int,
        at: datetime,
    ) -> None: ...

    @beartype
    def list_audit(self) -> tuple[LocationRosterAuditRecord, ...]: ...


@runtime_checkable
class LocationRosterDraftStore(Protocol):
    @beartype
    def get(self, machine_id: MachineId) -> LocationRosterEntry | None: ...

    @beartype
    def list_all(self) -> tuple[LocationRosterEntry, ...]: ...

    @beartype
    def is_empty(self) -> bool: ...

    @beartype
    def replace_all(self, entries: tuple[LocationRosterEntry, ...]) -> None: ...

    @beartype
    def upsert(
        self,
        entry: LocationRosterEntry,
        *,
        expected_updated_at: datetime | None,
    ) -> LocationRosterEntry: ...


__all__ = [
    "LocationRosterDraftStore",
    "LocationRosterStore",
    "ProductCatalogDrinkSource",
    "ProductCatalogMsAssortmentReader",
    "ReferenceDataSnapshotStore",
    "ReferenceDataSourceReader",
]
