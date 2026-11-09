from __future__ import annotations

from datetime import datetime

from beartype import beartype

from src.application.reference_data.location_roster import LocationRosterEntry
from src.application.reference_data.ports import LocationRosterDraftStore, LocationRosterStore
from src.domain.ids import MachineId


@beartype
def clear_location_roster_technician(
    machine_id: MachineId,
    *,
    applied: LocationRosterStore,
    draft: LocationRosterDraftStore,
    actor_telegram_user_id: int,
    now: datetime,
) -> None:
    """Clear technician assignment; keep service_weekdays. No-op if already unassigned."""
    applied_entry = applied.get(machine_id)
    if applied_entry is not None and applied_entry.technician_id is not None:
        applied.save_batch(
            (
                LocationRosterEntry(
                    machine_id=machine_id,
                    technician_id=None,
                    service_weekdays=applied_entry.service_weekdays,
                    updated_at=now,
                    updated_by_telegram_user_id=actor_telegram_user_id,
                ),
            ),
            actor_telegram_user_id=actor_telegram_user_id,
            at=now,
        )
    draft_entry = draft.get(machine_id)
    if draft_entry is not None and draft_entry.technician_id is not None:
        draft.upsert(
            LocationRosterEntry(
                machine_id=machine_id,
                technician_id=None,
                service_weekdays=draft_entry.service_weekdays,
                updated_at=now,
                updated_by_telegram_user_id=actor_telegram_user_id,
            ),
            expected_updated_at=draft_entry.updated_at,
        )
