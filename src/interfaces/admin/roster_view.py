from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.application.reference_data import ReferenceDataProvider, roster_draft_is_dirty
from src.application.reference_data.ports import LocationRosterDraftStore, LocationRosterStore
from src.application.sheets import (
    LocationPlacement,
    LocationsDirectorySnapshot,
    list_all_machines_from_snapshot,
)
from src.domain.ids import TechnicianId


@beartype
@dataclass(frozen=True, slots=True)
class RosterRowView:
    machine_id: str
    location_name: str
    technician_id: str
    weekdays: frozenset[int]
    latitude: str | None
    longitude: str | None
    updated_at: str
    applied_updated_at: str
    applied_technician_id: str
    applied_weekdays: frozenset[int]


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianOptionView:
    id: str
    name: str


@beartype
@dataclass(frozen=True, slots=True)
class RosterViewModel:
    rows: tuple[RosterRowView, ...]
    technicians: tuple[TechnicianOptionView, ...]
    map_coordinates_available: bool
    draft_dirty: bool


@beartype
def _format_coord(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


@beartype
def _current_placement_for_machine(
    directory: LocationsDirectorySnapshot,
    machine_id: str,
) -> LocationPlacement | None:
    """Open placement (removed_on is None), else latest by installed_on.

    Do not use list order: master-data hydrate/`list_all` may order by UUID.
    """
    candidates = [
        placement for placement in directory.placements if placement.machine_id.value == machine_id
    ]
    if not candidates:
        return None
    open_placements = [placement for placement in candidates if placement.removed_on is None]
    pool = open_placements if open_placements else candidates
    return max(pool, key=lambda placement: placement.installed_on)


@beartype
def _coords_from_current_placement(
    directory: LocationsDirectorySnapshot | None,
    machine_id: str,
) -> tuple[str | None, str | None]:
    if directory is None:
        return None, None
    current = _current_placement_for_machine(directory, machine_id)
    if current is None:
        return None, None
    if current.latitude is None or current.longitude is None:
        return None, None
    return _format_coord(current.latitude), _format_coord(current.longitude)


@beartype
def build_roster_view_model(
    provider: ReferenceDataProvider,
    *,
    draft_store: LocationRosterDraftStore,
    applied_store: LocationRosterStore,
    active_technician_ids: frozenset[TechnicianId] | None = None,
) -> RosterViewModel:
    catalog = provider.locations_catalog()
    directory = provider.technicians_directory()
    directory_snapshot = provider.locations_directory_or_none()
    catalog_ids = frozenset(machine.id for machine in list_all_machines_from_snapshot(catalog))
    draft_entries = tuple(
        entry for entry in draft_store.list_all() if entry.machine_id in catalog_ids
    )
    applied_entries = tuple(
        entry for entry in applied_store.list_all() if entry.machine_id in catalog_ids
    )
    draft_by_id = {entry.machine_id: entry for entry in draft_entries}
    applied_by_id = {entry.machine_id: entry for entry in applied_entries}
    rows: list[RosterRowView] = []
    for machine in list_all_machines_from_snapshot(catalog):
        entry = draft_by_id.get(machine.id)
        applied_entry = applied_by_id.get(machine.id)
        if entry is None:
            technician_id = ""
            weekdays: frozenset[int] = frozenset()
            updated_at = ""
        else:
            technician_id = "" if entry.technician_id is None else entry.technician_id.value
            weekdays = entry.service_weekdays
            updated_at = entry.updated_at.isoformat()
        if applied_entry is None:
            applied_technician_id = ""
            applied_weekdays: frozenset[int] = frozenset()
            applied_updated_at = ""
        else:
            applied_technician_id = (
                "" if applied_entry.technician_id is None else applied_entry.technician_id.value
            )
            applied_weekdays = applied_entry.service_weekdays
            applied_updated_at = applied_entry.updated_at.isoformat()
        lat, lng = _coords_from_current_placement(directory_snapshot, machine.id.value)
        rows.append(
            RosterRowView(
                machine_id=machine.id.value,
                location_name=machine.name,
                technician_id=technician_id,
                weekdays=weekdays,
                latitude=lat,
                longitude=lng,
                updated_at=updated_at,
                applied_updated_at=applied_updated_at,
                applied_technician_id=applied_technician_id,
                applied_weekdays=applied_weekdays,
            ),
        )
    rows.sort(key=lambda row: 0 if not row.technician_id else 1)
    users = provider.system_users()
    lok51_technician_ids = {
        user.technician_id
        for user in users.users_by_telegram_id.values()
        if user.is_active and user.technician_id is not None
    }
    current_assigned = {TechnicianId(row.technician_id) for row in rows if row.technician_id}
    allowed = lok51_technician_ids | current_assigned
    if active_technician_ids is not None:
        allowed = {
            technician_id
            for technician_id in allowed
            if technician_id in active_technician_ids or technician_id in current_assigned
        }
    technicians = tuple(
        TechnicianOptionView(id=technician_id.value, name=name)
        for technician_id, name in sorted(
            directory.names_by_id.items(),
            key=lambda item: item[0].value,
        )
        if technician_id in allowed
    )
    return RosterViewModel(
        rows=tuple(rows),
        technicians=technicians,
        map_coordinates_available=directory_snapshot is not None,
        draft_dirty=roster_draft_is_dirty(draft_entries, applied_entries, catalog_ids),
    )
