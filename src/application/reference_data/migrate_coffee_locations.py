from __future__ import annotations

from beartype import beartype

from src.application.reference_data.models import (
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
)
from src.application.reference_data.ports import ReferenceDataSnapshotStore

_LEGACY_TECHNICIAN_LOCATIONS_ID = "technician_locations"


@beartype
def migrate_technician_locations_to_coffee(store: ReferenceDataSnapshotStore) -> None:
    existing = store.get(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS)
    if existing is not None and existing.rows:
        return
    legacy = store.get_by_id(_LEGACY_TECHNICIAN_LOCATIONS_ID)
    if legacy is None or not legacy.rows:
        return
    store.put(
        ReferenceDataSnapshot(
            source_id=ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
            rows=legacy.rows,
            content_hash=legacy.content_hash,
            last_fetched_at=legacy.last_fetched_at,
            content_updated_at=legacy.content_updated_at,
            last_sync_error=legacy.last_sync_error,
        ),
    )
    store.delete_by_id(_LEGACY_TECHNICIAN_LOCATIONS_ID)
