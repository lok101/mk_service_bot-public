from __future__ import annotations

import logging
from dataclasses import dataclass, field

from beartype import beartype

from src.application.reference_data.errors import ReferenceDataUnavailable
from src.application.reference_data.location_roster_overlay import overlay_location_roster
from src.application.reference_data.locations_merge import (
    assert_locations_kind_for_source,
    assert_locations_merge_compatible,
    filter_locations_by_machine_ids,
    merge_locations_catalog,
)
from src.application.reference_data.models import (
    APP_REFERENCE_DATA_SOURCE_IDS,
    ReferenceDataSourceId,
)
from src.application.reference_data.ms_product_catalog import (
    ParsedMsProductCatalog,
    parse_ms_product_catalog_rows,
)
from src.application.reference_data.ports import LocationRosterStore, ReferenceDataSnapshotStore
from src.application.sheets import (
    LocationsDirectorySnapshot,
    ParsedProductCatalog,
    SystemUsersSnapshot,
    TechnicianLocationsSnapshot,
    TechniciansDirectorySnapshot,
    build_locations_directory_snapshot,
    build_system_users_snapshot,
    build_technician_locations_snapshot,
    build_technicians_directory_snapshot,
    list_all_machines_from_snapshot,
    parse_product_catalog_sheet,
)

_LOGGER = logging.getLogger(__name__)


@beartype
@dataclass(slots=True)
class ReferenceDataProvider:
    _coffee_locations: TechnicianLocationsSnapshot | None = field(default=None, repr=False)
    _snack_locations: TechnicianLocationsSnapshot | None = field(default=None, repr=False)
    _micromarket_locations: TechnicianLocationsSnapshot | None = field(default=None, repr=False)
    _system_users: SystemUsersSnapshot | None = field(default=None, repr=False)
    _technicians_directory: TechniciansDirectorySnapshot | None = field(
        default=None,
        repr=False,
    )
    _locations_directory: LocationsDirectorySnapshot | None = field(default=None, repr=False)
    _product_vitrine: ParsedProductCatalog | None = field(default=None, repr=False)
    _ms_product_catalog: ParsedMsProductCatalog | None = field(default=None, repr=False)
    _degraded_logged: set[ReferenceDataSourceId] = field(default_factory=set, repr=False)
    _roster_enabled: bool = False
    _roster_store: LocationRosterStore | None = None

    @beartype
    def apply_rows(self, source_id: ReferenceDataSourceId, rows: list[list[str]]) -> None:
        if source_id in (
            ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
            ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS,
        ):
            self._apply_locations(source_id, rows)
        elif source_id is ReferenceDataSourceId.BOT_USERS:
            self._system_users = build_system_users_snapshot(rows)
        elif source_id is ReferenceDataSourceId.TECHNICIANS_DIRECTORY:
            self._technicians_directory = build_technicians_directory_snapshot(rows)
        elif source_id is ReferenceDataSourceId.LOCATIONS_DIRECTORY:
            self._locations_directory = build_locations_directory_snapshot(rows)
        elif source_id is ReferenceDataSourceId.PRODUCT_VITRINE:
            self._product_vitrine = parse_product_catalog_sheet(rows)
        elif source_id is ReferenceDataSourceId.PRODUCT_CATALOG:
            self._ms_product_catalog = parse_ms_product_catalog_rows(rows)
        else:
            msg = f"unsupported app reference source: {source_id}"
            raise ValueError(msg)
        self._degraded_logged.discard(source_id)

    @beartype
    def configure_roster(self, *, enabled: bool, store: LocationRosterStore | None) -> None:
        self._roster_enabled = enabled
        self._roster_store = store

    @beartype
    def apply_master_snapshots(
        self,
        *,
        coffee: TechnicianLocationsSnapshot | None,
        snack: TechnicianLocationsSnapshot | None,
        micromarket: TechnicianLocationsSnapshot | None = None,
        locations_directory: LocationsDirectorySnapshot | None,
    ) -> None:
        if coffee is not None:
            if self._snack_locations is not None:
                assert_locations_merge_compatible(coffee, self._snack_locations)
            if self._micromarket_locations is not None:
                assert_locations_merge_compatible(coffee, self._micromarket_locations)
            self._coffee_locations = coffee
            self._degraded_logged.discard(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS)
        if snack is not None:
            if self._coffee_locations is not None:
                assert_locations_merge_compatible(snack, self._coffee_locations)
            if self._micromarket_locations is not None:
                assert_locations_merge_compatible(snack, self._micromarket_locations)
            self._snack_locations = snack
            self._degraded_logged.discard(ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS)
        if micromarket is not None:
            if self._coffee_locations is not None:
                assert_locations_merge_compatible(micromarket, self._coffee_locations)
            if self._snack_locations is not None:
                assert_locations_merge_compatible(micromarket, self._snack_locations)
            self._micromarket_locations = micromarket
        if locations_directory is not None:
            self._locations_directory = locations_directory
            self._degraded_logged.discard(ReferenceDataSourceId.LOCATIONS_DIRECTORY)

    @beartype
    def _apply_locations(
        self,
        source_id: ReferenceDataSourceId,
        rows: list[list[str]],
    ) -> None:
        snapshot = (
            build_technician_locations_snapshot(rows, assignments="fleet")
            if self._roster_enabled
            else build_technician_locations_snapshot(rows)
        )
        assert_locations_kind_for_source(snapshot, source_id)
        other = (
            self._snack_locations
            if source_id is ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS
            else self._coffee_locations
        )
        if other is not None:
            assert_locations_merge_compatible(snapshot, other)
        if self._micromarket_locations is not None:
            assert_locations_merge_compatible(snapshot, self._micromarket_locations)
        if source_id is ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS:
            self._coffee_locations = snapshot
        else:
            self._snack_locations = snapshot

    @beartype
    def hydrate_from_store(
        self,
        store: ReferenceDataSnapshotStore,
        *,
        skip_source_ids: frozenset[ReferenceDataSourceId] = frozenset(),
    ) -> None:
        for source_id in APP_REFERENCE_DATA_SOURCE_IDS:
            if source_id in skip_source_ids:
                continue
            snapshot = store.get(source_id)
            if snapshot is None or not snapshot.rows:
                continue
            rows = [list(row) for row in snapshot.rows]
            try:
                self.apply_rows(source_id, rows)
            except Exception as exc:  # noqa: BLE001 - degrade per source, never crash startup
                _LOGGER.warning(
                    "reference_data_hydrate_failed",
                    extra={"source_id": source_id.value, "error": str(exc)},
                )

        for extra_id in (
            ReferenceDataSourceId.PRODUCT_CATALOG,
            ReferenceDataSourceId.LOCATIONS_DIRECTORY,
        ):
            extra_snapshot = store.get(extra_id)
            if extra_snapshot is None or not extra_snapshot.rows:
                continue
            extra_rows = [list(row) for row in extra_snapshot.rows]
            try:
                self.apply_rows(extra_id, extra_rows)
            except Exception as exc:  # noqa: BLE001 - degrade per source, never crash startup
                _LOGGER.warning(
                    "reference_data_hydrate_failed",
                    extra={"source_id": extra_id.value, "error": str(exc)},
                )

    @beartype
    def has_source(self, source_id: ReferenceDataSourceId) -> bool:
        if source_id is ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS:
            return self._coffee_locations is not None
        if source_id is ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS:
            return self._snack_locations is not None
        if source_id is ReferenceDataSourceId.BOT_USERS:
            return self._system_users is not None
        if source_id is ReferenceDataSourceId.TECHNICIANS_DIRECTORY:
            return self._technicians_directory is not None
        if source_id is ReferenceDataSourceId.LOCATIONS_DIRECTORY:
            return self._locations_directory is not None
        if source_id is ReferenceDataSourceId.PRODUCT_VITRINE:
            return self._product_vitrine is not None
        if source_id is ReferenceDataSourceId.PRODUCT_CATALOG:
            return self._ms_product_catalog is not None
        return False

    @beartype
    def locations_catalog_or_none(self) -> TechnicianLocationsSnapshot | None:
        catalog = merge_locations_catalog(
            self._coffee_locations,
            self._snack_locations,
            self._micromarket_locations,
        )
        if catalog is None:
            self._note_degraded(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS)
            return None
        if self._roster_enabled and self._roster_store is not None:
            return overlay_location_roster(
                catalog,
                store=self._roster_store,
                directory=self._technicians_directory,
            )
        return catalog

    @beartype
    def locations_catalog(self) -> TechnicianLocationsSnapshot:
        catalog = self.locations_catalog_or_none()
        if catalog is None:
            raise ReferenceDataUnavailable(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS)
        return catalog

    @beartype
    def coffee_locations_or_none(self) -> TechnicianLocationsSnapshot | None:
        catalog = self.locations_catalog_or_none()
        if catalog is None:
            return None
        allowed = self._snapshot_machine_ids(self._coffee_locations)
        return filter_locations_by_machine_ids(catalog, allowed)

    @beartype
    def coffee_locations(self) -> TechnicianLocationsSnapshot:
        snapshot = self.coffee_locations_or_none()
        if snapshot is None:
            raise ReferenceDataUnavailable(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS)
        return snapshot

    @beartype
    def service_locations_or_none(self) -> TechnicianLocationsSnapshot | None:
        catalog = self.locations_catalog_or_none()
        if catalog is None:
            return None
        allowed = self._snapshot_machine_ids(self._coffee_locations) | self._snapshot_machine_ids(
            self._micromarket_locations,
        )
        return filter_locations_by_machine_ids(catalog, allowed)

    @beartype
    def service_locations(self) -> TechnicianLocationsSnapshot:
        snapshot = self.service_locations_or_none()
        if snapshot is None:
            raise ReferenceDataUnavailable(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS)
        return snapshot

    @beartype
    def _snapshot_machine_ids(
        self,
        snapshot: TechnicianLocationsSnapshot | None,
    ) -> frozenset[str]:
        if snapshot is None:
            return frozenset()
        return frozenset(m.id.value for m in list_all_machines_from_snapshot(snapshot))

    @beartype
    def apply_system_users_snapshot(self, snapshot: SystemUsersSnapshot) -> None:
        self._system_users = snapshot
        self._degraded_logged.discard(ReferenceDataSourceId.BOT_USERS)

    @beartype
    def apply_technicians_directory_snapshot(
        self,
        snapshot: TechniciansDirectorySnapshot,
    ) -> None:
        self._technicians_directory = snapshot
        self._degraded_logged.discard(ReferenceDataSourceId.TECHNICIANS_DIRECTORY)

    @beartype
    def system_users_or_none(self) -> SystemUsersSnapshot | None:
        if self._system_users is None:
            self._note_degraded(ReferenceDataSourceId.BOT_USERS)
        return self._system_users

    @beartype
    def system_users(self) -> SystemUsersSnapshot:
        snapshot = self.system_users_or_none()
        if snapshot is None:
            raise ReferenceDataUnavailable(ReferenceDataSourceId.BOT_USERS)
        return snapshot

    @beartype
    def technicians_directory_or_none(self) -> TechniciansDirectorySnapshot | None:
        if self._technicians_directory is None:
            self._note_degraded(ReferenceDataSourceId.TECHNICIANS_DIRECTORY)
        return self._technicians_directory

    @beartype
    def technicians_directory(self) -> TechniciansDirectorySnapshot:
        snapshot = self.technicians_directory_or_none()
        if snapshot is None:
            raise ReferenceDataUnavailable(ReferenceDataSourceId.TECHNICIANS_DIRECTORY)
        return snapshot

    @beartype
    def locations_directory_or_none(self) -> LocationsDirectorySnapshot | None:
        if self._locations_directory is None:
            self._note_degraded(ReferenceDataSourceId.LOCATIONS_DIRECTORY)
        return self._locations_directory

    @beartype
    def locations_directory(self) -> LocationsDirectorySnapshot:
        snapshot = self.locations_directory_or_none()
        if snapshot is None:
            raise ReferenceDataUnavailable(ReferenceDataSourceId.LOCATIONS_DIRECTORY)
        return snapshot

    @beartype
    def product_vitrine_or_none(self) -> ParsedProductCatalog | None:
        if self._product_vitrine is None:
            self._note_degraded(ReferenceDataSourceId.PRODUCT_VITRINE)
        return self._product_vitrine

    @beartype
    def product_vitrine(self) -> ParsedProductCatalog:
        vitrine = self.product_vitrine_or_none()
        if vitrine is None:
            raise ReferenceDataUnavailable(ReferenceDataSourceId.PRODUCT_VITRINE)
        return vitrine

    @beartype
    def product_catalog_or_none(self) -> ParsedMsProductCatalog | None:
        if self._ms_product_catalog is None:
            self._note_degraded(ReferenceDataSourceId.PRODUCT_CATALOG)
        return self._ms_product_catalog

    @beartype
    def product_catalog(self) -> ParsedMsProductCatalog:
        catalog = self.product_catalog_or_none()
        if catalog is None:
            raise ReferenceDataUnavailable(ReferenceDataSourceId.PRODUCT_CATALOG)
        return catalog

    @beartype
    def _note_degraded(self, source_id: ReferenceDataSourceId) -> None:
        if source_id in self._degraded_logged:
            return
        self._degraded_logged.add(source_id)
        _LOGGER.warning("reference_data_degraded", extra={"source_id": source_id.value})
