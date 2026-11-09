from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID
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
    UpdateCompany,
    UpdateTechnician,
)
from src.application.matrix_automation.matrix_sku_catalog_memory import (
    InMemoryMatrixSkuCatalogStore,
)
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.sheets import SystemUsersSnapshot
from src.domain.system_user import AdminPanel, BotRole, SystemUser, SystemUserId
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes
from src.interfaces.admin.session import admin_session_cookie_name, pack_admin_session

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_FROZEN_NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def _authed(client: TestClient) -> None:
    token = pack_admin_session(
        telegram_user_id=_ADMIN_TG,
        issued_at=int(_FROZEN_NOW.timestamp()),
        secret=_SESSION_SECRET,
    )
    client.cookies.set(admin_session_cookie_name(), token)


def _user(*, panels: frozenset[AdminPanel]) -> SystemUser:
    return SystemUser(
        user_id=SystemUserId("1"),
        name="Ops",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=_ADMIN_TG,
        technician_id=None,
        company_roles=company_roles_for_test_panels(panels),
    )


def _provider_and_store(
    *,
    panels: frozenset[AdminPanel],
) -> tuple[ReferenceDataProvider, InMemoryLocationRosterStore, InMemorySystemUserStore]:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Иван"]],
    )
    roster_store = InMemoryLocationRosterStore()
    provider.configure_roster(enabled=True, store=roster_store)
    user = _user(panels=panels)
    provider.apply_system_users_snapshot(
        SystemUsersSnapshot(
            users_by_telegram_id={_ADMIN_TG: user},
            users_by_technician_id={},
        ),
    )
    system_user_store = InMemorySystemUserStore()
    system_user_store.replace_all(
        (
            SystemUserRecord(
                user=user,
                updated_at=_FROZEN_NOW,
                updated_by_telegram_user_id=_ADMIN_TG,
            ),
        ),
    )
    return provider, roster_store, system_user_store


def _core_kwargs(
    *,
    provider: ReferenceDataProvider,
    roster_store: InMemoryLocationRosterStore,
    system_user_store: InMemorySystemUserStore,
) -> dict[str, object]:
    return {
        "provider": provider,
        "roster_store": roster_store,
        "roster_draft_store": InMemoryLocationRosterDraftStore(),
        "visit_store": InMemoryServiceVisitStore(),
        "maintenance_lookup": NullMaintenanceOnOperationalDayLookup(),
        "bot_token": _BOT_TOKEN,
        "session_secret": _SESSION_SECRET,
        "session_ttl_seconds": 86400,
        "telegram_auth_max_age_seconds": 86400,
        "telegram_bot_username": "mk_bot",
        "stub_login_enabled": True,
        "timezone": ZoneInfo("Europe/Moscow"),
        "day_end_hour": 6,
        "now_factory": lambda: _FROZEN_NOW,
        "users_enabled": True,
        "system_user_store": system_user_store,
    }


def _client(deps: AdminHttpDeps) -> TestClient:
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    client = TestClient(app)
    _authed(client)
    return client


def _technicians_client(*, panels: frozenset[AdminPanel]) -> TestClient:
    provider, roster_store, system_user_store = _provider_and_store(panels=panels)
    technician_store = InMemoryTechnicianStore()
    counters = InMemoryMasterDataCounterStore()
    audit = InMemoryMasterDataAuditStore()
    create_uc = CreateTechnician(store=technician_store, counters=counters, audit=audit)
    update_uc = UpdateTechnician(store=technician_store, audit=audit)
    save_field_staff = SaveFieldStaff(
        save_system_users=SaveSystemUsers(store=system_user_store, counters=counters),
        create_technician=create_uc,
        update_technician=update_uc,
        technician_store=technician_store,
        technicians_enabled=True,
    )
    deps = AdminHttpDeps(
        **_core_kwargs(  # type: ignore[arg-type]
            provider=provider,
            roster_store=roster_store,
            system_user_store=system_user_store,
        ),
        technicians_enabled=True,
        technician_store=technician_store,
        create_technician=create_uc,
        update_technician=update_uc,
        save_field_staff=save_field_staff,
    )
    return _client(deps)


def _companies_client(*, panels: frozenset[AdminPanel]) -> TestClient:
    provider, roster_store, system_user_store = _provider_and_store(panels=panels)
    store = InMemoryCompanyStore()
    counters = InMemoryMasterDataCounterStore()
    audit = InMemoryMasterDataAuditStore()
    deps = AdminHttpDeps(
        **_core_kwargs(  # type: ignore[arg-type]
            provider=provider,
            roster_store=roster_store,
            system_user_store=system_user_store,
        ),
        companies_enabled=True,
        company_store=store,
        create_company=CreateCompany(store=store, counters=counters, audit=audit),
        update_company=UpdateCompany(store=store, audit=audit),
        company_display_names={},
        refresh_company_display_names=lambda: None,
    )
    return _client(deps)


class _EmptySnackAssortmentReader:
    async def list_by_folder_ids(
        self,
        *,
        entity_kind: str,
        folder_ids: object,
    ) -> list[object]:
        return []


def _sku_catalog_client(*, panels: frozenset[AdminPanel]) -> TestClient:
    provider, roster_store, system_user_store = _provider_and_store(panels=panels)
    deps = AdminHttpDeps(
        **_core_kwargs(  # type: ignore[arg-type]
            provider=provider,
            roster_store=roster_store,
            system_user_store=system_user_store,
        ),
        master_stores=InMemoryMasterDataStores(),
        sku_catalog_master_enabled=True,
        matrix_sku_catalog_store=InMemoryMatrixSkuCatalogStore(),
        snack_sku_assortment_reader=_EmptySnackAssortmentReader(),  # type: ignore[arg-type]
        snack_sku_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
    )
    return _client(deps)


def test_technicians_happy_narrow_panel_grants_access() -> None:
    client = _technicians_client(panels=frozenset({AdminPanel.TECHNICIANS}))
    assert client.get("/admin/technicians").status_code == 200


def test_technicians_edge_master_data_alone_denied() -> None:
    client = _technicians_client(panels=frozenset({AdminPanel.MASTER_DATA}))
    assert client.get("/admin/technicians").status_code == 403


def test_technicians_error_no_panel_denied() -> None:
    client = _technicians_client(panels=frozenset())
    assert client.get("/admin/technicians").status_code == 403


def test_companies_happy_narrow_panel_grants_access() -> None:
    client = _companies_client(panels=frozenset({AdminPanel.COMPANIES}))
    assert client.get("/admin/companies").status_code == 200


def test_companies_edge_master_data_alone_denied() -> None:
    client = _companies_client(panels=frozenset({AdminPanel.MASTER_DATA}))
    assert client.get("/admin/companies").status_code == 403


def test_companies_error_no_panel_denied() -> None:
    client = _companies_client(panels=frozenset())
    assert client.get("/admin/companies").status_code == 403


def test_matrix_catalog_happy_narrow_panel_grants_access() -> None:
    client = _sku_catalog_client(panels=frozenset({AdminPanel.MATRIX_SKU_CATALOG}))
    assert client.get("/admin/matrix-sku-catalog").status_code == 200


def test_matrix_catalog_edge_master_data_alone_denied() -> None:
    client = _sku_catalog_client(panels=frozenset({AdminPanel.MASTER_DATA}))
    assert client.get("/admin/matrix-sku-catalog").status_code == 403


def test_matrix_catalog_error_no_panel_denied() -> None:
    client = _sku_catalog_client(panels=frozenset())
    assert client.get("/admin/matrix-sku-catalog").status_code == 403
