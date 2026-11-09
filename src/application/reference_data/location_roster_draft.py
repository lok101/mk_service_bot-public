from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.reference_data.location_roster import (
    LocationRosterConflict,
    LocationRosterEntry,
    LocationRosterPatch,
    SaveLocationRoster,
    _validate_patches,
)
from src.application.reference_data.location_roster_draft_compare import roster_draft_is_dirty
from src.application.reference_data.ports import LocationRosterDraftStore, LocationRosterStore
from src.domain.ids import MachineId, TechnicianId


def _roster_instants_equal(left: datetime, right: datetime) -> bool:
    """Compare optimistic tokens at BSON Date precision (milliseconds)."""
    return int(left.timestamp() * 1000) == int(right.timestamp() * 1000)


def _assert_draft_versions(
    draft: LocationRosterDraftStore,
    *,
    catalog_machine_ids: frozenset[MachineId],
    expected_draft_updated_at: Mapping[MachineId, datetime],
) -> None:
    for machine_id in catalog_machine_ids:
        entry = draft.get(machine_id)
        if entry is None:
            continue
        expected = expected_draft_updated_at.get(machine_id)
        if expected is None or not _roster_instants_equal(entry.updated_at, expected):
            raise LocationRosterConflict()


def _assert_applied_versions(
    applied: LocationRosterStore,
    *,
    catalog_machine_ids: frozenset[MachineId],
    expected_applied_updated_at: Mapping[MachineId, datetime],
) -> None:
    for machine_id in catalog_machine_ids:
        entry = applied.get(machine_id)
        if entry is None:
            continue
        expected = expected_applied_updated_at.get(machine_id)
        if expected is None or not _roster_instants_equal(entry.updated_at, expected):
            raise LocationRosterConflict()


def _patches_from_draft(
    draft: LocationRosterDraftStore,
    *,
    catalog_machine_ids: frozenset[MachineId],
) -> tuple[LocationRosterPatch, ...]:
    patches: list[LocationRosterPatch] = []
    for machine_id in catalog_machine_ids:
        entry = draft.get(machine_id)
        if entry is None:
            patches.append(
                LocationRosterPatch(
                    machine_id=machine_id,
                    technician_id=None,
                    service_weekdays=frozenset(),
                ),
            )
        else:
            patches.append(
                LocationRosterPatch(
                    machine_id=machine_id,
                    technician_id=entry.technician_id,
                    service_weekdays=entry.service_weekdays,
                ),
            )
    return tuple(patches)


@beartype
@dataclass(slots=True)
class BootstrapLocationRosterDraft:
    applied: LocationRosterStore
    draft: LocationRosterDraftStore

    @beartype
    def execute(
        self,
        *,
        catalog_machine_ids: frozenset[MachineId],
        now: datetime,
        actor_telegram_user_id: int,
    ) -> None:
        existing = {entry.machine_id: entry for entry in self.draft.list_all()}
        merged: list[LocationRosterEntry] = list(existing.values())
        for machine_id in catalog_machine_ids:
            if machine_id in existing:
                continue
            applied_entry = self.applied.get(machine_id)
            if applied_entry is not None:
                merged.append(applied_entry)
            else:
                merged.append(
                    LocationRosterEntry(
                        machine_id=machine_id,
                        technician_id=None,
                        service_weekdays=frozenset(),
                        updated_at=now,
                        updated_by_telegram_user_id=actor_telegram_user_id,
                    ),
                )
        self.draft.replace_all(tuple(merged))


@beartype
@dataclass(slots=True)
class UpsertLocationRosterDraft:
    draft: LocationRosterDraftStore

    @beartype
    def execute(
        self,
        patch: LocationRosterPatch,
        *,
        expected_updated_at: datetime | None,
        catalog_machine_ids: frozenset[MachineId],
        directory_technician_ids: frozenset[TechnicianId],
        actor_telegram_user_id: int,
        now: datetime,
    ) -> LocationRosterEntry:
        _validate_patches(
            (patch,),
            catalog_machine_ids=catalog_machine_ids,
            directory_technician_ids=directory_technician_ids,
        )
        entry = LocationRosterEntry(
            machine_id=patch.machine_id,
            technician_id=patch.technician_id,
            service_weekdays=patch.service_weekdays,
            updated_at=now,
            updated_by_telegram_user_id=actor_telegram_user_id,
        )
        return self.draft.upsert(entry, expected_updated_at=expected_updated_at)


@beartype
@dataclass(frozen=True, slots=True)
class ApplyLocationRosterDraftResult:
    applied: bool


@beartype
@dataclass(slots=True)
class ApplyLocationRosterDraft:
    draft: LocationRosterDraftStore
    applied: LocationRosterStore
    on_applied: Callable[[tuple[LocationRosterEntry, ...]], None]

    @beartype
    def execute(
        self,
        *,
        catalog_machine_ids: frozenset[MachineId],
        directory_technician_ids: frozenset[TechnicianId],
        expected_draft_updated_at: Mapping[MachineId, datetime],
        expected_applied_updated_at: Mapping[MachineId, datetime],
        actor_telegram_user_id: int,
        now: datetime,
    ) -> ApplyLocationRosterDraftResult:
        _assert_draft_versions(
            self.draft,
            catalog_machine_ids=catalog_machine_ids,
            expected_draft_updated_at=expected_draft_updated_at,
        )
        _assert_applied_versions(
            self.applied,
            catalog_machine_ids=catalog_machine_ids,
            expected_applied_updated_at=expected_applied_updated_at,
        )
        draft_entries = tuple(
            entry for entry in self.draft.list_all() if entry.machine_id in catalog_machine_ids
        )
        applied_entries = tuple(
            entry for entry in self.applied.list_all() if entry.machine_id in catalog_machine_ids
        )
        if not roster_draft_is_dirty(draft_entries, applied_entries, catalog_machine_ids):
            return ApplyLocationRosterDraftResult(applied=False)
        patches = _patches_from_draft(self.draft, catalog_machine_ids=catalog_machine_ids)
        SaveLocationRoster(store=self.applied).execute(
            patches,
            catalog_machine_ids=catalog_machine_ids,
            directory_technician_ids=directory_technician_ids,
            actor_telegram_user_id=actor_telegram_user_id,
            now=now,
        )
        saved_entries = tuple(
            LocationRosterEntry(
                machine_id=patch.machine_id,
                technician_id=patch.technician_id,
                service_weekdays=patch.service_weekdays,
                updated_at=now,
                updated_by_telegram_user_id=actor_telegram_user_id,
            )
            for patch in patches
        )
        self.on_applied(saved_entries)
        return ApplyLocationRosterDraftResult(applied=True)


@beartype
@dataclass(slots=True)
class ResetLocationRosterDraft:
    draft: LocationRosterDraftStore
    applied: LocationRosterStore

    @beartype
    def execute(
        self,
        *,
        catalog_machine_ids: frozenset[MachineId],
        expected_draft_updated_at: Mapping[MachineId, datetime],
        now: datetime,
        actor_telegram_user_id: int,
    ) -> None:
        _assert_draft_versions(
            self.draft,
            catalog_machine_ids=catalog_machine_ids,
            expected_draft_updated_at=expected_draft_updated_at,
        )
        entries: list[LocationRosterEntry] = []
        for machine_id in catalog_machine_ids:
            applied_entry = self.applied.get(machine_id)
            if applied_entry is not None:
                entries.append(
                    LocationRosterEntry(
                        machine_id=machine_id,
                        technician_id=applied_entry.technician_id,
                        service_weekdays=applied_entry.service_weekdays,
                        updated_at=now,
                        updated_by_telegram_user_id=actor_telegram_user_id,
                    ),
                )
            else:
                entries.append(
                    LocationRosterEntry(
                        machine_id=machine_id,
                        technician_id=None,
                        service_weekdays=frozenset(),
                        updated_at=now,
                        updated_by_telegram_user_id=actor_telegram_user_id,
                    ),
                )
        self.draft.replace_all(tuple(entries))
