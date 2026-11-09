from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.reference_data.locations_merge import (
    assert_locations_merge_compatible,
    merge_locations_catalog,
)
from src.application.reference_data.ports import LocationRosterStore
from src.application.sheets import (
    TechnicianLocationsSnapshot,
    build_technician_locations_snapshot,
    find_technician_id_for_machine_in_snapshot,
    list_all_machines_from_snapshot,
)
from src.domain.ids import MachineId, TechnicianId

_ALLOWED_WEEKDAYS = frozenset(range(7))
_SYSTEM_ACTOR_TELEGRAM_USER_ID = 0
_LOGGER = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class LocationRosterEntry:
    machine_id: MachineId
    technician_id: TechnicianId | None
    service_weekdays: frozenset[int]
    updated_at: datetime
    updated_by_telegram_user_id: int


@beartype
@dataclass(frozen=True, slots=True)
class LocationRosterAuditRecord:
    at: datetime
    actor_telegram_user_id: int
    machine_id: MachineId
    before: LocationRosterEntry | None
    after: LocationRosterEntry


@beartype
@dataclass(frozen=True, slots=True)
class LocationRosterPatch:
    machine_id: MachineId
    technician_id: TechnicianId | None
    service_weekdays: frozenset[int]


class LocationRosterInvalid(Exception):
    @beartype
    def __init__(self, message: str) -> None:
        super().__init__(message)


class LocationRosterConflict(Exception):
    @beartype
    def __init__(self, message: str = "location roster conflict") -> None:
        super().__init__(message)


@beartype
@dataclass(slots=True)
class SaveLocationRoster:
    store: LocationRosterStore

    @beartype
    def execute(
        self,
        patches: tuple[LocationRosterPatch, ...],
        *,
        catalog_machine_ids: frozenset[MachineId],
        directory_technician_ids: frozenset[TechnicianId],
        actor_telegram_user_id: int,
        now: datetime,
    ) -> None:
        _validate_patches(
            patches,
            catalog_machine_ids=catalog_machine_ids,
            directory_technician_ids=directory_technician_ids,
        )
        last_by_machine: dict[MachineId, LocationRosterPatch] = {}
        for patch in patches:
            last_by_machine[patch.machine_id] = patch
        entries = tuple(
            LocationRosterEntry(
                machine_id=patch.machine_id,
                technician_id=patch.technician_id,
                service_weekdays=patch.service_weekdays,
                updated_at=now,
                updated_by_telegram_user_id=actor_telegram_user_id,
            )
            for patch in last_by_machine.values()
        )
        self.store.save_batch(
            entries,
            actor_telegram_user_id=actor_telegram_user_id,
            at=now,
        )


@beartype
def _validate_patches(
    patches: tuple[LocationRosterPatch, ...],
    *,
    catalog_machine_ids: frozenset[MachineId],
    directory_technician_ids: frozenset[TechnicianId],
) -> None:
    for patch in patches:
        if patch.machine_id not in catalog_machine_ids:
            raise LocationRosterInvalid(f"Unknown machine {patch.machine_id.value!r}")
        if patch.technician_id is not None and patch.technician_id not in directory_technician_ids:
            raise LocationRosterInvalid(f"Unknown technician {patch.technician_id.value!r}")
        if not patch.service_weekdays <= _ALLOWED_WEEKDAYS:
            raise LocationRosterInvalid(
                f"Invalid weekday in {sorted(patch.service_weekdays - _ALLOWED_WEEKDAYS)}",
            )


@beartype
@dataclass(slots=True)
class ImportLocationRosterFromSheets:
    store: LocationRosterStore

    @beartype
    def execute(
        self,
        *,
        coffee_rows: list[list[str]],
        snack_rows: list[list[str]] | None,
        catalog_machine_count: int,
        now: datetime,
    ) -> None:
        if not self.store.is_empty():
            return
        try:
            snapshot = _snapshot_from_location_rows(coffee_rows, snack_rows)
        except ValueError as exc:
            _LOGGER.error(
                "location_roster_import",
                extra={"catalog_machine_count": catalog_machine_count, "error": str(exc)},
            )
            return
        entries = _entries_from_snapshot(snapshot, now)
        if not entries:
            if catalog_machine_count > 0:
                _LOGGER.error(
                    "location_roster_import",
                    extra={"catalog_machine_count": catalog_machine_count, "imported": 0},
                )
            return
        self.store.replace_all(entries)
        _LOGGER.info(
            "location_roster_import",
            extra={"imported": len(entries), "catalog_machine_count": catalog_machine_count},
        )


@beartype
def _snapshot_from_location_rows(
    coffee_rows: list[list[str]],
    snack_rows: list[list[str]] | None,
) -> TechnicianLocationsSnapshot:
    coffee = build_technician_locations_snapshot(coffee_rows)
    if snack_rows is None:
        return coffee
    snack = build_technician_locations_snapshot(snack_rows)
    assert_locations_merge_compatible(coffee, snack)
    merged = merge_locations_catalog(coffee, snack)
    if merged is None:
        raise ValueError("location roster import produced empty catalog")
    return merged


@beartype
def _entries_from_snapshot(
    snapshot: TechnicianLocationsSnapshot,
    now: datetime,
) -> tuple[LocationRosterEntry, ...]:
    return tuple(
        LocationRosterEntry(
            machine_id=machine.id,
            technician_id=find_technician_id_for_machine_in_snapshot(snapshot, machine.id),
            service_weekdays=machine.service_weekdays,
            updated_at=now,
            updated_by_telegram_user_id=_SYSTEM_ACTOR_TELEGRAM_USER_ID,
        )
        for machine in list_all_machines_from_snapshot(snapshot)
    )
