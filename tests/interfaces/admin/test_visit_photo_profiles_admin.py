from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests._company_roles_for_panels import company_roles_for_test_panels

from src.application.master_data import (
    CoffeeMachineModel,
    InMemoryCoffeeMachineModelStore,
    InMemoryMasterDataCounterStore,
    InMemoryMasterDataStores,
    InMemoryStandTypeStore,
    InMemorySystemUserStore,
    SaveSystemUsers,
    StandType,
    SystemUserRecord,
)
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.sheets import SystemUsersSnapshot
from src.application.visit_photo_review.profile import (
    InMemoryVisitPhotoProfileStore,
    SaveVisitPhotoProfile,
    VisitPhotoProfileMember,
)
from src.domain.system_user import AdminPanel, BotRole, SystemUser, SystemUserId
from src.infrastructure.composition.adapters.visit_photo_profile_lookup import (
    MasterCoffeeEquipmentCatalogLookup,
)
from src.infrastructure.visit_photo_review.profile_storage import (
    FilesystemVisitPhotoProfileTechRefStorage,
)
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes
from src.interfaces.admin.session import admin_session_cookie_name, pack_admin_session

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_FROZEN_NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
_ORIGIN = {"Origin": "http://testserver"}


def _build(tmp_path: Path) -> tuple[FastAPI, AdminHttpDeps, InMemoryVisitPhotoProfileStore]:
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
        company_roles=company_roles_for_test_panels(
            frozenset({AdminPanel.VISIT_PHOTO_REVIEW}),
        ),
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
    models = InMemoryCoffeeMachineModelStore()
    models.upsert(
        CoffeeMachineModel(model_id="m-g23", name="G23", floor_standing=False),
    )
    models.upsert(
        CoffeeMachineModel(model_id="m-jl220", name="JL220", floor_standing=True),
    )
    stands = InMemoryStandTypeStore()
    stands.upsert(StandType(stand_type_id="st-new", name="Новая"))
    store = InMemoryVisitPhotoProfileStore()
    save = SaveVisitPhotoProfile(
        store=store,
        catalog=MasterCoffeeEquipmentCatalogLookup(models=models, stand_types=stands),
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
        master_stores=InMemoryMasterDataStores(),
        coffee_machine_model_store=models,
        stand_type_store=stands,
        users_enabled=True,
        system_user_store=system_user_store,
        save_system_users=SaveSystemUsers(
            store=system_user_store,
            counters=InMemoryMasterDataCounterStore(),
        ),
        visit_photo_review_enabled=True,
        visit_photo_profile_store=store,
        save_visit_photo_profile=save,
        visit_photo_profile_tech_ref_storage=FilesystemVisitPhotoProfileTechRefStorage(
            tmp_path / "tech-refs",
        ),
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return app, deps, store


def _login(client: TestClient) -> None:
    token = pack_admin_session(
        telegram_user_id=_ADMIN_TG,
        issued_at=int(_FROZEN_NOW.timestamp()),
        secret=_SESSION_SECRET,
    )
    client.cookies.set(admin_session_cookie_name(), token)


def test_create_sets_pack_key_to_profile_id(tmp_path: Path) -> None:
    app, _deps, store = _build(tmp_path)
    client = TestClient(app)
    _login(client)

    create = client.post(
        "/admin/visit-photo-profiles/new",
        data={
            "name": "Новая G23",
            "pack_key": "forged-key",
            "content_group_id-0": "",
            "content_group_title-0": "1. A",
            "content_group_id-1": "",
            "content_group_title-1": "2. B",
            "member_model_id-0": "m-g23",
            "member_stand_type_id-0": "st-new",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert create.status_code == 303
    location = create.headers["location"]
    assert location.startswith("/admin/visit-photo-profiles/")
    profile_id = location.rsplit("/", 1)[-1]
    profile = store.get(profile_id)
    assert profile is not None
    assert profile.pack_key == profile_id

    opened = client.get(location)
    assert opened.status_code == 200
    assert "Новая G23" in opened.text
    assert 'name="pack_key"' not in opened.text
    assert "1. A" in opened.text
    assert "Чеклист (по одному пункту в строке)" not in opened.text
    assert "Группы фото" in opened.text


def test_edit_preserves_existing_pack_key(tmp_path: Path) -> None:
    app, deps, store = _build(tmp_path)
    assert deps.save_visit_photo_profile is not None
    deps.save_visit_photo_profile(
        profile_id="p-legacy",
        name="Legacy",
        members=frozenset(
            {VisitPhotoProfileMember(model_id="m-jl220", stand_type_id=None)},
        ),
        checklist_items=("1. До",),
        pack_key="shared-pack",
    )
    client = TestClient(app)
    _login(client)
    response = client.post(
        "/admin/visit-photo-profiles/p-legacy",
        data={
            "name": "Legacy renamed",
            "pack_key": "should-ignore",
            "content_group_id-0": "",
            "content_group_title-0": "1. До",
            "content_group_id-1": "",
            "content_group_title-1": "2. После",
            "member_model_id-0": "m-jl220",
            "member_stand_type_id-0": "",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303
    updated = store.get("p-legacy")
    assert updated is not None
    assert updated.pack_key == "shared-pack"
    assert updated.name == "Legacy renamed"


def test_list_and_new_hide_pack_key_field(tmp_path: Path) -> None:
    app, deps, _store = _build(tmp_path)
    assert deps.save_visit_photo_profile is not None
    deps.save_visit_photo_profile(
        profile_id="p1",
        name="Shown",
        members=frozenset(
            {VisitPhotoProfileMember(model_id="m-g23", stand_type_id="st-new")},
        ),
        checklist_items=("1. A",),
        pack_key="hidden-key",
    )
    client = TestClient(app)
    _login(client)
    listing = client.get("/admin/visit-photo-profiles")
    assert listing.status_code == 200
    assert ">pack_key<" not in listing.text
    assert "hidden-key" not in listing.text
    assert "Shown" in listing.text
    new_page = client.get("/admin/visit-photo-profiles/new")
    assert new_page.status_code == 200
    assert 'name="pack_key"' not in new_page.text


def test_editor_shows_members(tmp_path: Path) -> None:
    app, deps, store = _build(tmp_path)
    assert deps.save_visit_photo_profile is not None
    profile = deps.save_visit_photo_profile(
        profile_id="p-edit",
        name="JL220 floor",
        members=frozenset(
            {VisitPhotoProfileMember(model_id="m-jl220", stand_type_id=None)},
        ),
        checklist_items=("1. До", "2. После"),
        pack_key="jl220",
    )
    client = TestClient(app)
    _login(client)
    html = client.get(f"/admin/visit-photo-profiles/{profile.profile_id}").text
    assert "JL220 floor" in html
    assert 'value="m-jl220"' in html
    assert "selected" in html
    assert store.get("p-edit") is not None


def test_overlap_rejects_with_error(tmp_path: Path) -> None:
    app, deps, _store = _build(tmp_path)
    assert deps.save_visit_photo_profile is not None
    deps.save_visit_photo_profile(
        profile_id="p1",
        name="First",
        members=frozenset(
            {VisitPhotoProfileMember(model_id="m-g23", stand_type_id="st-new")},
        ),
        checklist_items=("1. A",),
        pack_key="a",
    )
    client = TestClient(app)
    _login(client)
    response = client.post(
        "/admin/visit-photo-profiles/new",
        data={
            "name": "Second",
            "content_group_id-0": "",
            "content_group_title-0": "1. B",
            "member_model_id-0": "m-g23",
            "member_stand_type_id-0": "st-new",
        },
        headers=_ORIGIN,
    )
    assert response.status_code == 400
    assert "Членство пересекается с другим профилем" in response.text


def test_profile_editor_shows_groups_list_not_checklist_textarea(tmp_path: Path) -> None:
    app, _deps, _store = _build(tmp_path)
    client = TestClient(app)
    _login(client)
    html = client.get("/admin/visit-photo-profiles/new").text
    assert "Группы фото" in html
    assert "Чеклист (по одному пункту в строке)" not in html
    assert 'name="content_group_title-0"' in html


def test_groups_tab_absent_on_review_panel(tmp_path: Path) -> None:
    app, _deps, _store = _build(tmp_path)
    client = TestClient(app)
    _login(client)
    # Review panel is separate; smoke that profiles editor path stays free of groups tab chrome.
    html = client.get("/admin/visit-photo-profiles").text
    assert 'data-tab="groups"' not in html


def test_save_profile_rejects_without_content_groups(tmp_path: Path) -> None:
    app, _deps, _store = _build(tmp_path)
    client = TestClient(app)
    _login(client)
    response = client.post(
        "/admin/visit-photo-profiles/new",
        data={
            "name": "Empty groups",
            "pack_key": "x",
            "content_group_id-0": "",
            "content_group_title-0": "",
            "member_model_id-0": "m-g23",
            "member_stand_type_id-0": "st-new",
        },
        headers=_ORIGIN,
    )
    assert response.status_code == 400
    assert "содержательную группу" in response.text
