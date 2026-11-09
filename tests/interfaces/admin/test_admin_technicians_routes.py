from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests._company_roles_for_panels import company_roles_for_test_panels

from src.application.master_data import (
    CreateTechnician,
    InMemoryMasterDataAuditStore,
    InMemoryMasterDataCounterStore,
    InMemorySystemUserStore,
    InMemoryTechnicianStore,
    SaveFieldStaff,
    SaveSystemUsers,
    SystemUserRecord,
    Technician,
    UpdateTechnician,
)
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster import LocationRosterEntry
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.sheets import SystemUsersSnapshot
from src.domain.ids import MachineId, TechnicianId
from src.domain.system_user import AdminPanel, BotRole, CompanyRole, SystemUser, SystemUserId
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_USERS_ADMIN_TG = 9999
_FROZEN_NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
_ORIGIN = {"origin": "http://testserver"}


@dataclass(frozen=True, slots=True)
class _TechniciansApp:
    client: TestClient
    deps: AdminHttpDeps


def _login(client: TestClient, telegram_user_id: int = _ADMIN_TG) -> None:
    response = client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(telegram_user_id)},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}


def _build_technicians_app(
    *,
    technicians_enabled: bool,
    panels: frozenset[AdminPanel],
    telegram_user_id: int = _ADMIN_TG,
    wire_field_staff: bool = True,
) -> _TechniciansApp:
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
    users_admin = SystemUser(
        user_id=SystemUserId("99"),
        name="UsersAdmin",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=_USERS_ADMIN_TG,
        technician_id=None,
        company_roles=frozenset({CompanyRole.ACCESS_ADMINISTRATOR}),
    )
    provider.apply_system_users_snapshot(
        SystemUsersSnapshot(
            users_by_telegram_id={
                telegram_user_id: user,
                _USERS_ADMIN_TG: users_admin,
            },
            users_by_technician_id={},
        ),
    )
    system_user_store = InMemorySystemUserStore()
    system_user_store.replace_all(
        (
            SystemUserRecord(
                user=user,
                updated_at=_FROZEN_NOW,
                updated_by_telegram_user_id=telegram_user_id,
            ),
            SystemUserRecord(
                user=users_admin,
                updated_at=_FROZEN_NOW,
                updated_by_telegram_user_id=_USERS_ADMIN_TG,
            ),
        ),
    )
    technician_store = InMemoryTechnicianStore() if technicians_enabled else None
    counters = InMemoryMasterDataCounterStore()
    audit = InMemoryMasterDataAuditStore()
    create = (
        None
        if technician_store is None
        else CreateTechnician(store=technician_store, counters=counters, audit=audit)
    )
    update = (
        None if technician_store is None else UpdateTechnician(store=technician_store, audit=audit)
    )
    save_field_staff = None
    if wire_field_staff and technician_store is not None and system_user_store is not None:
        save_field_staff = SaveFieldStaff(
            save_system_users=SaveSystemUsers(store=system_user_store, counters=counters),
            create_technician=create,
            update_technician=update,
            technician_store=technician_store,
            technicians_enabled=technicians_enabled,
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
        users_enabled=True,
        system_user_store=system_user_store,
        technicians_enabled=technicians_enabled,
        technician_store=technician_store,
        create_technician=create,
        update_technician=update,
        save_field_staff=save_field_staff,
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return _TechniciansApp(client=TestClient(app), deps=deps)


def test_technicians_routes_404_when_disabled() -> None:
    built = _build_technicians_app(
        technicians_enabled=False,
        panels=frozenset({AdminPanel.TECHNICIANS, AdminPanel.ROSTER}),
    )
    assert built.client.get("/admin/technicians").status_code == 404


def test_technicians_form_has_no_panel_columns() -> None:
    built = _build_technicians_app(
        technicians_enabled=True,
        panels=frozenset({AdminPanel.TECHNICIANS, AdminPanel.ROSTER}),
    )
    _login(built.client)
    html = built.client.get("/admin/technicians").text
    assert "panel_roster" not in html
    assert 'name="panel_' not in html


def test_technicians_post_creates_field_staff_pair() -> None:
    built = _build_technicians_app(
        technicians_enabled=True,
        panels=frozenset({AdminPanel.TECHNICIANS, AdminPanel.ROSTER}),
    )
    _login(built.client)
    response = built.client.post(
        "/admin/technicians",
        data={
            "name-0": "Новый",
            "telegram_user_id-0": "9001",
            "bot_role-0": BotRole.TECHNICIAN.value,
            "technician_is_active-0": "on",
            "is_active-0": "on",
            "technician_id-0": "",
            "user_id-0": "",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code in {303, 302}
    tech_store = built.deps.technician_store
    user_store = built.deps.system_user_store
    assert tech_store is not None
    assert user_store is not None
    techs = tech_store.list_all()
    assert len(techs) == 1
    assert techs[0].name == "Новый"
    field = user_store.get(9001)
    assert field is not None
    assert field.user.technician_id == techs[0].technician_id
    assert field.user.panels == frozenset()


def test_technicians_post_rejects_without_technicians_panel() -> None:
    built = _build_technicians_app(
        technicians_enabled=True,
        panels=frozenset({AdminPanel.ROSTER, AdminPanel.VISIT_BOARD, AdminPanel.MASTER_DATA}),
    )
    _login(built.client)
    response = built.client.post(
        "/admin/technicians",
        data={"name": "Новый"},
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_technicians_create_post_happy() -> None:
    built = _build_technicians_app(
        technicians_enabled=True,
        panels=frozenset({AdminPanel.TECHNICIANS, AdminPanel.ROSTER}),
    )
    _login(built.client)
    response = built.client.post(
        "/admin/technicians",
        data={
            "name-0": "Новый",
            "telegram_user_id-0": "9002",
            "bot_role-0": BotRole.TECHNICIAN.value,
            "technician_is_active-0": "on",
            "is_active-0": "on",
            "technician_id-0": "",
            "user_id-0": "",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code in {303, 302}
    names = built.deps.provider.technicians_directory().names_by_id
    assert any(name == "Новый" for name in names.values())


def test_technicians_create_hydrate_failure_returns_500(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    built = _build_technicians_app(
        technicians_enabled=True,
        panels=frozenset({AdminPanel.TECHNICIANS, AdminPanel.ROSTER}),
    )
    _login(built.client)
    monkeypatch.setattr(
        "src.interfaces.admin.routes.technicians._refresh_provider_technicians",
        lambda _deps: (_ for _ in ()).throw(RuntimeError("hydrate boom")),
    )
    with caplog.at_level(logging.ERROR):
        response = built.client.post(
            "/admin/technicians",
            data={
                "name-0": "Новый",
                "telegram_user_id-0": "9003",
                "bot_role-0": BotRole.TECHNICIAN.value,
                "technician_is_active-0": "on",
                "is_active-0": "on",
                "technician_id-0": "",
                "user_id-0": "",
            },
            headers=_ORIGIN,
            follow_redirects=False,
        )
    assert response.status_code == 500
    assert "admin_technicians_hydrate_failed" in caplog.text


def test_technicians_deactivate_post_happy() -> None:
    built = _build_technicians_app(
        technicians_enabled=True,
        panels=frozenset({AdminPanel.TECHNICIANS, AdminPanel.ROSTER}),
    )
    store = built.deps.technician_store
    assert store is not None
    technician_id = TechnicianId("7")
    store.upsert(Technician(technician_id=technician_id, name="Данил", is_active=True))
    _login(built.client)
    response = built.client.post(
        "/admin/technicians/7",
        data={"name": "Данил"},
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code in {303, 302}
    updated = store.get(technician_id)
    assert updated is not None
    assert updated.is_active is False


def test_technicians_page_has_admin_save_bar() -> None:
    built = _build_technicians_app(
        technicians_enabled=True,
        panels=frozenset({AdminPanel.TECHNICIANS, AdminPanel.ROSTER}),
    )
    _login(built.client)
    html = built.client.get("/admin/technicians").text
    assert "admin-save-bar" in html


def _seed_active_and_inactive(store: InMemoryTechnicianStore) -> None:
    store.upsert(
        Technician(technician_id=TechnicianId("11"), name="Смирнов-актив", is_active=True),
    )
    store.upsert(
        Technician(technician_id=TechnicianId("12"), name="Козлов-архив", is_active=False),
    )


def test_technicians_list_default_active_only() -> None:
    built = _build_technicians_app(
        technicians_enabled=True,
        panels=frozenset({AdminPanel.TECHNICIANS, AdminPanel.ROSTER}),
    )
    store = built.deps.technician_store
    assert store is not None
    _seed_active_and_inactive(store)
    _login(built.client)
    html = built.client.get("/admin/technicians").text
    assert "Смирнов-актив" in html
    assert "Козлов-архив" not in html


def test_technicians_list_filter_inactive() -> None:
    built = _build_technicians_app(
        technicians_enabled=True,
        panels=frozenset({AdminPanel.TECHNICIANS, AdminPanel.ROSTER}),
    )
    store = built.deps.technician_store
    assert store is not None
    _seed_active_and_inactive(store)
    _login(built.client)
    inactive_html = built.client.get("/admin/technicians?status=inactive").text
    assert "Козлов-архив" in inactive_html
    assert "Смирнов-актив" not in inactive_html
    all_html = built.client.get("/admin/technicians?status=all").text
    assert "Смирнов-актив" in all_html
    assert "Козлов-архив" in all_html


def test_nav_technicians_item_when_technicians_enabled() -> None:
    built = _build_technicians_app(
        technicians_enabled=True,
        panels=frozenset({AdminPanel.TECHNICIANS, AdminPanel.ROSTER}),
    )
    _login(built.client)
    response = built.client.get("/admin/technicians")
    assert response.status_code == 200
    html = response.text
    assert 'href="/admin/technicians"' in html
    assert ">Техники<" in html or "Техники</" in html


def test_nav_hides_technicians_without_technicians_panel() -> None:
    built = _build_technicians_app(
        technicians_enabled=True,
        panels=frozenset({AdminPanel.ROSTER, AdminPanel.VISIT_BOARD, AdminPanel.MASTER_DATA}),
    )
    _login(built.client)
    html = built.client.get("/admin/roster").text
    assert 'href="/admin/technicians"' not in html


def test_nav_hides_technicians_when_flag_off() -> None:
    built = _build_technicians_app(
        technicians_enabled=False,
        panels=frozenset({AdminPanel.TECHNICIANS, AdminPanel.ROSTER}),
    )
    _login(built.client)
    html = built.client.get("/admin/roster").text
    assert 'href="/admin/technicians"' not in html


def _seed_inactive_technician_still_linked(built: _TechniciansApp) -> None:
    store = built.deps.technician_store
    assert store is not None
    store.upsert(
        Technician(technician_id=TechnicianId("001"), name="Активный", is_active=True),
    )
    store.upsert(
        Technician(technician_id=TechnicianId("002"), name="Неактивный", is_active=False),
    )
    built.deps.provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Активный"], ["002", "Неактивный"]],
    )
    built.deps.provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника"],
            ["101", "Школа", "Неактивный", "002"],
            ["102", "Офис", "Активный", "001"],
        ],
    )
    built.deps.provider.apply_system_users_snapshot(
        SystemUsersSnapshot(
            users_by_telegram_id={
                _ADMIN_TG: SystemUser(
                    user_id=SystemUserId("1"),
                    name="Ops",
                    role=BotRole.ADMINISTRATOR,
                    is_active=True,
                    telegram_user_id=_ADMIN_TG,
                    technician_id=None,
                    company_roles=frozenset({CompanyRole.ACCESS_ADMINISTRATOR}),
                ),
                10: SystemUser(
                    user_id=SystemUserId("10"),
                    name="Linked-inactive",
                    role=BotRole.TECHNICIAN,
                    is_active=True,
                    telegram_user_id=10,
                    technician_id=TechnicianId("002"),
                    company_roles=frozenset(),
                ),
                11: SystemUser(
                    user_id=SystemUserId("11"),
                    name="Linked-active",
                    role=BotRole.TECHNICIAN,
                    is_active=True,
                    telegram_user_id=11,
                    technician_id=TechnicianId("001"),
                    company_roles=frozenset(),
                ),
            },
            users_by_technician_id={},
        ),
    )
    built.deps.roster_store.save_batch(
        (
            LocationRosterEntry(
                machine_id=MachineId("101"),
                technician_id=TechnicianId("002"),
                service_weekdays=frozenset({2}),
                updated_at=_FROZEN_NOW,
                updated_by_telegram_user_id=_ADMIN_TG,
            ),
            LocationRosterEntry(
                machine_id=MachineId("102"),
                technician_id=TechnicianId("001"),
                service_weekdays=frozenset({2}),
                updated_at=_FROZEN_NOW,
                updated_by_telegram_user_id=_ADMIN_TG,
            ),
        ),
        actor_telegram_user_id=_ADMIN_TG,
        at=_FROZEN_NOW,
    )


def test_technicians_post_skips_orphan_without_telegram() -> None:
    built = _build_technicians_app(
        technicians_enabled=True,
        panels=frozenset({AdminPanel.TECHNICIANS, AdminPanel.ROSTER}),
    )
    store = built.deps.technician_store
    assert store is not None
    orphan_id = TechnicianId("orph-1")
    store.upsert(Technician(technician_id=orphan_id, name="Орфан", is_active=True))
    _login(built.client)
    response = built.client.post(
        "/admin/technicians",
        data={
            "name-0": "Орфан",
            "telegram_user_id-0": "",
            "bot_role-0": BotRole.TECHNICIAN.value,
            "technician_is_active-0": "on",
            "technician_id-0": orphan_id.value,
            "user_id-0": "",
            "name-1": "Новый",
            "telegram_user_id-1": "9020",
            "bot_role-1": BotRole.TECHNICIAN.value,
            "technician_is_active-1": "on",
            "is_active-1": "on",
            "technician_id-1": "",
            "user_id-1": "",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code in {303, 302}
    user_store = built.deps.system_user_store
    assert user_store is not None
    orphan = store.get(orphan_id)
    assert orphan is not None
    assert orphan.name == "Орфан"
    linked_to_orphan = tuple(
        record for record in user_store.list_all() if record.user.technician_id == orphan_id
    )
    assert linked_to_orphan == ()
    new_user = user_store.get(9020)
    assert new_user is not None
    assert new_user.user.name == "Новый"
    assert new_user.user.technician_id is not None
    assert new_user.user.technician_id != orphan_id


def test_technicians_post_field_create_with_technicians_panel_only() -> None:
    built = _build_technicians_app(
        technicians_enabled=True,
        panels=frozenset({AdminPanel.USERS}),
    )
    _login(built.client)
    response = built.client.post(
        "/admin/technicians",
        data={
            "name-0": "Полевой",
            "telegram_user_id-0": "9010",
            "bot_role-0": BotRole.TECHNICIAN.value,
            "technician_is_active-0": "on",
            "is_active-0": "on",
            "technician_id-0": "",
            "user_id-0": "",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code in {303, 302}


def test_technicians_post_rejects_without_users_flag_when_needed() -> None:
    built = _build_technicians_app(
        technicians_enabled=True,
        panels=frozenset({AdminPanel.TECHNICIANS, AdminPanel.ROSTER}),
        wire_field_staff=False,
    )
    _login(built.client)
    assert built.client.get("/admin/technicians").status_code == 404


def test_roster_save_rejects_inactive_technician_new_assign() -> None:
    built = _build_technicians_app(
        technicians_enabled=True,
        panels=frozenset({AdminPanel.TECHNICIANS, AdminPanel.ROSTER}),
    )
    _seed_inactive_technician_still_linked(built)
    _login(built.client)

    response = built.client.post(
        "/admin/roster/draft",
        data={"machine_id": "102", "technician-102": "002", "wd-102-2": "on"},
        headers=_ORIGIN,
        follow_redirects=False,
    )

    assert response.status_code == 400
    entry = built.deps.roster_store.get(MachineId("102"))
    assert entry is not None
    assert entry.technician_id == TechnicianId("001")


def test_roster_save_keeps_already_assigned_inactive_technician() -> None:
    built = _build_technicians_app(
        technicians_enabled=True,
        panels=frozenset({AdminPanel.TECHNICIANS, AdminPanel.ROSTER}),
    )
    _seed_inactive_technician_still_linked(built)
    _login(built.client)

    response = built.client.post(
        "/admin/roster/draft",
        data={
            "machine_id": "101",
            "technician-101": "002",
            "wd-101-2": "on",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )

    assert response.status_code == 200
    entry = built.deps.roster_draft_store.get(MachineId("101"))
    assert entry is not None
    assert entry.technician_id == TechnicianId("002")
