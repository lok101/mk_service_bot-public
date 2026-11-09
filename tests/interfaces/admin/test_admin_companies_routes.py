from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests._company_roles_for_panels import company_roles_for_test_panels

from src.application.master_data import (
    CreateCompany,
    InMemoryCompanyStore,
    InMemoryMasterDataAuditStore,
    InMemoryMasterDataCounterStore,
    InMemorySystemUserStore,
    KitPlatform,
    KitPlatformBinding,
    KitPlatformRole,
    MasterCompany,
    SystemUserRecord,
    UpdateCompany,
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

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_FROZEN_NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
_ORIGIN = {"origin": "http://testserver"}


@dataclass(frozen=True, slots=True)
class _CompaniesApp:
    client: TestClient
    deps: AdminHttpDeps
    store: InMemoryCompanyStore


def _login(client: TestClient, telegram_user_id: int = _ADMIN_TG) -> None:
    response = client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(telegram_user_id)},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}


def _build_companies_app(
    *,
    companies_enabled: bool,
    panels: frozenset[AdminPanel],
) -> _CompaniesApp:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Иван"]],
    )
    roster_store = InMemoryLocationRosterStore()
    provider.configure_roster(enabled=True, store=roster_store)
    user = SystemUser(
        user_id=SystemUserId("1"),
        name="Ops",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=_ADMIN_TG,
        technician_id=None,
        company_roles=company_roles_for_test_panels(panels),
    )
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
    store = InMemoryCompanyStore()
    counters = InMemoryMasterDataCounterStore()
    audit = InMemoryMasterDataAuditStore()
    create = None
    update = None
    display_names: dict[int, str] = {}

    def _refresh() -> None:
        display_names.clear()
        display_names.update(
            {c.company_id: c.name.strip() for c in store.list_all() if c.is_active},
        )

    if companies_enabled:
        create = CreateCompany(store=store, counters=counters, audit=audit)
        update = UpdateCompany(store=store, audit=audit)
        _refresh()
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
        users_enabled=True,
        system_user_store=system_user_store,
        companies_enabled=companies_enabled,
        company_store=store if companies_enabled else None,
        create_company=create,
        update_company=update,
        company_display_names=display_names if companies_enabled else None,
        refresh_company_display_names=_refresh if companies_enabled else None,
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return _CompaniesApp(client=TestClient(app), deps=deps, store=store)


def test_companies_routes_404_when_disabled() -> None:
    built = _build_companies_app(
        companies_enabled=False,
        panels=frozenset({AdminPanel.USERS}),
    )
    assert built.client.get("/admin/companies").status_code == 404


def test_companies_list_default_active_only() -> None:
    built = _build_companies_app(
        companies_enabled=True,
        panels=frozenset({AdminPanel.COMPANIES, AdminPanel.ROSTER}),
    )
    built.store.upsert(MasterCompany(company_id=1, name="Актив", is_active=True))
    built.store.upsert(MasterCompany(company_id=2, name="Архив", is_active=False))
    _login(built.client)
    html = built.client.get("/admin/companies").text
    assert "<td>Актив</td>" in html
    assert "<td>Архив</td>" not in html


def test_companies_list_filter_inactive() -> None:
    built = _build_companies_app(
        companies_enabled=True,
        panels=frozenset({AdminPanel.COMPANIES, AdminPanel.ROSTER}),
    )
    built.store.upsert(MasterCompany(company_id=1, name="Актив", is_active=True))
    built.store.upsert(MasterCompany(company_id=2, name="Архив", is_active=False))
    _login(built.client)
    html = built.client.get("/admin/companies?status=inactive").text
    assert "<td>Архив</td>" in html
    assert "<td>Актив</td>" not in html


def test_companies_list_has_no_save_bar() -> None:
    built = _build_companies_app(
        companies_enabled=True,
        panels=frozenset({AdminPanel.COMPANIES, AdminPanel.ROSTER}),
    )
    _login(built.client)
    html = built.client.get("/admin/companies").text
    assert "admin-save-bar" not in html


def test_company_new_has_admin_save_bar() -> None:
    built = _build_companies_app(
        companies_enabled=True,
        panels=frozenset({AdminPanel.COMPANIES, AdminPanel.ROSTER}),
    )
    _login(built.client)
    html = built.client.get("/admin/companies/new").text
    assert "admin-save-bar" in html


def test_company_edit_has_admin_save_bar() -> None:
    built = _build_companies_app(
        companies_enabled=True,
        panels=frozenset({AdminPanel.COMPANIES, AdminPanel.ROSTER}),
    )
    built.store.upsert(MasterCompany(company_id=1, name="A", is_active=True))
    _login(built.client)
    html = built.client.get("/admin/companies/1").text
    assert "admin-save-bar" in html


def test_companies_create_post_happy_refreshes_display_names() -> None:
    built = _build_companies_app(
        companies_enabled=True,
        panels=frozenset({AdminPanel.USERS}),
    )
    _login(built.client)
    assert built.deps.company_display_names is not None
    built.deps.company_display_names.clear()
    response = built.client.post(
        "/admin/companies/new",
        data={"name": "Ромашка"},
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    assert "/admin/companies/" in response.headers["location"]
    assert 1 in built.deps.company_display_names
    assert built.deps.company_display_names[1] == "Ромашка"


def test_companies_create_rejects_second_sales_poll() -> None:
    built = _build_companies_app(
        companies_enabled=True,
        panels=frozenset({AdminPanel.USERS}),
    )
    built.store.upsert(
        MasterCompany(
            company_id=1,
            name="Existing",
            is_active=True,
            platform_bindings=(
                KitPlatformBinding(
                    platform=KitPlatform.KIT_VENDING,
                    kit_company_id=10,
                    roles=(KitPlatformRole.SALES_POLL, KitPlatformRole.CATALOG),
                ),
            ),
        ),
    )
    _login(built.client)
    response = built.client.post(
        "/admin/companies/new",
        data={
            "name": "New",
            "platform-0": "kit_vending",
            "kit_company_id-0": "11",
            "role-sales_poll-0": "on",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "admin-error" in response.text


def test_companies_create_rejects_duplicate_binding() -> None:
    built = _build_companies_app(
        companies_enabled=True,
        panels=frozenset({AdminPanel.USERS}),
    )
    built.store.upsert(
        MasterCompany(
            company_id=1,
            name="Existing",
            is_active=True,
            platform_bindings=(
                KitPlatformBinding(
                    platform=KitPlatform.KIT_VENDING,
                    kit_company_id=10,
                    roles=(KitPlatformRole.CATALOG,),
                ),
            ),
        ),
    )
    _login(built.client)
    response = built.client.post(
        "/admin/companies/new",
        data={
            "name": "New",
            "platform-0": "kit_vending",
            "kit_company_id-0": "10",
            "role-catalog-0": "on",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "admin-error" in response.text


def test_companies_unknown_id_returns_404() -> None:
    built = _build_companies_app(
        companies_enabled=True,
        panels=frozenset({AdminPanel.USERS}),
    )
    _login(built.client)
    assert built.client.get("/admin/companies/999").status_code == 404


def test_companies_post_rejects_without_companies_panel() -> None:
    built = _build_companies_app(
        companies_enabled=True,
        panels=frozenset({AdminPanel.ROSTER, AdminPanel.VISIT_BOARD, AdminPanel.MASTER_DATA}),
    )
    _login(built.client)
    response = built.client.post(
        "/admin/companies/new",
        data={"name": "X"},
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_companies_post_rejects_bad_origin() -> None:
    built = _build_companies_app(
        companies_enabled=True,
        panels=frozenset({AdminPanel.USERS}),
    )
    _login(built.client)
    response = built.client.post(
        "/admin/companies/new",
        data={"name": "X"},
        headers={"origin": "https://evil.example"},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_nav_companies_item_when_companies_enabled() -> None:
    built = _build_companies_app(
        companies_enabled=True,
        panels=frozenset({AdminPanel.COMPANIES, AdminPanel.ROSTER}),
    )
    _login(built.client)
    html = built.client.get("/admin/companies").text
    assert 'href="/admin/companies"' in html
    assert "Компании" in html


def test_companies_update_bindings_post_happy() -> None:
    built = _build_companies_app(
        companies_enabled=True,
        panels=frozenset({AdminPanel.USERS}),
    )
    built.store.upsert(MasterCompany(company_id=1, name="A", is_active=True))
    _login(built.client)
    response = built.client.post(
        "/admin/companies/1",
        data={
            "name": "A2",
            "is_active": "on",
            "platform-0": "kit_shop",
            "kit_company_id-0": "5",
            "role-default-0": "on",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    updated = built.store.get(1)
    assert updated is not None
    assert updated.name == "A2"
    assert updated.platform_bindings[0].platform is KitPlatform.KIT_SHOP
    assert updated.platform_bindings[0].kit_company_id == 5


def test_companies_list_get_offloads_store_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # happy
    calls: list[object] = []
    real = asyncio.to_thread

    async def recording(func, /, *args, **kwargs):
        calls.append(func)
        return await real(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", recording)
    app = _build_companies_app(
        companies_enabled=True,
        panels=frozenset({AdminPanel.USERS}),
    )
    _login(app.client)
    response = app.client.get("/admin/companies")
    assert response.status_code == 200
    assert calls, "GET list must call asyncio.to_thread"


def test_company_edit_get_offloads_store_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # happy
    calls: list[object] = []
    real = asyncio.to_thread

    async def recording(func, /, *args, **kwargs):
        calls.append(func)
        return await real(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", recording)
    app = _build_companies_app(
        companies_enabled=True,
        panels=frozenset({AdminPanel.USERS}),
    )
    company_id = 1
    app.store.upsert(MasterCompany(company_id=company_id, name="A", is_active=True))
    _login(app.client)
    response = app.client.get(f"/admin/companies/{company_id}")
    assert response.status_code == 200
    assert calls
