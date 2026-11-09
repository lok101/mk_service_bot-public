from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from src.application.master_data import InMemoryMasterDataStores
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.reference_data.provider import ReferenceDataProvider
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.infrastructure.reference_data.master_data_sheets_export import (
    FailingMasterDataExport,
    RecordingMasterDataExport,
)
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import _export_mirror_after_roster

_FROZEN_NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


def _deps(
    *,
    master_stores: InMemoryMasterDataStores | None,
    export_hook: object | None,
) -> AdminHttpDeps:
    return AdminHttpDeps(
        provider=ReferenceDataProvider(),
        roster_store=InMemoryLocationRosterStore(),
        roster_draft_store=InMemoryLocationRosterDraftStore(),
        visit_store=InMemoryServiceVisitStore(),
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        bot_token="test-bot-token",
        session_secret="admin-session-secret",
        session_ttl_seconds=86400,
        telegram_auth_max_age_seconds=86400,
        telegram_bot_username="mk_bot",
        stub_login_enabled=True,
        timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
        now_factory=lambda: _FROZEN_NOW,
        master_stores=master_stores,
        master_data_export_hook=export_hook,  # type: ignore[arg-type]
    )


def test_roster_save_triggers_mirror_export() -> None:
    stores = InMemoryMasterDataStores()
    recording = RecordingMasterDataExport()
    _export_mirror_after_roster(_deps(master_stores=stores, export_hook=recording))
    assert recording.calls == [stores]


def test_roster_save_keeps_on_export_fail() -> None:
    stores = InMemoryMasterDataStores()
    _export_mirror_after_roster(
        _deps(master_stores=stores, export_hook=FailingMasterDataExport()),
    )
    assert stores.locations.is_empty() is True
