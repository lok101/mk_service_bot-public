from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo.database import Database

from src.application.master_data import (
    InMemoryMasterDataCounterStore,
    SaveSystemUsers,
    SystemUserRecord,
    hydrate_provider_from_system_users,
)
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.technician_settlement import (
    AggregateSettlementClusters,
    BuildPeriodAnalysisView,
    BuildSessionAnalysisView,
    BuildSettlementAnalysisTree,
    InMemorySettlementAnalysisPrefsStore,
)
from src.domain.system_user import BotRole, CompanyRole, SystemUser, SystemUserId
from src.infrastructure.mongodb.system_users import MongoSystemUserStore
from src.infrastructure.testing.settlement_fakes import (
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
)
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes

pytestmark = pytest.mark.integration

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_OPS_TG = 1002
_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _build_admin_app(
    *,
    provider: ReferenceDataProvider,
    system_user_store: MongoSystemUserStore,
    users_enabled: bool,
    stub: bool,
    settlement_analysis_enabled: bool = False,
) -> tuple[FastAPI, AdminHttpDeps]:
    roster_store = InMemoryLocationRosterStore()
    provider.configure_roster(enabled=True, store=roster_store)
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["t1", "Tech"]],
    )
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника"],
            ["101", "Школа", "Tech", "t1"],
        ],
    )
    counters = InMemoryMasterDataCounterStore()
    analysis_tree = None
    analysis_aggregate = None
    analysis_session = None
    analysis_period = None
    analysis_prefs = None
    if settlement_analysis_enabled:
        events = InMemoryTechnicianSettlementEventStore()
        periods = InMemoryPeriodReconciliationRepository()
        analysis_tree = BuildSettlementAnalysisTree(
            event_store=events,
            period_repository=periods,
        )
        analysis_aggregate = AggregateSettlementClusters(
            event_store=events,
            period_repository=periods,
        )
        analysis_session = BuildSessionAnalysisView(event_store=events)
        analysis_period = BuildPeriodAnalysisView(period_repository=periods)
        analysis_prefs = InMemorySettlementAnalysisPrefsStore()
    deps = AdminHttpDeps(
        provider=provider,
        roster_store=roster_store,
        roster_draft_store=InMemoryLocationRosterDraftStore(),
        visit_store=InMemoryServiceVisitStore(),
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        bot_token=_BOT_TOKEN,
        session_secret=_SESSION_SECRET,
        session_ttl_seconds=86400,
        telegram_auth_max_age_seconds=86400,
        telegram_bot_username="mk_bot",
        stub_login_enabled=stub,
        timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
        now_factory=lambda: _NOW,
        users_enabled=users_enabled,
        system_user_store=system_user_store,
        save_system_users=SaveSystemUsers(store=system_user_store, counters=counters),
        settlement_analysis_enabled=settlement_analysis_enabled,
        build_settlement_analysis_tree=analysis_tree,
        aggregate_settlement_clusters=analysis_aggregate,
        build_session_analysis_view=analysis_session,
        build_period_analysis_view=analysis_period,
        settlement_analysis_prefs_store=analysis_prefs,
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return app, deps


def test_access_administrator_opens_users_and_settlement_operator_denied_roster(
    mongo_database: Database,
) -> None:
    store = MongoSystemUserStore(
        users_collection=mongo_database["master_system_users"],
        audit_collection=mongo_database["master_data_audit"],
    )
    admin = SystemUser(
        user_id=SystemUserId("1"),
        name="Admin",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=_ADMIN_TG,
        technician_id=None,
        company_roles=frozenset({CompanyRole.ACCESS_ADMINISTRATOR}),
    )
    operator = SystemUser(
        user_id=SystemUserId("2"),
        name="Ops",
        role=BotRole.NONE,
        is_active=True,
        telegram_user_id=_OPS_TG,
        technician_id=None,
        company_roles=frozenset({CompanyRole.SETTLEMENT_OPERATOR}),
    )
    store.replace_all(
        (
            SystemUserRecord(user=admin, updated_at=_NOW, updated_by_telegram_user_id=_ADMIN_TG),
            SystemUserRecord(
                user=operator,
                updated_at=_NOW,
                updated_by_telegram_user_id=_ADMIN_TG,
            ),
        )
    )
    provider = ReferenceDataProvider()
    hydrate_provider_from_system_users(provider, store)
    app, _deps = _build_admin_app(
        provider=provider,
        system_user_store=store,
        users_enabled=True,
        stub=True,
        settlement_analysis_enabled=True,
    )
    client = TestClient(app)
    assert client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    ).status_code in {302, 303}
    users = client.get("/admin/users")
    assert users.status_code == 200
    assert "company_role_access_administrator" in users.text
    assert "panel_" not in users.text

    client2 = TestClient(app)
    assert client2.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_OPS_TG)},
        follow_redirects=False,
    ).status_code in {302, 303}
    settlement = client2.get("/admin/settlement-analysis")
    assert settlement.status_code == 200
    assert client2.get("/admin/roster").status_code == 403
    assert client2.get("/admin/users").status_code == 403
