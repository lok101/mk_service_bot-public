from __future__ import annotations

from datetime import UTC, datetime

import mongomock
import pytest
from bson.int64 import Int64

from src.application.master_data import SystemUserRecord
from src.domain.system_user import (
    AdminPanel,
    BotRole,
    CompanyRole,
    SystemUser,
    SystemUserId,
)
from src.infrastructure.mongodb.system_users import MongoSystemUserStore

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def test_mongo_system_users_roundtrip() -> None:
    client = mongomock.MongoClient()
    db = client["test"]
    store = MongoSystemUserStore(
        users_collection=db["master_system_users"],
        audit_collection=db["master_data_audit"],
    )
    user = SystemUser(
        user_id=SystemUserId("1"),
        name="A",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=42,
        technician_id=None,
        company_roles=frozenset({CompanyRole.ACCESS_ADMINISTRATOR}),
    )
    store.replace_all(
        (
            SystemUserRecord(
                user=user,
                updated_at=_NOW,
                updated_by_telegram_user_id=1,
            ),
        )
    )
    loaded = store.get(42)
    assert loaded is not None
    assert loaded.user.name == "A"
    assert CompanyRole.ACCESS_ADMINISTRATOR in loaded.user.company_roles
    assert AdminPanel.USERS in loaded.user.panels
    raw = store.users_collection.find_one({"_id": 42})
    assert raw is not None
    assert "panels" not in raw
    assert raw["company_roles"] == ["access_administrator"]


def _store() -> MongoSystemUserStore:
    client = mongomock.MongoClient()
    db = client["test"]
    return MongoSystemUserStore(
        users_collection=db["master_system_users"],
        audit_collection=db["master_data_audit"],
    )


def _user(
    company_roles: frozenset[CompanyRole],
    telegram_user_id: int = 42,
) -> SystemUser:
    return SystemUser(
        user_id=SystemUserId(str(telegram_user_id)),
        name="A",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=telegram_user_id,
        technician_id=None,
        company_roles=company_roles,
    )


def _record(user: SystemUser) -> SystemUserRecord:
    return SystemUserRecord(user=user, updated_at=_NOW, updated_by_telegram_user_id=1)


_BACKFILL_ID = "planogram-panel-backfill"


def test_list_all_and_is_empty_ignore_backfill_marker() -> None:
    store = _store()
    store.users_collection.insert_one({"_id": _BACKFILL_ID})
    assert store.list_all() == ()
    assert store.is_empty() is True


def test_grant_planogram_panel_once_adds_then_keeps_unchecked() -> None:
    store = _store()
    store.users_collection.insert_one(
        {
            "_id": 42,
            "user_id": "42",
            "name": "A",
            "is_active": True,
            "bot_role": "administrator",
            "technician_id": None,
            "panels": ["master_data", "users"],
            "updated_at": _NOW,
            "updated_by_telegram_user_id": 1,
        }
    )
    store.users_collection.insert_one(
        {
            "_id": 9,
            "user_id": "9",
            "name": "B",
            "is_active": True,
            "bot_role": "administrator",
            "technician_id": None,
            "panels": ["users"],
            "updated_at": _NOW,
            "updated_by_telegram_user_id": 1,
        }
    )
    store.users_collection.insert_one(
        {
            "_id": 7,
            "user_id": "7",
            "name": "C",
            "is_active": True,
            "bot_role": "administrator",
            "technician_id": None,
            "panels": ["master_data", "micromarket_planograms"],
            "updated_at": _NOW,
            "updated_by_telegram_user_id": 1,
        }
    )
    store.grant_planogram_panel_once()
    keeper_doc = store.users_collection.find_one({"_id": 42})
    assert keeper_doc is not None
    assert "micromarket_planograms" in keeper_doc["panels"]
    outsider_doc = store.users_collection.find_one({"_id": 9})
    assert outsider_doc is not None
    assert "micromarket_planograms" not in outsider_doc["panels"]
    assert store.users_collection.find_one({"_id": _BACKFILL_ID}) is not None
    store.users_collection.replace_one(
        {"_id": 11},
        {
            "_id": 11,
            "user_id": "11",
            "name": "C",
            "is_active": True,
            "bot_role": "administrator",
            "technician_id": None,
            "panels": ["master_data"],
            "updated_at": _NOW,
            "updated_by_telegram_user_id": 1,
        },
        upsert=True,
    )
    panels = [p for p in keeper_doc["panels"] if p != "micromarket_planograms"]
    store.users_collection.update_one({"_id": 42}, {"$set": {"panels": sorted(panels)}})
    store.grant_planogram_panel_once()
    again_doc = store.users_collection.find_one({"_id": 42})
    assert again_doc is not None
    assert "micromarket_planograms" not in again_doc["panels"]
    created_after_doc = store.users_collection.find_one({"_id": 11})
    assert created_after_doc is not None
    assert "micromarket_planograms" not in created_after_doc["panels"]


def test_replace_all_keeps_backfill_marker() -> None:
    store = _store()
    store.users_collection.insert_one({"_id": _BACKFILL_ID})
    store.replace_all(())
    assert store.users_collection.find_one({"_id": _BACKFILL_ID}) is not None
    assert store.is_empty() is True


def test_list_all_loads_bson_int64_telegram_user_id() -> None:
    store = _store()
    telegram_user_id = 7_089_874_822
    store.users_collection.insert_one(
        {
            "_id": Int64(telegram_user_id),
            "user_id": "alex",
            "name": "Alexander",
            "is_active": True,
            "bot_role": BotRole.ADMINISTRATOR.value,
            "technician_id": None,
            "panels": ["roster"],
            "updated_at": _NOW,
            "updated_by_telegram_user_id": Int64(709195127),
        },
    )
    records = store.list_all()
    assert len(records) == 1
    assert records[0].user.telegram_user_id == telegram_user_id
    assert store.get(telegram_user_id) is not None


def test_on_read_legacy_users_panels_become_access_administrator() -> None:
    store = _store()
    store.users_collection.insert_one(
        {
            "_id": 42,
            "user_id": "1",
            "name": "A",
            "is_active": True,
            "bot_role": "administrator",
            "technician_id": None,
            "panels": ["users"],
            "updated_at": _NOW,
            "updated_by_telegram_user_id": 1,
        }
    )
    loaded = store.get(42)
    assert loaded is not None
    assert loaded.user.company_roles == frozenset({CompanyRole.ACCESS_ADMINISTRATOR})


def test_on_read_legacy_settlement_panels_become_settlement_operator() -> None:
    store = _store()
    store.users_collection.insert_one(
        {
            "_id": 42,
            "user_id": "1",
            "name": "A",
            "is_active": True,
            "bot_role": "none",
            "technician_id": None,
            "panels": ["settlement_analysis"],
            "updated_at": _NOW,
            "updated_by_telegram_user_id": 1,
        }
    )
    loaded = store.get(42)
    assert loaded is not None
    assert loaded.user.company_roles == frozenset({CompanyRole.SETTLEMENT_OPERATOR})


def test_on_read_unknown_company_role_rejects() -> None:
    store = _store()
    store.users_collection.insert_one(
        {
            "_id": 42,
            "user_id": "1",
            "name": "A",
            "is_active": True,
            "bot_role": "none",
            "technician_id": None,
            "company_roles": ["not_a_real_role"],
            "updated_at": _NOW,
            "updated_by_telegram_user_id": 1,
        }
    )
    with pytest.raises(ValueError, match="unknown company role"):
        store.get(42)
