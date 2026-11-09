from __future__ import annotations

from beartype import beartype

from src.application.reference_data.location_roster import LocationRosterEntry
from src.domain.ids import MachineId


@beartype
def roster_draft_is_dirty(
    draft: tuple[LocationRosterEntry, ...],
    applied: tuple[LocationRosterEntry, ...],
    catalog_machine_ids: frozenset[MachineId],
) -> bool:
    draft_by = {e.machine_id: e for e in draft if e.machine_id in catalog_machine_ids}
    applied_by = {e.machine_id: e for e in applied if e.machine_id in catalog_machine_ids}
    for machine_id in catalog_machine_ids:
        d = draft_by.get(machine_id)
        a = applied_by.get(machine_id)
        d_tech = None if d is None else d.technician_id
        a_tech = None if a is None else a.technician_id
        d_days = frozenset() if d is None else d.service_weekdays
        a_days = frozenset() if a is None else a.service_weekdays
        if d_tech != a_tech or d_days != a_days:
            return True
    return False
