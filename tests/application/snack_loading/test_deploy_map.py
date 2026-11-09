from __future__ import annotations

from src.infrastructure.testing.snack_loading_fakes import InMemoryKitMatrixDeployMapStore


def test_deploy_map_upsert_after_apply() -> None:
    store = InMemoryKitMatrixDeployMapStore()
    store.upsert(
        kit_matrix_id=42,
        logical_matrix_name="SnackA",
        machine_code="514",
        vending_machine_id=7,
        kit_matrix_name="SnackA_514_2026-07-27",
    )
    row = store.get(42)
    assert row is not None
    assert row.logical_matrix_name == "SnackA"
    assert row.machine_code == "514"


def test_deploy_map_miss_returns_none() -> None:
    store = InMemoryKitMatrixDeployMapStore()
    assert store.get(999) is None
