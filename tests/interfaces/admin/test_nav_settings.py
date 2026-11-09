from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests._company_roles_for_panels import company_roles_for_test_panels

from src.application.master_data import (
    CreateTechnician,
    InMemoryMasterDataAuditStore,
    InMemoryMasterDataCounterStore,
    InMemoryMasterDataStores,
    InMemorySystemUserStore,
    InMemoryTechnicianStore,
    SaveFieldStaff,
    SaveSystemUsers,
    SystemUserRecord,
    Technician,
    UpdateTechnician,
)
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import (
    BuildVisitBoardMonth,
    LocationDisplaySnapshot,
    NullMaintenanceOnOperationalDayLookup,
    PlacementAtSnapshot,
    RosterEntrySnapshot,
)
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.shared.admin_nav_memory import InMemoryAdminNavStructureStore
from src.application.sheets import SystemUsersSnapshot
from src.application.technician_settlement import (
    AggregateSettlementClusters,
    BuildPeriodAnalysisView,
    BuildSessionAnalysisView,
    BuildSettlementAnalysisTree,
    InMemorySettlementAnalysisPrefsStore,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.system_user import AdminPanel, BotRole, SystemUser, SystemUserId
from src.infrastructure.testing.settlement_fakes import (
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
)
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_FROZEN_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
_ORIGIN = {"origin": "http://testserver"}


@dataclass(frozen=True, slots=True)
class _EmptyRoster:
    def list_entries(self) -> tuple[RosterEntrySnapshot, ...]:
        return ()


@dataclass(frozen=True, slots=True)
class _EmptyPlacement:
    def placements_for_machine(
        self,
        machine_id: MachineId,
    ) -> tuple[PlacementAtSnapshot, ...]:
        return ()


@dataclass(frozen=True, slots=True)
class _EmptyLocations:
    def display_for(self, location_id: str) -> LocationDisplaySnapshot | None:
        return None


@dataclass(frozen=True, slots=True)
class _EmptyTech:
    def display_name(self, technician_id: TechnicianId) -> str | None:
        return None


def _empty_build_visit_board() -> BuildVisitBoardMonth:
    return BuildVisitBoardMonth(
        visit_store=InMemoryServiceVisitStore(),
        roster=_EmptyRoster(),
        placements=_EmptyPlacement(),
        locations=_EmptyLocations(),
        technicians=_EmptyTech(),
        timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
    )


def _build_users_app(
    *,
    panels: frozenset[AdminPanel],
    telegram_user_id: int = _ADMIN_TG,
    with_master_stores: bool = False,
    with_visit_board: bool = False,
    technicians_enabled: bool = False,
    settlement_analysis_enabled: bool = False,
    nav_store: InMemoryAdminNavStructureStore | None = None,
) -> tuple[FastAPI, AdminHttpDeps]:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Иван"]],
    )
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника"],
            ["101", "Школа", "Иван", "001"],
        ],
    )
    roster_store = InMemoryLocationRosterStore()
    provider.configure_roster(enabled=True, store=roster_store)
    user = SystemUser(
        user_id=SystemUserId("1"),
        name="Ops",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=telegram_user_id,
        technician_id=None,
        company_roles=company_roles_for_test_panels(panels),
    )
    snap = SystemUsersSnapshot(
        users_by_telegram_id={telegram_user_id: user},
        users_by_technician_id={},
    )
    provider.apply_system_users_snapshot(snap)
    system_user_store = InMemorySystemUserStore()
    system_user_store.replace_all(
        (
            SystemUserRecord(
                user=user,
                updated_at=_FROZEN_NOW,
                updated_by_telegram_user_id=telegram_user_id,
            ),
        ),
    )
    counters = InMemoryMasterDataCounterStore()
    master_stores = InMemoryMasterDataStores() if with_master_stores else None
    build_visit_board = _empty_build_visit_board() if with_visit_board else None
    technician_store = None
    create_technician = None
    update_technician = None
    audit = InMemoryMasterDataAuditStore()
    if technicians_enabled:
        technician_store = InMemoryTechnicianStore()
        technician_store.upsert(
            Technician(
                technician_id=TechnicianId("001"),
                name="Иван",
                is_active=True,
            ),
        )
        create_technician = CreateTechnician(
            store=technician_store,
            counters=counters,
            audit=audit,
        )
        update_technician = UpdateTechnician(store=technician_store, audit=audit)
    save_system_users = SaveSystemUsers(store=system_user_store, counters=counters)
    save_field_staff = SaveFieldStaff(
        save_system_users=save_system_users,
        create_technician=create_technician,
        update_technician=update_technician,
        technician_store=technician_store,
        technicians_enabled=technicians_enabled,
    )
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
        stub_login_enabled=True,
        timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
        now_factory=lambda: _FROZEN_NOW,
        master_stores=master_stores,
        build_visit_board=build_visit_board,
        users_enabled=True,
        system_user_store=system_user_store,
        save_system_users=save_system_users,
        save_field_staff=save_field_staff,
        technicians_enabled=technicians_enabled,
        technician_store=technician_store,
        create_technician=create_technician,
        update_technician=update_technician,
        settlement_analysis_enabled=settlement_analysis_enabled,
        build_settlement_analysis_tree=analysis_tree,
        aggregate_settlement_clusters=analysis_aggregate,
        build_session_analysis_view=analysis_session,
        build_period_analysis_view=analysis_period,
        settlement_analysis_prefs_store=analysis_prefs,
        admin_nav_structure_store=nav_store,
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return app, deps


def test_nav_settings_forbidden_without_panel() -> None:
    app, _deps = _build_users_app(
        panels=frozenset({AdminPanel.ROSTER}),
        nav_store=InMemoryAdminNavStructureStore(),
    )
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    assert client.get("/admin/nav-settings").status_code == 403


def test_nav_settings_ok_with_panel() -> None:
    app, _deps = _build_users_app(
        panels=frozenset({AdminPanel.USERS, AdminPanel.NAV_SETTINGS}),
        nav_store=InMemoryAdminNavStructureStore(),
    )
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    response = client.get("/admin/nav-settings")
    assert response.status_code == 200
    assert "admin-save-bar" in response.text
    assert "nav-settings" in response.text or "Справочники" in response.text


def _nav_client(
    store: InMemoryAdminNavStructureStore,
) -> tuple[TestClient, InMemoryAdminNavStructureStore]:
    app, _deps = _build_users_app(
        panels=frozenset({AdminPanel.USERS, AdminPanel.NAV_SETTINGS}),
        nav_store=store,
    )
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    return client, store


def test_nav_settings_post_persists() -> None:
    client, nav_store = _nav_client(InMemoryAdminNavStructureStore())
    payload = {
        "structure_json": json.dumps(
            [
                {"type": "panel", "panel": "roster"},
                {
                    "type": "folder",
                    "id": "directories",
                    "title": "Справочники",
                    "children": ["master_data", "users"],
                },
                {"type": "panel", "panel": "nav_settings"},
            ]
        )
    }
    response = client.post("/admin/nav-settings", data=payload, headers=_ORIGIN)
    assert response.status_code in {200, 303}
    saved = nav_store.get()
    assert saved is not None
    assert any(n.kind == "folder" and n.title == "Справочники" for n in saved.nodes)


def test_nav_settings_post_rejects_duplicate() -> None:
    client, nav_store = _nav_client(InMemoryAdminNavStructureStore())
    payload = {
        "structure_json": json.dumps(
            [
                {"type": "panel", "panel": "roster"},
                {"type": "panel", "panel": "roster"},
            ]
        )
    }
    response = client.post("/admin/nav-settings", data=payload, headers=_ORIGIN)
    assert response.status_code == 400
    assert nav_store.get() is None


def test_nav_settings_post_rejects_empty_folder_title() -> None:
    client, nav_store = _nav_client(InMemoryAdminNavStructureStore())
    payload = {
        "structure_json": json.dumps(
            [
                {
                    "type": "folder",
                    "id": "x",
                    "title": "  ",
                    "children": ["roster"],
                }
            ]
        )
    }
    response = client.post("/admin/nav-settings", data=payload, headers=_ORIGIN)
    assert response.status_code == 400
    assert nav_store.get() is None


def test_nav_settings_has_dnd_hooks() -> None:
    client, _store = _nav_client(InMemoryAdminNavStructureStore())
    html = client.get("/admin/nav-settings").text
    assert "nav_settings.js" in html or "data-nav-structure" in html
    assert "admin-save-bar" in html


def test_nav_settings_users_panel_access_label() -> None:
    from pathlib import Path

    js_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "interfaces"
        / "admin"
        / "static"
        / "nav_settings.js"
    )
    source = js_path.read_text(encoding="utf-8")
    assert 'users: "Доступ"' in source
    assert 'users: "Люди"' not in source
    assert 'matrix_pricing: "Правила цены"' in source
    assert 'matrix_sku_catalog: "SKU матрицы"' in source
    assert 'technicians: "Техники"' in source


def test_users_form_has_company_role_checkboxes() -> None:
    app, _deps = _build_users_app(panels=frozenset({AdminPanel.USERS}))
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    html = client.get("/admin/users").text
    assert "company_role_access_administrator" in html
    assert "panel_nav_settings" not in html
