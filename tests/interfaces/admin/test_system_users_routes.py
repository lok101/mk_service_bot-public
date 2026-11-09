from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests._company_roles_for_panels import company_roles_for_test_panels

from src.application.master_data import (
    CreateCompany,
    CreateTechnician,
    InMemoryCompanyStore,
    InMemoryMasterDataAuditStore,
    InMemoryMasterDataCounterStore,
    InMemoryMasterDataStores,
    InMemorySystemUserStore,
    InMemoryTechnicianStore,
    SaveFieldStaff,
    SaveSystemUsers,
    SystemUserRecord,
    Technician,
    UpdateCompany,
    UpdateTechnician,
)
from src.application.matrix_automation.base_margin_store_memory import InMemoryMatrixBaseMarginStore
from src.application.matrix_automation.matrix_sku_catalog_memory import (
    InMemoryMatrixSkuCatalogStore,
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
from src.application.sheets import SystemUsersSnapshot
from src.application.technician_settlement import (
    AggregateSettlementClusters,
    BuildPeriodAnalysisView,
    BuildSessionAnalysisView,
    BuildSettlementAnalysisTree,
    InMemorySettlementAnalysisPrefsStore,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.system_user import (
    AdminPanel,
    BotRole,
    CompanyRole,
    SystemUser,
    SystemUserId,
)
from src.infrastructure.product_identity import (
    MemoryDomainProductStore,
    SnapshotCatalogProductLookup,
)
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
    InMemoryMicromarketPlanogramStore,
)
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


def _registered_route_paths(app: FastAPI) -> set[str]:
    return {path for route in app.routes if isinstance(path := getattr(route, "path", None), str)}


def _build_users_app(
    *,
    company_roles: frozenset[CompanyRole] | None = None,
    panels: frozenset[AdminPanel] | None = None,
    telegram_user_id: int = _ADMIN_TG,
    with_master_stores: bool = False,
    with_visit_board: bool = False,
    technicians_enabled: bool = False,
    companies_enabled: bool = False,
    settlement_analysis_enabled: bool = False,
    visit_photo_review_enabled: bool = False,
    sku_catalog_master_enabled: bool = False,
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
    if company_roles is None:
        if panels is None:
            raise TypeError("company_roles or panels required")
        company_roles = company_roles_for_test_panels(panels)
    user = SystemUser(
        user_id=SystemUserId("1"),
        name="Ops",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=telegram_user_id,
        technician_id=None,
        company_roles=company_roles,
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
    matrix_base_margin_store = InMemoryMatrixBaseMarginStore() if with_master_stores else None
    micromarket_planogram_store = (
        InMemoryMicromarketPlanogramStore() if with_master_stores else None
    )
    micromarket_stock_store = InMemoryMicromarketDeviceStockStore() if with_master_stores else None
    domain_product_store = None
    catalog_product_lookup = None
    coffee_machine_model_store = None
    stand_type_store = None
    stand_color_store = None
    visit_photo_profile_store = None
    save_visit_photo_profile = None
    visit_photo_profile_tech_ref_storage = None
    border_registration_store = None
    if with_master_stores:
        from src.application.product_identity import MemoryBorderRegistrationStore

        domain_product_store = MemoryDomainProductStore()
        catalog_product_lookup = SnapshotCatalogProductLookup(provider)
        border_registration_store = MemoryBorderRegistrationStore()
        from src.application.master_data import (
            InMemoryCoffeeMachineModelStore,
            InMemoryStandColorStore,
            InMemoryStandTypeStore,
        )
        from src.application.visit_photo_review.profile import (
            InMemoryVisitPhotoProfileStore,
            SaveVisitPhotoProfile,
        )
        from src.infrastructure.composition.adapters.visit_photo_profile_lookup import (
            MasterCoffeeEquipmentCatalogLookup,
        )
        from src.infrastructure.visit_photo_review.profile_storage import (
            FilesystemVisitPhotoProfileTechRefStorage,
        )

        coffee_machine_model_store = InMemoryCoffeeMachineModelStore()
        stand_type_store = InMemoryStandTypeStore()
        stand_color_store = InMemoryStandColorStore()
        visit_photo_profile_store = InMemoryVisitPhotoProfileStore()
        save_visit_photo_profile = SaveVisitPhotoProfile(
            store=visit_photo_profile_store,
            catalog=MasterCoffeeEquipmentCatalogLookup(
                models=coffee_machine_model_store,
                stand_types=stand_type_store,
            ),
        )
        visit_photo_profile_tech_ref_storage = FilesystemVisitPhotoProfileTechRefStorage(
            Path("."),  # unused in characterization; admin CRUD tests use own root
        )
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
    company_store = None
    create_company = None
    update_company = None
    company_display_names: dict[int, str] | None = None
    refresh_company_display_names = None
    if companies_enabled:
        company_store = InMemoryCompanyStore()
        create_company = CreateCompany(store=company_store, counters=counters, audit=audit)
        update_company = UpdateCompany(store=company_store, audit=audit)
        company_display_names = {}

        def _refresh_company_display_names() -> None:
            assert company_display_names is not None
            assert company_store is not None
            company_display_names.clear()
            company_display_names.update(
                {c.company_id: c.name.strip() for c in company_store.list_all() if c.is_active},
            )

        refresh_company_display_names = _refresh_company_display_names
        _refresh_company_display_names()
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
    review_queries = None
    if visit_photo_review_enabled:
        from tests.application.visit_photo_review.fakes import (
            FixedBatches,
            FixedCatalog,
            MemoryReviewStore,
        )

        from src.application.visit_photo_review import ReviewQueries
        from src.domain.visit_photo_review import CatalogGroup, ReviewCatalog

        review_queries = ReviewQueries(
            FixedCatalog(
                ReviewCatalog(
                    groups=(
                        CatalogGroup(
                            group_id="waste_tank",
                            title="Бак",
                            required=True,
                            defects=(),
                        ),
                    )
                )
            ),
            MemoryReviewStore(),
            FixedBatches(None),
        )
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
        companies_enabled=companies_enabled,
        company_store=company_store,
        create_company=create_company,
        update_company=update_company,
        company_display_names=company_display_names,
        refresh_company_display_names=refresh_company_display_names,
        matrix_base_margin_store=matrix_base_margin_store,
        settlement_analysis_enabled=settlement_analysis_enabled,
        build_settlement_analysis_tree=analysis_tree,
        aggregate_settlement_clusters=analysis_aggregate,
        build_session_analysis_view=analysis_session,
        build_period_analysis_view=analysis_period,
        settlement_analysis_prefs_store=analysis_prefs,
        visit_photo_review_enabled=visit_photo_review_enabled,
        review_queries=review_queries,
        coffee_machine_model_store=coffee_machine_model_store,
        stand_type_store=stand_type_store,
        stand_color_store=stand_color_store,
        visit_photo_profile_store=visit_photo_profile_store,
        save_visit_photo_profile=save_visit_photo_profile,
        visit_photo_profile_tech_ref_storage=visit_photo_profile_tech_ref_storage,
        sku_catalog_master_enabled=sku_catalog_master_enabled,
        matrix_sku_catalog_store=(
            InMemoryMatrixSkuCatalogStore() if sku_catalog_master_enabled else None
        ),
        domain_product_store=domain_product_store,
        border_registration_store=border_registration_store,
        catalog_product_lookup=catalog_product_lookup,
        micromarket_planogram_store=micromarket_planogram_store,
        micromarket_stock_store=micromarket_stock_store,
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return app, deps


def test_access_form_has_no_field_accounting_columns() -> None:
    app, _deps = _build_users_app(
        panels=frozenset({AdminPanel.USERS}),
        technicians_enabled=True,
    )
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    html = client.get("/admin/users").text
    assert "Полевой учёт" not in html
    assert 'name="field_accounting-' not in html
    assert 'name="technician_is_active-' not in html
    assert "В учёте" not in html


def test_users_page_title_is_access() -> None:
    app, _deps = _build_users_app(panels=frozenset({AdminPanel.USERS}))
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    html = client.get("/admin/users").text
    assert "Доступ" in html
    assert "Люди" not in html or "admin-hint" not in html


def test_nav_access_label_on_users_path() -> None:
    app, _deps = _build_users_app(
        panels=frozenset({AdminPanel.USERS}),
        with_master_stores=True,
        technicians_enabled=True,
    )
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    html = client.get("/admin/users").text
    assert ">Доступ<" in html or "Доступ</" in html
    assert 'href="/admin/users"' in html
    assert ">Люди<" not in html


def test_nav_shows_only_allowed_panels() -> None:
    app, deps = _build_users_app(
        panels=frozenset({AdminPanel.ROSTER, AdminPanel.VISIT_BOARD, AdminPanel.MASTER_DATA}),
        telegram_user_id=_ADMIN_TG,
    )
    client = TestClient(app)
    assert client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    ).status_code in {302, 303}
    response = client.get("/admin/roster")
    assert response.status_code == 200
    assert 'href="/admin/roster"' in response.text
    assert 'href="/admin/users"' not in response.text
    assert 'href="/admin/machines"' not in response.text


def test_users_get_ok_with_panel() -> None:
    app, _deps = _build_users_app(panels=frozenset({AdminPanel.USERS}))
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    response = client.get("/admin/users")
    assert response.status_code == 200
    assert "Telegram" in response.text or "telegram" in response.text.lower()
    assert 'id="users-active-filter"' in response.text
    assert 'value="active" selected' in response.text
    assert 'src="/admin/static/users.js?v=' in response.text


def test_users_page_role_checkbox_names_use_row_index() -> None:
    """Nested Jinja loop must bind company_role_* names to row index."""
    app, deps = _build_users_app(
        panels=frozenset({AdminPanel.USERS}),
    )
    store = deps.system_user_store
    assert store is not None
    admin = store.get(_ADMIN_TG)
    assert admin is not None
    tech = SystemUser(
        user_id=SystemUserId("2"),
        name="Tech",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=2002,
        technician_id=None,
        company_roles=frozenset(),
    )
    store.replace_all(
        (
            admin,
            SystemUserRecord(
                user=tech,
                updated_at=_FROZEN_NOW,
                updated_by_telegram_user_id=_ADMIN_TG,
            ),
        ),
    )
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    response = client.get("/admin/users")
    assert response.status_code == 200
    html = response.text
    assert "panel_" not in html
    assert "галочк" not in html.lower()
    for role in CompanyRole:
        assert f'name="company_role_{role.value}-0"' in html
        assert f'name="company_role_{role.value}-1"' in html


def test_users_get_forbidden_without_access_administrator() -> None:
    app, _deps = _build_users_app(
        panels=frozenset({AdminPanel.ROSTER, AdminPanel.VISIT_BOARD, AdminPanel.MASTER_DATA}),
    )
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    assert client.get("/admin/users").status_code == 403


def test_users_page_has_admin_save_bar() -> None:
    app, _deps = _build_users_app(panels=frozenset({AdminPanel.USERS}))
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    html = client.get("/admin/users").text
    assert "admin-save-bar" in html


def test_access_linked_telegram_is_read_only() -> None:
    app, deps = _build_users_app(
        panels=frozenset({AdminPanel.USERS}),
        technicians_enabled=True,
    )
    assert deps.system_user_store is not None
    tech_id = TechnicianId("001")
    field_user = SystemUser(
        user_id=SystemUserId("2"),
        name="Иван",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=3003,
        technician_id=tech_id,
        company_roles=frozenset(),
    )
    admin = deps.system_user_store.get(_ADMIN_TG)
    assert admin is not None
    deps.system_user_store.replace_all(
        (
            admin,
            SystemUserRecord(
                user=field_user,
                updated_at=_FROZEN_NOW,
                updated_by_telegram_user_id=_ADMIN_TG,
            ),
        ),
    )
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    html = client.get("/admin/users").text
    assert 'name="telegram_user_id-1"' in html
    assert 'type="hidden"' in html
    assert 'name="telegram_user_id-1"' in html.split('name="telegram_user_id-0"')[1]
    linked_section = html.split('name="telegram_user_id-1"')[1].split("</tr>")[0]
    assert 'type="text"' not in linked_section
    assert "<span>3003</span>" in html
    assert 'name="telegram_user_id-0"' in html
    admin_section = html.split('name="telegram_user_id-0"')[1].split("</tr>")[0]
    assert 'type="text"' in admin_section


def test_access_form_has_no_technician_select() -> None:
    app, _deps = _build_users_app(
        panels=frozenset({AdminPanel.USERS}),
        technicians_enabled=True,
    )
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    html = client.get("/admin/users").text
    assert 'name="technician_id-' not in html


def test_access_post_omitted_bot_role_preserves_technician_role() -> None:
    app, deps = _build_users_app(
        panels=frozenset({AdminPanel.USERS}),
        technicians_enabled=True,
    )
    assert deps.system_user_store is not None
    tech_id = TechnicianId("001")
    field_user = SystemUser(
        user_id=SystemUserId("2"),
        name="Иван",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=3003,
        technician_id=tech_id,
        company_roles=frozenset(),
    )
    admin = deps.system_user_store.get(_ADMIN_TG)
    assert admin is not None
    deps.system_user_store.replace_all(
        (
            admin,
            SystemUserRecord(
                user=field_user,
                updated_at=_FROZEN_NOW,
                updated_by_telegram_user_id=_ADMIN_TG,
            ),
        ),
    )
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    response = client.post(
        "/admin/users",
        data={
            "user_id-0": "1",
            "name-0": "Ops",
            "telegram_user_id-0": str(_ADMIN_TG),
            "is_active-0": "on",
            "company_role_access_administrator-0": "on",
            "user_id-1": "2",
            "name-1": "Иван",
            "telegram_user_id-1": "3003",
            "is_active-1": "on",
            "company_role_service_operations_coordinator-1": "on",
        },
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    updated = deps.system_user_store.get(3003)
    assert updated is not None
    assert updated.user.role is BotRole.TECHNICIAN
    assert updated.user.technician_id == tech_id


def test_people_form_parser_removed_from_admin_routes() -> None:
    import src.interfaces.admin.routes as routes

    assert not hasattr(routes, "_people_rows_from_users_form")
    assert not hasattr(routes, "_people_row_from_indexed_row")


def test_access_form_parse_rows() -> None:
    from src.interfaces.admin.routes import _access_rows_from_users_form

    rows = _access_rows_from_users_form(
        {
            "user_id-0": "1",
            "name-0": "Ops",
            "telegram_user_id-0": "1001",
            "bot_role-0": "administrator",
            "is_active-0": "on",
            "company_role_access_administrator-0": "on",
        }
    )
    assert len(rows) == 1
    assert rows[0].name == "Ops"
    assert rows[0].bot_role is BotRole.ADMINISTRATOR
    assert rows[0].company_roles == frozenset({CompanyRole.ACCESS_ADMINISTRATOR})


def test_access_post_preserves_technician_link() -> None:
    app, deps = _build_users_app(
        panels=frozenset({AdminPanel.USERS}),
        technicians_enabled=True,
    )
    assert deps.system_user_store is not None
    tech_id = TechnicianId("001")
    field_user = SystemUser(
        user_id=SystemUserId("2"),
        name="Иван",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=3003,
        technician_id=tech_id,
        company_roles=frozenset(),
    )
    admin = deps.system_user_store.get(_ADMIN_TG)
    assert admin is not None
    deps.system_user_store.replace_all(
        (
            admin,
            SystemUserRecord(
                user=field_user,
                updated_at=_FROZEN_NOW,
                updated_by_telegram_user_id=_ADMIN_TG,
            ),
        ),
    )
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    response = client.post(
        "/admin/users",
        data={
            "user_id-0": "1",
            "name-0": "Ops",
            "telegram_user_id-0": str(_ADMIN_TG),
            "bot_role-0": "administrator",
            "is_active-0": "on",
            "company_role_access_administrator-0": "on",
            "user_id-1": "2",
            "name-1": "Иван",
            "telegram_user_id-1": "3003",
            "bot_role-1": "technician",
            "is_active-1": "on",
            "company_role_service_operations_coordinator-1": "on",
        },
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    updated = deps.system_user_store.get(3003)
    assert updated is not None
    assert updated.user.technician_id == tech_id
    assert AdminPanel.ROSTER in updated.user.panels


def test_access_post_office_create_no_technician() -> None:
    app, deps = _build_users_app(panels=frozenset({AdminPanel.USERS, AdminPanel.ROSTER}))
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    response = client.post(
        "/admin/users",
        data={
            "user_id-0": "1",
            "name-0": "Ops",
            "telegram_user_id-0": str(_ADMIN_TG),
            "bot_role-0": "administrator",
            "is_active-0": "on",
            "company_role_access_administrator-0": "on",
            "user_id-1": "",
            "name-1": "Мария",
            "telegram_user_id-1": "4004",
            "bot_role-1": "none",
            "is_active-1": "on",
            "company_role_service_operations_coordinator-1": "on",
        },
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    assert deps.system_user_store is not None
    created = deps.system_user_store.get(4004)
    assert created is not None
    assert created.user.name == "Мария"
    assert created.user.technician_id is None
    assert created.user.role is BotRole.NONE


def test_users_post_rejects_foreign_origin() -> None:
    app, _deps = _build_users_app(panels=frozenset({AdminPanel.USERS}))
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    response = client.post(
        "/admin/users",
        data={
            "user_id-0": "1",
            "name-0": "Ops",
            "telegram_user_id-0": str(_ADMIN_TG),
            "bot_role-0": "administrator",
            "is_active-0": "on",
            "company_role_access_administrator-0": "on",
        },
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_users_post_happy_updates_store() -> None:
    app, deps = _build_users_app(panels=frozenset({AdminPanel.USERS, AdminPanel.ROSTER}))
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    response = client.post(
        "/admin/users",
        data={
            "user_id-0": "1",
            "name-0": "Ops",
            "telegram_user_id-0": str(_ADMIN_TG),
            "bot_role-0": "administrator",
            "is_active-0": "on",
            "company_role_access_administrator-0": "on",
            "company_role_service_operations_coordinator-0": "on",
        },
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    assert deps.system_user_store is not None
    record = deps.system_user_store.get(_ADMIN_TG)
    assert record is not None
    assert AdminPanel.ROSTER in record.user.panels
    snap = deps.provider.system_users()
    assert snap.users_by_telegram_id[_ADMIN_TG].panels == record.user.panels


def test_users_post_persists_micromarket_planograms_panel() -> None:
    app, deps = _build_users_app(
        panels=frozenset({AdminPanel.USERS, AdminPanel.MICROMARKET_PLANOGRAMS}),
    )
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    response = client.post(
        "/admin/users",
        data={
            "user_id-0": "1",
            "name-0": "Ops",
            "telegram_user_id-0": str(_ADMIN_TG),
            "bot_role-0": "administrator",
            "is_active-0": "on",
            "company_role_access_administrator-0": "on",
            "company_role_planogram_curator-0": "on",
        },
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    assert deps.system_user_store is not None
    record = deps.system_user_store.get(_ADMIN_TG)
    assert record is not None
    assert AdminPanel.MICROMARKET_PLANOGRAMS in record.user.panels


def test_users_post_ok_when_technicians_enabled() -> None:
    """LOK-80: POST with technicians_enabled must not 500."""
    app, deps = _build_users_app(
        panels=frozenset({AdminPanel.USERS}),
        technicians_enabled=True,
    )
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    response = client.post(
        "/admin/users",
        data={
            "user_id-0": "1",
            "name-0": "Ops",
            "telegram_user_id-0": str(_ADMIN_TG),
            "bot_role-0": "administrator",
            "is_active-0": "on",
            "company_role_access_administrator-0": "on",
            "company_role_service_operations_coordinator-0": "on",
        },
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    assert deps.system_user_store is not None
    record = deps.system_user_store.get(_ADMIN_TG)
    assert record is not None
    assert record.user.technician_id is None


def test_users_post_guard_returns_400() -> None:
    app, deps = _build_users_app(panels=frozenset({AdminPanel.USERS}))
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    assert deps.system_user_store is not None
    before = deps.system_user_store.get(_ADMIN_TG)
    assert before is not None
    response = client.post(
        "/admin/users",
        data={
            "user_id-0": "1",
            "name-0": "Ops",
            "telegram_user_id-0": str(_ADMIN_TG),
            "bot_role-0": "administrator",
            "is_active-0": "on",
        },
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    after = deps.system_user_store.get(_ADMIN_TG)
    assert after is not None
    assert after.user.panels == before.user.panels


def test_users_post_creates_new_row() -> None:
    app, deps = _build_users_app(panels=frozenset({AdminPanel.USERS, AdminPanel.ROSTER}))
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    response = client.post(
        "/admin/users",
        data={
            "user_id-0": "1",
            "name-0": "Ops",
            "telegram_user_id-0": str(_ADMIN_TG),
            "bot_role-0": "administrator",
            "is_active-0": "on",
            "company_role_access_administrator-0": "on",
            "user_id-1": "",
            "name-1": "New",
            "telegram_user_id-1": "2002",
            "bot_role-1": "none",
            "is_active-1": "on",
            "company_role_service_operations_coordinator-1": "on",
        },
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    assert deps.system_user_store is not None
    created = deps.system_user_store.get(2002)
    assert created is not None
    assert created.user.name == "New"
    assert AdminPanel.ROSTER in created.user.panels


def test_users_post_partial_preserves_omitted() -> None:
    app, deps = _build_users_app(panels=frozenset({AdminPanel.USERS}))
    assert deps.system_user_store is not None
    admin = SystemUser(
        user_id=SystemUserId("1"),
        name="Ops",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=_ADMIN_TG,
        technician_id=None,
        company_roles=frozenset({CompanyRole.ACCESS_ADMINISTRATOR}),
    )
    other = SystemUser(
        user_id=SystemUserId("2"),
        name="Other",
        role=BotRole.NONE,
        is_active=True,
        telegram_user_id=2002,
        technician_id=None,
        company_roles=frozenset({CompanyRole.SERVICE_OPERATIONS_COORDINATOR}),
    )
    deps.system_user_store.replace_all(
        (
            SystemUserRecord(
                user=admin,
                updated_at=_FROZEN_NOW,
                updated_by_telegram_user_id=_ADMIN_TG,
            ),
            SystemUserRecord(
                user=other,
                updated_at=_FROZEN_NOW,
                updated_by_telegram_user_id=_ADMIN_TG,
            ),
        ),
    )
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    response = client.post(
        "/admin/users",
        data={
            "user_id-0": "1",
            "name-0": "Ops Only",
            "telegram_user_id-0": str(_ADMIN_TG),
            "bot_role-0": "administrator",
            "is_active-0": "on",
            "company_role_access_administrator-0": "on",
        },
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    assert deps.system_user_store.get(2002) is not None
    assert deps.system_user_store.get(2002).user.name == "Other"


def test_users_post_rejects_non_access_administrator() -> None:
    app, deps = _build_users_app(
        panels=frozenset({AdminPanel.SETTLEMENT_ANALYSIS}),
        settlement_analysis_enabled=True,
    )
    client = TestClient(app)
    client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    response = client.post(
        "/admin/users",
        data={
            "user_id-0": "1",
            "name-0": "Ops",
            "telegram_user_id-0": str(_ADMIN_TG),
            "bot_role-0": "administrator",
            "is_active-0": "on",
            "company_role_access_administrator-0": "on",
        },
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert deps.system_user_store is not None
    assert CompanyRole.ACCESS_ADMINISTRATOR not in (
        deps.system_user_store.get(_ADMIN_TG).user.company_roles  # type: ignore[union-attr]
    )


def test_every_admin_panel_has_route() -> None:
    mapping = {
        AdminPanel.ROSTER: "/admin/roster",
        AdminPanel.MASTER_DATA: "/admin/machines",
        AdminPanel.USERS: "/admin/users",
        AdminPanel.VISIT_BOARD: "/admin/visit-board",
        AdminPanel.VISIT_PHOTO_REVIEW: "/admin/visit-photo-review",
        AdminPanel.SETTLEMENT_ANALYSIS: "/admin/settlement-analysis",
        AdminPanel.MATRIX_PRICING: "/admin/matrix-pricing",
        AdminPanel.MATRIX_SKU_CATALOG: "/admin/matrix-sku-catalog",
        AdminPanel.MICROMARKET_PLANOGRAMS: "/admin/micromarket-planograms",
        AdminPanel.TECHNICIANS: "/admin/technicians",
        AdminPanel.COMPANIES: "/admin/companies",
        AdminPanel.DOMAIN_PRODUCTS: "/admin/domain-products",
        AdminPanel.COFFEE_RECIPES: "/admin/coffee-ingredients",
        AdminPanel.NAV_SETTINGS: "/admin/nav-settings",
    }
    assert set(mapping) == set(AdminPanel)
    app, _deps = _build_users_app(
        panels=frozenset({AdminPanel.USERS}),
        with_master_stores=True,
        with_visit_board=True,
        technicians_enabled=True,
        companies_enabled=True,
        settlement_analysis_enabled=True,
        visit_photo_review_enabled=True,
        sku_catalog_master_enabled=True,
    )
    registered = _registered_route_paths(app)
    for panel, path in mapping.items():
        if panel is AdminPanel.DOMAIN_PRODUCTS:
            # Route mounted by domain-product-identity pack; panel exists for nav exhaustiveness.
            continue
        assert path in registered
