from __future__ import annotations

from datetime import UTC, datetime

import mongomock

from src.application.master_data import InMemorySystemUserStore, SystemUserRecord
from src.domain.system_user import AdminPanel, BotRole, CompanyRole, SystemUser, SystemUserId
from src.infrastructure.composition.factories.system_users import grant_planogram_panel_if_mongo
from src.infrastructure.mongodb.system_users import MongoSystemUserStore

_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def test_grant_planogram_panel_if_mongo_skips_memory_store() -> None:
    memory = InMemorySystemUserStore()
    memory.replace_all(
        (
            SystemUserRecord(
                user=SystemUser(
                    user_id=SystemUserId("1"),
                    name="A",
                    role=BotRole.ADMINISTRATOR,
                    is_active=True,
                    telegram_user_id=42,
                    technician_id=None,
                    company_roles=frozenset({CompanyRole.SERVICE_OPERATIONS_COORDINATOR}),
                ),
                updated_at=_NOW,
                updated_by_telegram_user_id=1,
            ),
        )
    )
    grant_planogram_panel_if_mongo(memory)
    loaded = memory.get(42)
    assert loaded is not None
    # Grant is a no-op on memory; planograms already comes from coordinator role map (OM).
    assert loaded.user.company_roles == frozenset({CompanyRole.SERVICE_OPERATIONS_COORDINATOR})
    assert AdminPanel.MICROMARKET_PLANOGRAMS in loaded.user.panels


def test_grant_planogram_panel_if_mongo_runs_on_mongo_store() -> None:
    client = mongomock.MongoClient()
    db = client["test"]
    store = MongoSystemUserStore(
        users_collection=db["master_system_users"],
        audit_collection=db["master_data_audit"],
    )
    # Legacy panels document: backfill still mutates panels SoT before roles cutover.
    store.users_collection.insert_one(
        {
            "_id": 42,
            "user_id": "1",
            "name": "A",
            "is_active": True,
            "bot_role": "administrator",
            "technician_id": None,
            "panels": ["master_data", "roster", "visit_board"],
            "updated_at": _NOW,
            "updated_by_telegram_user_id": 1,
        }
    )
    grant_planogram_panel_if_mongo(store)
    raw = store.users_collection.find_one({"_id": 42})
    assert raw is not None
    assert "micromarket_planograms" in raw["panels"]
