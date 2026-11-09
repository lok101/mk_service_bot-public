from __future__ import annotations

from tests.application.matrix_automation.fixtures.curved_margin_params import curved_margin_params

from src.application.matrix_automation.base_margin_store_memory import InMemoryMatrixBaseMarginStore


def test_memory_base_margin_round_trip() -> None:
    store = InMemoryMatrixBaseMarginStore()
    assert store.get() is None
    params = curved_margin_params(rounding_last_digits=frozenset({0, 5}))
    store.save(params)
    assert store.get() == params
