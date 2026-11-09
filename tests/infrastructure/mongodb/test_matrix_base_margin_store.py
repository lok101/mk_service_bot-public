from __future__ import annotations

from mongomock import MongoClient
from tests.application.matrix_automation.fixtures.curved_margin_params import curved_margin_params

from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.matrix_base_margin import MongoMatrixBaseMarginStore


def test_mongo_base_margin_round_trip() -> None:
    client: MongoClient = MongoClient()
    settings = MongoSettings(uri="mongodb://localhost", database="t")
    store = MongoMatrixBaseMarginStore.from_settings(settings, client=client)
    assert store.get() is None
    params = curved_margin_params(rounding_last_digits=frozenset({0, 5}))
    store.save(params)
    assert store.get() == params
    params_none = curved_margin_params(rounding_last_digits=None)
    store.save(params_none)
    assert store.get() == params_none
