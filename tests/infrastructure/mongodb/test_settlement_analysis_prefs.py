from __future__ import annotations

from decimal import Decimal

import mongomock

from src.application.technician_settlement.analysis_prefs import SettlementAnalysisPrefs
from src.infrastructure.mongodb.settlement_analysis_prefs import (
    MongoSettlementAnalysisPrefsStore,
)


def test_mongo_prefs_round_trip() -> None:
    collection = mongomock.MongoClient().db.settlement_analysis_prefs
    store = MongoSettlementAnalysisPrefsStore.from_collection(collection)
    prefs = SettlementAnalysisPrefs(
        unit_prices={"COFFEE": Decimal("1.5"), "SUGAR": Decimal("0.10")},
        recoverable_product_codes=frozenset({"COFFEE"}),
        allowed_loss_pct=Decimal("2"),
    )

    store.save(telegram_user_id=7, prefs=prefs)
    got = store.get(7)

    assert got == prefs
    raw = collection.find_one({"_id": 7})
    assert raw is not None
    assert raw["telegram_user_id"] == 7
    assert raw["unit_prices"] == {"COFFEE": "1.5", "SUGAR": "0.10"}
    assert isinstance(raw["unit_prices"]["COFFEE"], str)
    assert set(raw["recoverable_product_codes"]) == {"COFFEE"}
    assert raw["allowed_loss_pct"] == "2"
    assert isinstance(raw["allowed_loss_pct"], str)
    assert "updated_at" in raw


def test_mongo_prefs_load_missing_returns_empty() -> None:
    collection = mongomock.MongoClient().db.settlement_analysis_prefs
    store = MongoSettlementAnalysisPrefsStore.from_collection(collection)
    prefs = store.get(telegram_user_id=99)
    assert prefs == SettlementAnalysisPrefs.empty()


def test_mongo_prefs_save_overwrite() -> None:
    collection = mongomock.MongoClient().db.settlement_analysis_prefs
    store = MongoSettlementAnalysisPrefsStore.from_collection(collection)
    store.save(
        telegram_user_id=7,
        prefs=SettlementAnalysisPrefs(
            unit_prices={"COFFEE": Decimal("1.5")},
            recoverable_product_codes=frozenset({"COFFEE"}),
            allowed_loss_pct=Decimal("2"),
        ),
    )
    store.save(
        telegram_user_id=7,
        prefs=SettlementAnalysisPrefs(
            unit_prices={"SUGAR": Decimal("0.1")},
            recoverable_product_codes=frozenset(),
            allowed_loss_pct=Decimal("1"),
        ),
    )
    got = store.get(7)
    assert got.unit_prices == {"SUGAR": Decimal("0.1")}
    assert got.recoverable_product_codes == frozenset()
    assert got.allowed_loss_pct == Decimal("1")
    assert collection.count_documents({}) == 1
