from __future__ import annotations

from datetime import UTC, datetime

from src.application.reference_data.migrate_coffee_locations import (
    migrate_technician_locations_to_coffee,
)
from src.application.reference_data.models import (
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
    compute_content_hash,
)
from src.infrastructure.reference_data.memory_store import InMemoryReferenceDataSnapshotStore

_LEGACY_ID = "technician_locations"
_NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
_HEADER = ("id локации", "имя локации", "имя техника", "id техника")
_COFFEE_ROW = ("129", "Cafe", "Tech", "T1")


def _legacy_snap(rows: tuple[tuple[str, ...], ...]) -> ReferenceDataSnapshot:
    return ReferenceDataSnapshot(
        source_id=ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        rows=rows,
        content_hash=compute_content_hash(rows),
        last_fetched_at=_NOW,
        content_updated_at=_NOW,
    )


def test_migrate_technician_locations_to_coffee_clears_legacy() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    store.put_by_id(_LEGACY_ID, _legacy_snap((_HEADER, _COFFEE_ROW)))

    migrate_technician_locations_to_coffee(store)

    coffee = store.get(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS)
    assert coffee is not None
    assert coffee.rows
    assert store.get_by_id(_LEGACY_ID) is None


def test_migrate_skips_when_coffee_exists() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    coffee_rows = (_HEADER, ("129", "Keep", "Tech", "T1"))
    store.put(
        ReferenceDataSnapshot(
            source_id=ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
            rows=coffee_rows,
            content_hash=compute_content_hash(coffee_rows),
            last_fetched_at=_NOW,
            content_updated_at=_NOW,
        ),
    )
    store.put_by_id(_LEGACY_ID, _legacy_snap((_HEADER, ("130", "Legacy", "Tech", "T1"))))

    migrate_technician_locations_to_coffee(store)

    coffee = store.get(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS)
    assert coffee is not None
    assert coffee.rows[1][0] == "129"
    assert store.get_by_id(_LEGACY_ID) is not None


def test_migrate_noop_when_no_legacy() -> None:
    store = InMemoryReferenceDataSnapshotStore()

    migrate_technician_locations_to_coffee(store)

    assert store.get(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS) is None
    assert store.get_by_id(_LEGACY_ID) is None


def test_migrate_replaces_empty_coffee_from_legacy() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    empty: tuple[tuple[str, ...], ...] = ()
    store.put(
        ReferenceDataSnapshot(
            source_id=ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
            rows=empty,
            content_hash=compute_content_hash(empty),
            last_fetched_at=_NOW,
            content_updated_at=_NOW,
        ),
    )
    store.put_by_id(_LEGACY_ID, _legacy_snap((_HEADER, _COFFEE_ROW)))

    migrate_technician_locations_to_coffee(store)

    coffee = store.get(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS)
    assert coffee is not None
    assert coffee.rows[1][0] == "129"
    assert store.get_by_id(_LEGACY_ID) is None
