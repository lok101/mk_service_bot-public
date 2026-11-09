from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.master_data import (
    CoffeeEquipmentCatalogs,
    CoffeeEquipmentCommands,
    InMemoryCoffeeMachineModelStore,
    InMemoryMasterDataStores,
    InMemoryStandColorStore,
    InMemoryStandTypeStore,
    MachineKind,
    MachineStatus,
    MasterMachine,
)
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.domain.ids import MachineId
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_FROZEN_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
_ORIGIN = {"Origin": "http://testserver"}


def _widget_fields() -> dict[str, str]:
    from tests.interfaces.admin.test_master_data_routes import _signed_widget_fields

    return _signed_widget_fields(tg=_ADMIN_TG, auth_date=str(int(_FROZEN_NOW.timestamp())))


def _build() -> tuple[FastAPI, AdminHttpDeps, CoffeeEquipmentCatalogs]:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.BOT_USERS,
        [
            ["Id", "Имя", "Роль", "телеграм id", "Id техника", "is active"],
            ["u1", "Ops", "администратор", str(_ADMIN_TG), "", "да"],
        ],
    )
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
    stores = InMemoryMasterDataStores()
    catalogs = CoffeeEquipmentCatalogs(
        models=InMemoryCoffeeMachineModelStore(),
        stand_types=InMemoryStandTypeStore(),
        stand_colors=InMemoryStandColorStore(),
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
        stub_login_enabled=False,
        timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
        now_factory=lambda: _FROZEN_NOW,
        master_stores=stores,
        coffee_machine_model_store=catalogs.models,
        stand_type_store=catalogs.stand_types,
        stand_color_store=catalogs.stand_colors,
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return app, deps, catalogs


def _login(client: TestClient) -> None:
    response = client.post(
        "/admin/auth/telegram",
        data=_widget_fields(),
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}


def _seed(deps: AdminHttpDeps, kind: MachineKind, machine_id: str) -> None:
    assert deps.master_stores is not None
    deps.master_stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId(machine_id),
            kind=kind,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )


def test_catalog_list_saves_model_and_park_links_to_it() -> None:
    app, _deps, catalogs = _build()
    client = TestClient(app)
    _login(client)
    park = client.get("/admin/machines")
    assert park.status_code == 200
    assert 'href="/admin/coffee-machine-models"' in park.text
    created = client.post(
        "/admin/coffee-machine-models",
        data={"intent": "create", "name": "Jetinno", "floor_standing": "on"},
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert created.status_code == 303
    page = client.get("/admin/coffee-machine-models")
    assert page.status_code == 200
    assert "Jetinno" in page.text
    assert catalogs.models.list_all()[0].floor_standing is True


def test_coffee_profile_hides_stand_for_floor_model() -> None:
    app, deps, catalogs = _build()
    assert deps.master_stores is not None
    commands = CoffeeEquipmentCommands(
        stores=deps.master_stores,
        catalogs=catalogs,
        now_factory=lambda: _FROZEN_NOW,
    )
    model = commands.create_model(name="Напольная", floor_standing=True, actor_telegram_user_id=1)
    commands.create_stand_type(name="Старый", actor_telegram_user_id=1)
    _seed(deps, MachineKind.COFFEE, "101")
    machine = deps.master_stores.machines.get(MachineId("101"))
    assert machine is not None
    from dataclasses import replace

    deps.master_stores.machines.upsert(replace(machine, coffee_machine_model_id=model.model_id))
    client = TestClient(app)
    _login(client)
    page = client.get("/admin/machines/101")
    assert page.status_code == 200
    assert 'name="coffee_machine_model_id"' in page.text
    assert 'id="coffee-stand-fields" hidden' in page.text
    response = client.post(
        "/admin/machines/101",
        data={
            "include_in_no_sales_monitoring": "on",
            "create_visit_on_no_sales": "on",
            "include_in_visit_photo_review": "on",
            "coffee_machine_model_id": model.model_id,
            "stand_type_id": "1",
            "stand_color_id": "1",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303
    saved = deps.master_stores.machines.get(MachineId("101"))
    assert saved is not None
    assert saved.coffee_machine_model_id == model.model_id
    assert saved.stand_type_id is None
    assert saved.stand_color_id is None


def test_snack_profile_has_no_catalog_choices() -> None:
    app, deps, _catalogs = _build()
    _seed(deps, MachineKind.SNACK, "501")
    client = TestClient(app)
    _login(client)
    page = client.get("/admin/machines/501")
    assert page.status_code == 200
    assert 'name="coffee_machine_model_id"' not in page.text
    assert 'name="stand_type_id"' not in page.text
    assert 'name="stand_color_id"' not in page.text
