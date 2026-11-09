from __future__ import annotations

from datetime import UTC, datetime

import mongomock

from src.domain.ids import MachineId, TechnicianId
from src.domain.technician_last_maintenance import TechnicianLastMaintenanceSnapshot
from src.infrastructure.machine_operations.technician_last_maintenance_mongo import (
    MongoTechnicianLastMaintenanceProjection,
)

_TECH = TechnicianId("tech-a")
_MACHINE_A = MachineId("vm-a")
_MACHINE_B = MachineId("vm-b")
_T0 = datetime(2026, 7, 2, 10, 0, tzinfo=UTC)
_T1 = datetime(2026, 7, 2, 11, 0, tzinfo=UTC)


def _store() -> MongoTechnicianLastMaintenanceProjection:
    collection = mongomock.MongoClient().db.technician_last_maintenance
    return MongoTechnicianLastMaintenanceProjection(_collection=collection)


def test_get_last_returns_none_when_empty() -> None:
    store = _store()
    assert store.get_last(_TECH) is None


def test_upsert_and_get_last() -> None:
    store = _store()
    snapshot = TechnicianLastMaintenanceSnapshot(
        technician_id=_TECH,
        machine_id=_MACHINE_A,
        completed_at=_T0,
    )
    store.upsert(snapshot)
    assert store.get_last(_TECH) == snapshot


def test_upsert_replaces_with_newer_completion() -> None:
    store = _store()
    store.upsert(
        TechnicianLastMaintenanceSnapshot(
            technician_id=_TECH,
            machine_id=_MACHINE_A,
            completed_at=_T0,
        ),
    )
    newer = TechnicianLastMaintenanceSnapshot(
        technician_id=_TECH,
        machine_id=_MACHINE_B,
        completed_at=_T1,
    )
    store.upsert(newer)
    assert store.get_last(_TECH) == newer


def test_upsert_skips_older_completion() -> None:
    store = _store()
    newer = TechnicianLastMaintenanceSnapshot(
        technician_id=_TECH,
        machine_id=_MACHINE_B,
        completed_at=_T1,
    )
    store.upsert(newer)
    store.upsert(
        TechnicianLastMaintenanceSnapshot(
            technician_id=_TECH,
            machine_id=_MACHINE_A,
            completed_at=_T0,
        ),
    )
    assert store.get_last(_TECH) == newer
