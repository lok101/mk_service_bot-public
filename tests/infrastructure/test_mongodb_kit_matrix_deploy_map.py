from __future__ import annotations

from datetime import UTC, datetime

import mongomock

from src.infrastructure.mongodb.kit_matrix_deploy_map import MongoKitMatrixDeployMapStore


def test_mongo_kit_matrix_deploy_map_upsert_get() -> None:
    collection = mongomock.MongoClient().db.kit_matrix_deploy_map
    store = MongoKitMatrixDeployMapStore.from_collection(collection)
    applied_at = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    store.upsert(
        kit_matrix_id=42,
        logical_matrix_name="SnackA",
        machine_code="514",
        vending_machine_id=7,
        kit_matrix_name="SnackA_514_2026-07-27",
        applied_at=applied_at,
    )
    row = store.get(42)
    assert row is not None
    assert row.machine_code == "514"
    assert row.logical_matrix_name == "SnackA"
    assert row.vending_machine_id == 7
    assert row.kit_matrix_name == "SnackA_514_2026-07-27"
    assert row.applied_at is not None
    assert row.applied_at.replace(tzinfo=UTC) == applied_at
