from __future__ import annotations

from datetime import UTC, datetime

from src.application.reference_data.models import (
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
)
from src.application.reference_data.provider import ReferenceDataProvider
from src.application.reference_data.sync import SyncReferenceData
from src.application.sheets import SystemUsersSnapshot
from src.domain.system_user import BotRole, CompanyRole, SystemUser, SystemUserId
from src.infrastructure.composition.factories import warm_up_reference_data_provider
from src.infrastructure.reference_data.memory_store import (
    InMemoryReferenceDataSnapshotStore,
)

_SID = ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS
_HEADER = ["id локации", "имя локации", "имя техника", "id техника"]
_ROW = ["129", "Локация 1", "Иван", "tech-1"]
_NOW = datetime(2026, 7, 1, tzinfo=UTC)


class _FailingReader:
    def read_rows(self, source_id):
        raise RuntimeError("sheets down")


def test_warm_up_hydrates_from_store_without_sync_when_lkg_present() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    store.put(
        ReferenceDataSnapshot(
            source_id=_SID,
            rows=(tuple(_HEADER), tuple(_ROW)),
            content_hash="sha256:x",
            last_fetched_at=_NOW,
            content_updated_at=_NOW,
        )
    )
    provider = ReferenceDataProvider()
    sync = SyncReferenceData(
        reader=_FailingReader(),
        store=store,
        provider=provider,
        source_ids=(_SID,),
    )
    warm_up_reference_data_provider(provider=provider, store=store, sync=sync)
    assert provider.coffee_locations_or_none() is not None


_BOT_USERS_HEADER = [
    "is active",
    "id",
    "имя",
    "роль",
    "телеграм id",
    "id техника",
]
_BOT_USERS_ROW = ["да", "u1", "Sheet User", "техник", "424242424", "t1"]


def test_hydrate_from_store_skips_bot_users_when_requested() -> None:
    mongo_user = SystemUser(
        user_id=SystemUserId("mongo-1"),
        name="Mongo User",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=1001,
        technician_id=None,
        company_roles=frozenset({CompanyRole.SERVICE_OPERATIONS_COORDINATOR}),
    )
    provider = ReferenceDataProvider()
    provider.apply_system_users_snapshot(
        SystemUsersSnapshot(
            users_by_telegram_id={1001: mongo_user},
            users_by_technician_id={},
        ),
    )
    store = InMemoryReferenceDataSnapshotStore()
    store.put(
        ReferenceDataSnapshot(
            source_id=ReferenceDataSourceId.BOT_USERS,
            rows=(tuple(_BOT_USERS_HEADER), tuple(_BOT_USERS_ROW)),
            content_hash="sha256:bot-users",
            last_fetched_at=_NOW,
            content_updated_at=_NOW,
        ),
    )
    provider.hydrate_from_store(
        store,
        skip_source_ids=frozenset({ReferenceDataSourceId.BOT_USERS}),
    )
    snapshot = provider.system_users_or_none()
    assert snapshot is not None
    assert snapshot.users_by_telegram_id[1001].name == "Mongo User"
    assert 424242424 not in snapshot.users_by_telegram_id
