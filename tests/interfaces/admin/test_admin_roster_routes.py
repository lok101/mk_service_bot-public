from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from tests.interfaces.admin.test_admin_auth_routes import (
    _ADMIN_TG,
    _STATIC_DIR,
    _admin_rows,
    _build_app,
    _signed_widget_fields,
)

from src.application.reference_data import ReferenceDataSourceId
from src.application.reference_data.location_roster import LocationRosterEntry
from src.application.service_visits import (
    ServiceVisit,
    VisitKind,
    VisitStatus,
)
from src.application.service_visits.visit_ids import scheduled_visit_id
from src.application.sheets import SystemUsersSnapshot
from src.domain.calendar import operational_day
from src.domain.ids import MachineId, TechnicianId
from src.domain.system_user import BotRole, SystemUser, SystemUserId

_DIR_HEADER = [
    "",
    "Создание",
    "Снятие",
    "ТТ",
    "Название",
    "Полное имя",
    "Город",
    "Улица",
    "Дом",
    "Широта",
    "Долгота",
]


def _dir_row(
    location_id: str,
    created: str,
    removed: str,
    machine: str,
    full_name: str,
    *,
    lat: str = "",
    lng: str = "",
) -> list[str]:
    return [
        location_id,
        created,
        removed,
        machine,
        "",
        full_name,
        "",
        "",
        "",
        lat,
        lng,
    ]


def test_roster_get_includes_map_container_hint_and_coord_attrs() -> None:
    app, deps = _build_app()
    deps.provider.apply_rows(
        ReferenceDataSourceId.LOCATIONS_DIRECTORY,
        [
            _DIR_HEADER,
            _dir_row(
                "loc-a",
                "01.06.2026",
                "",
                "101",
                "Школа full",
                lat="55,8",
                lng="49,1",
            ),
        ],
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/roster").text
    assert 'id="roster-map"' in html
    assert 'id="roster-map-legend"' in html
    assert 'data-lat="55.8"' in html
    assert 'data-lng="49.1"' in html
    assert "/admin/static/leaflet.js?v=" in html
    assert "/admin/static/leaflet.css?v=" in html
    assert "/admin/static/roster-map.js?v=" in html
    assert 'id="roster-map-hint"' not in html


def test_roster_get_map_hint_when_directory_missing() -> None:
    app, _deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/roster").text
    assert 'id="roster-map"' in html
    assert 'id="roster-map-hint"' in html
    assert "недоступ" in html.lower() or "каталог" in html.lower()
    assert "data-lat=" not in html
    assert "data-lng=" not in html


def test_roster_get_redirects_without_cookie() -> None:
    app, _deps = _build_app()
    client = TestClient(app)
    response = client.get("/admin/roster", follow_redirects=False)
    assert response.status_code in {302, 303}
    assert "/admin/login" in response.headers["location"]


def test_roster_get_offloads_sync_builder_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    real = asyncio.to_thread

    async def recording(func, /, *args, **kwargs):
        calls.append(func)
        return await real(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", recording)
    app, _deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/roster")
    assert response.status_code == 200
    assert any(getattr(f, "__name__", "") == "build_roster_page_sync" for f in calls)


def test_roster_get_renders_machine_id_from_view_model() -> None:
    app, _deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/roster").text
    assert 'name="technician-101"' in html
    assert "Школа" in html


def test_roster_get_includes_code_column_static_hint_and_data_attrs() -> None:
    app, _deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/roster").text
    assert "/admin/static/admin.css?v=" in html
    assert "/admin/static/roster.js?v=" in html
    assert ">101<" in html or ">101</td>" in html
    assert 'data-machine-id="101"' in html
    assert "data-location-name=" in html
    assert "data-technician-id=" in html
    assert "data-weekdays=" in html
    assert "сохраняются все строки" in html.lower() or "сохраняется вся" in html.lower()
    assert 'id="roster-search"' in html
    assert 'id="roster-technician-filter"' in html
    assert 'id="roster-weekday-filter"' in html
    assert 'id="roster-visible-count"' in html
    assert 'action="/admin/logout"' in html


def test_roster_get_keeps_all_row_inputs_in_form_dom() -> None:
    app, deps = _build_app()
    deps.provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника"],
            ["101", "Школа", "Иван", "001"],
            ["202", "Офис", "", ""],
        ],
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/roster").text
    assert 'name="technician-101"' in html
    assert 'name="technician-202"' in html
    assert 'name="wd-101-0"' in html or 'name="wd-101-1"' in html or "wd-101-" in html
    assert "wd-202-" in html


def test_roster_get_has_admin_save_bar_with_submit_on_right() -> None:
    """happy: primary save в .admin-save-bar внутри #roster-form."""
    app, _deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())  # session bootstrap
    html = client.get("/admin/roster").text
    assert 'id="roster-form"' in html
    assert "admin-save-bar" in html
    bar_idx = html.find("admin-save-bar")
    save_idx = html.find(">Применить<", bar_idx)
    assert bar_idx != -1
    assert save_idx != -1
    form_end = html.find("</form>", bar_idx)
    assert form_end != -1 and save_idx < form_end


def test_roster_logout_submit_not_inside_admin_save_bar() -> None:
    """edge: logout остаётся в header, не на save bar."""
    app, _deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())  # session bootstrap
    html = client.get("/admin/roster").text
    logout_idx = html.find('action="/admin/logout"')
    bar_idx = html.find("admin-save-bar")
    assert logout_idx != -1
    assert bar_idx != -1
    assert logout_idx < bar_idx


def test_roster_get_weekday_cells_wrap_checkbox_in_hit_target() -> None:
    """happy: weekday td uses hit-target label around wd-* checkbox."""
    app, _deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/roster").text
    assert "admin-roster-weekday" in html
    assert "admin-roster-weekday-hit" in html
    assert 'name="wd-101-' in html


def test_roster_get_has_unified_roster_chrome() -> None:
    """happy: фильтры в chrome-pin, thead в той же таблице что tbody."""
    app, _deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/roster").text
    assert "admin-roster-chrome" in html
    assert "admin-roster-chrome-pin" in html
    assert 'id="roster-filters"' in html
    assert 'id="roster-table"' in html
    assert "<thead>" in html
    pin_idx = html.find("admin-roster-chrome-pin")
    filters_idx = html.find('id="roster-filters"')
    form_idx = html.find('id="roster-form"')
    table_idx = html.find('id="roster-table"')
    assert pin_idx != -1 and filters_idx != -1 and form_idx != -1 and table_idx != -1
    assert pin_idx < filters_idx < form_idx < table_idx


def test_roster_post_rejects_foreign_origin() -> None:
    app, _deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/roster/draft",
        data={"machine_id": "101", "technician-101": "001"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_roster_draft_post_rejects_foreign_origin() -> None:
    app, _deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/roster/draft",
        data={"machine_id": "101", "technician-101": "001"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_roster_post_allows_https_origin_when_app_sees_http() -> None:
    app, deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    client.get("/admin/roster")
    draft = deps.roster_draft_store.get(MachineId("101"))
    assert draft is not None
    deps.roster_draft_store.upsert(
        LocationRosterEntry(
            machine_id=MachineId("101"),
            technician_id=TechnicianId("001"),
            service_weekdays=frozenset({2}),
            updated_at=deps.now_factory(),
            updated_by_telegram_user_id=_ADMIN_TG,
        ),
        expected_updated_at=draft.updated_at,
    )
    updated = deps.roster_draft_store.get(MachineId("101"))
    assert updated is not None
    response = client.post(
        "/admin/roster/apply",
        data={"expected_draft_updated_at-101": updated.updated_at.isoformat()},
        headers={"Origin": "https://testserver", "Host": "testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/roster"
    entry = deps.roster_store.get(MachineId("101"))
    assert entry is not None
    assert entry.technician_id == TechnicianId("001")


def test_roster_get_renders_draft_not_applied() -> None:
    app, deps = _build_app()
    now = deps.now_factory()
    deps.roster_store.save_batch(
        (
            LocationRosterEntry(
                machine_id=MachineId("101"),
                technician_id=TechnicianId("001"),
                service_weekdays=frozenset({1}),
                updated_at=now,
                updated_by_telegram_user_id=_ADMIN_TG,
            ),
        ),
        actor_telegram_user_id=_ADMIN_TG,
        at=now,
    )
    deps.roster_draft_store.upsert(
        LocationRosterEntry(
            machine_id=MachineId("101"),
            technician_id=TechnicianId("002"),
            service_weekdays=frozenset({1}),
            updated_at=now,
            updated_by_telegram_user_id=_ADMIN_TG,
        ),
        expected_updated_at=None,
    )
    deps.provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Иван"], ["002", "Пётр"]],
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    body = client.get("/admin/roster").text
    assert 'name="technician-101"' in body
    assert 'value="002"' in body
    assert "002" in body


def test_roster_get_draft_dirty_flag() -> None:
    app, deps = _build_app()
    now = deps.now_factory()
    deps.roster_store.save_batch(
        (
            LocationRosterEntry(
                machine_id=MachineId("101"),
                technician_id=TechnicianId("001"),
                service_weekdays=frozenset({1}),
                updated_at=now,
                updated_by_telegram_user_id=_ADMIN_TG,
            ),
        ),
        actor_telegram_user_id=_ADMIN_TG,
        at=now,
    )
    deps.roster_draft_store.upsert(
        LocationRosterEntry(
            machine_id=MachineId("101"),
            technician_id=TechnicianId("002"),
            service_weekdays=frozenset({1}),
            updated_at=now,
            updated_by_telegram_user_id=_ADMIN_TG,
        ),
        expected_updated_at=None,
    )
    deps.provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Иван"], ["002", "Пётр"]],
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    body = client.get("/admin/roster").text
    assert 'data-draft-dirty="true"' in body


def test_roster_draft_post_conflict_409() -> None:
    app, deps = _build_app()
    now = deps.now_factory()
    deps.roster_draft_store.upsert(
        LocationRosterEntry(
            machine_id=MachineId("101"),
            technician_id=TechnicianId("001"),
            service_weekdays=frozenset({1}),
            updated_at=now,
            updated_by_telegram_user_id=_ADMIN_TG,
        ),
        expected_updated_at=None,
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/roster/draft",
        data={
            "machine_id": "101",
            "technician-101": "001",
            "wd-101-1": "on",
            "expected_updated_at": "2020-01-01T00:00:00+00:00",
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 409


def test_roster_draft_post_accepts_urlencoded_autosave_body() -> None:
    """happy: roster.js URLSearchParams (urlencoded) — совместим с _form_fields/parse_qs."""
    app, deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    client.get("/admin/roster")
    draft = deps.roster_draft_store.get(MachineId("101"))
    assert draft is not None
    response = client.post(
        "/admin/roster/draft",
        data={
            "machine_id": "101",
            "technician-101": "001",
            "wd-101-2": "on",
            "expected_updated_at": draft.updated_at.isoformat(),
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "updated_at" in payload
    saved = deps.roster_draft_store.get(MachineId("101"))
    assert saved is not None
    assert saved.technician_id == TechnicianId("001")
    assert saved.service_weekdays == frozenset({2})


def test_roster_static_js_autosave_uses_urlencoded_body() -> None:
    """contract: autosave не FormData/multipart — иначе parse_qs на сервере даёт 400."""
    text = (_STATIC_DIR / "roster.js").read_text(encoding="utf-8")
    assert "URLSearchParams" in text
    assert "new FormData" not in text
    assert "/admin/roster/draft" in text


def test_roster_apply_post_saves_and_refreshes() -> None:
    app, deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    client.get("/admin/roster")
    draft = deps.roster_draft_store.get(MachineId("101"))
    assert draft is not None
    deps.roster_draft_store.upsert(
        LocationRosterEntry(
            machine_id=MachineId("101"),
            technician_id=TechnicianId("001"),
            service_weekdays=frozenset({2}),
            updated_at=deps.now_factory(),
            updated_by_telegram_user_id=_ADMIN_TG,
        ),
        expected_updated_at=draft.updated_at,
    )
    updated = deps.roster_draft_store.get(MachineId("101"))
    assert updated is not None
    response = client.post(
        "/admin/roster/apply",
        data={
            "technician-101": "001",
            "wd-101-2": "on",
            "expected_draft_updated_at-101": updated.updated_at.isoformat(),
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/roster"
    entry = deps.roster_store.get(MachineId("101"))
    assert entry is not None
    assert entry.technician_id == TechnicianId("001")
    assert 2 in entry.service_weekdays


def test_roster_apply_when_clean_skips_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    app, deps = _build_app()
    now = deps.now_factory()
    entry = LocationRosterEntry(
        machine_id=MachineId("101"),
        technician_id=TechnicianId("001"),
        service_weekdays=frozenset({1}),
        updated_at=now,
        updated_by_telegram_user_id=_ADMIN_TG,
    )
    deps.roster_store.save_batch((entry,), actor_telegram_user_id=_ADMIN_TG, at=now)
    deps.roster_draft_store.replace_all((entry,))
    calls: list[object] = []
    monkeypatch.setattr(
        "src.interfaces.admin.routes.roster.RefreshScheduledVisitsForRosterChange.execute",
        lambda self, **kwargs: (
            calls.append(kwargs)
            or type(
                "R",
                (),
                {"upserted": 0, "cancelled": 0, "retrospectively_closed": 0},
            )()
        ),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/roster/apply",
        data={
            "technician-101": "001",
            "wd-101-1": "on",
            "expected_draft_updated_at-101": now.isoformat(),
            "expected_applied_updated_at-101": now.isoformat(),
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert calls == []


def test_roster_reset_post_restores_applied() -> None:
    app, deps = _build_app()
    now = deps.now_factory()
    applied = LocationRosterEntry(
        machine_id=MachineId("101"),
        technician_id=TechnicianId("001"),
        service_weekdays=frozenset({0}),
        updated_at=now,
        updated_by_telegram_user_id=_ADMIN_TG,
    )
    deps.roster_store.save_batch(
        (applied,),
        actor_telegram_user_id=_ADMIN_TG,
        at=now,
    )
    deps.roster_draft_store.upsert(
        LocationRosterEntry(
            machine_id=MachineId("101"),
            technician_id=TechnicianId("001"),
            service_weekdays=frozenset({5}),
            updated_at=now,
            updated_by_telegram_user_id=_ADMIN_TG,
        ),
        expected_updated_at=None,
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/roster/reset",
        data={"expected_draft_updated_at-101": now.isoformat()},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    draft = deps.roster_draft_store.get(MachineId("101"))
    assert draft is not None
    assert draft.service_weekdays == frozenset({0})


def test_roster_reset_conflict_redirects_to_roster_with_banner() -> None:
    """error: form Reset conflict → 303 ?conflict=1, не blank HTTP 409 page."""
    app, deps = _build_app()
    now = deps.now_factory()
    deps.roster_draft_store.upsert(
        LocationRosterEntry(
            machine_id=MachineId("101"),
            technician_id=TechnicianId("001"),
            service_weekdays=frozenset({1}),
            updated_at=now,
            updated_by_telegram_user_id=_ADMIN_TG,
        ),
        expected_updated_at=None,
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/roster/reset",
        data={"expected_draft_updated_at-101": "2020-01-01T00:00:00+00:00"},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/roster?conflict=1"
    body = client.get("/admin/roster?conflict=1").text
    assert "конфликт" in body.lower() or "Конфликт" in body


def test_roster_legacy_post_returns_405() -> None:
    app, _deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/roster",
        data={"technician-101": "001"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 405


def test_save_roster_unassign_without_weekday_change_cancels_open() -> None:
    # happy: снятие техника без смены дней снимает open scheduled сегодня
    app, deps = _build_app()
    client = TestClient(app)
    ops_day = operational_day(
        deps.now_factory(),
        deps.timezone,
        deps.day_end_hour,
    )
    machine_id = MachineId("101")
    now = deps.now_factory()
    entry = LocationRosterEntry(
        machine_id=machine_id,
        technician_id=TechnicianId("001"),
        service_weekdays=frozenset({ops_day.weekday()}),
        updated_at=now,
        updated_by_telegram_user_id=_ADMIN_TG,
    )
    deps.roster_store.save_batch(
        (entry,),
        actor_telegram_user_id=_ADMIN_TG,
        at=now,
    )
    deps.roster_draft_store.replace_all((entry,))
    deps.visit_store.upsert(
        ServiceVisit(
            visit_id=scheduled_visit_id(machine_id, ops_day),
            machine_id=machine_id,
            kind=VisitKind.SCHEDULED,
            due_date=ops_day,
            status=VisitStatus.OPEN,
            closable=True,
            priority_boost=False,
            incident_source=None,
            close_type=None,
            completed_at=None,
            completed_by_technician_id=None,
            maintenance_event_id=None,
            created_at=now,
            updated_at=now,
        ),
    )
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    iso = ops_day.weekday()
    deps.roster_draft_store.upsert(
        LocationRosterEntry(
            machine_id=machine_id,
            technician_id=None,
            service_weekdays=frozenset({iso}),
            updated_at=now,
            updated_by_telegram_user_id=_ADMIN_TG,
        ),
        expected_updated_at=now,
    )
    draft = deps.roster_draft_store.get(machine_id)
    assert draft is not None
    response = client.post(
        "/admin/roster/apply",
        data={
            "technician-101": "",
            f"wd-101-{iso}": "on",
            "expected_draft_updated_at-101": draft.updated_at.isoformat(),
            "expected_applied_updated_at-101": now.isoformat(),
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert deps.visit_store.get(scheduled_visit_id(machine_id, ops_day)) is None


def test_roster_post_unknown_technician_returns_400() -> None:
    app, deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/roster/draft",
        data={"machine_id": "101", "technician-101": "999"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 400
    assert deps.roster_store.is_empty() is True


def test_roster_post_rejects_new_inactive_technician() -> None:
    app, deps = _build_app()
    deps.provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Активный"], ["002", "Уволенный"]],
    )
    deps.provider.apply_system_users_snapshot(
        SystemUsersSnapshot(
            users_by_telegram_id={
                _ADMIN_TG: SystemUser(
                    user_id=SystemUserId("u1"),
                    name="Ops",
                    role=BotRole.ADMINISTRATOR,
                    is_active=True,
                    telegram_user_id=_ADMIN_TG,
                    technician_id=None,
                    company_roles=frozenset(),
                ),
                10: SystemUser(
                    user_id=SystemUserId("10"),
                    name="A",
                    role=BotRole.TECHNICIAN,
                    is_active=True,
                    telegram_user_id=10,
                    technician_id=TechnicianId("001"),
                    company_roles=frozenset(),
                ),
                11: SystemUser(
                    user_id=SystemUserId("11"),
                    name="B",
                    role=BotRole.TECHNICIAN,
                    is_active=False,
                    telegram_user_id=11,
                    technician_id=TechnicianId("002"),
                    company_roles=frozenset(),
                ),
            },
            users_by_technician_id={},
        ),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/roster/draft",
        data={
            "machine_id": "101",
            "technician-101": "002",
            "wd-101-2": "on",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_roster_forbidden_after_deactivate_flag_off() -> None:
    """error: деактивация администратора при живой cookie → 403 (flag off)."""
    app, deps = _build_app(stub=True)
    client = TestClient(app)
    login = client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    assert login.status_code in {302, 303}
    deps.provider.apply_rows(
        ReferenceDataSourceId.BOT_USERS,
        _admin_rows(active="нет"),
    )
    response = client.get("/admin/roster")
    assert response.status_code == 403


def test_roster_save_bar_buttons_disabled_when_clean() -> None:
    """happy: draft=applied → Применить/Сбросить disabled на SSR."""
    app, deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    body = client.get("/admin/roster").text
    assert "Применить" in body
    assert "Сбросить" in body
    assert 'id="roster-apply"' in body
    assert 'id="roster-reset"' in body
    assert "disabled" in body
    apply_idx = body.find('id="roster-apply"')
    reset_idx = body.find('id="roster-reset"')
    assert apply_idx != -1
    assert reset_idx != -1
    assert "disabled" in body[apply_idx : apply_idx + 80]
    assert "disabled" in body[reset_idx : reset_idx + 80]


def test_roster_dirty_banner_when_dirty() -> None:
    """happy: draft≠applied → dirty banner в HTML без hidden."""
    app, deps = _build_app()
    now = deps.now_factory()
    deps.roster_store.save_batch(
        (
            LocationRosterEntry(
                machine_id=MachineId("101"),
                technician_id=TechnicianId("001"),
                service_weekdays=frozenset({1}),
                updated_at=now,
                updated_by_telegram_user_id=_ADMIN_TG,
            ),
        ),
        actor_telegram_user_id=_ADMIN_TG,
        at=now,
    )
    deps.roster_draft_store.upsert(
        LocationRosterEntry(
            machine_id=MachineId("101"),
            technician_id=TechnicianId("002"),
            service_weekdays=frozenset({1}),
            updated_at=now,
            updated_by_telegram_user_id=_ADMIN_TG,
        ),
        expected_updated_at=None,
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    body = client.get("/admin/roster").text
    assert 'id="roster-dirty-banner"' in body
    idx = body.find('id="roster-dirty-banner"')
    assert idx != -1
    opening = body[body.rfind("<", 0, idx) : body.find(">", idx) + 1]
    assert "hidden" not in opening


def test_roster_dirty_banner_element_present_when_clean() -> None:
    """happy: clean GET — #roster-dirty-banner в DOM с hidden (клиентский toggle)."""
    app, _deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    body = client.get("/admin/roster").text
    assert 'id="roster-dirty-banner"' in body
    idx = body.find('id="roster-dirty-banner"')
    assert idx != -1
    opening = body[body.rfind("<", 0, idx) : body.find(">", idx) + 1]
    assert "hidden" in opening


def test_roster_static_js_posts_draft_endpoint() -> None:
    """happy: roster.js autosave → /admin/roster/draft + beforeunload pending."""
    text = (_STATIC_DIR / "roster.js").read_text(encoding="utf-8")
    assert "/admin/roster/draft" in text
    assert "beforeunload" in text
    assert "pending" in text or "flush" in text


def test_roster_static_js_gates_apply_on_pending_flush() -> None:
    """error/contract: Apply/Reset disabled while pending flush или flushFailed."""
    text = (_STATIC_DIR / "roster.js").read_text(encoding="utf-8")
    assert "hasPendingFlush" in text
    assert "flushFailed" in text or "flushError" in text
    assert "roster-apply" in text
    assert "hasPendingFlush()" in text
    refresh_idx = text.find("function refreshDirtyUi")
    assert refresh_idx != -1
    refresh_block = text[refresh_idx : refresh_idx + 280]
    assert "hasPendingFlush" in refresh_block


def test_roster_map_expand_controls_present() -> None:
    """happy: map expand control в HTML (LOK-105)."""
    app, _deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    body = client.get("/admin/roster").text
    assert 'id="roster-map-expand"' in body


def test_roster_map_expand_collapse_control_stays_above_overlay() -> None:
    """happy: collapse control поверх expanded overlay (body.roster-map-expanded)."""
    css = (_STATIC_DIR / "admin.css").read_text(encoding="utf-8")
    js = (_STATIC_DIR / "roster-map.js").read_text(encoding="utf-8")
    assert "is-expanded" in css
    assert "roster-map-expanded" in css or "roster-map-expanded" in js
    assert "position: fixed !important" in css
    assert "width: 100% !important" in css
    assert 'button[type="submit"]:disabled' in css or "button[type='submit']:disabled" in css


def test_location_name_script_escaped_in_roster_html() -> None:
    app, deps = _build_app()
    deps.provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [
            ["Id локации", "Имя локации", "Имя техника", "Id техника"],
            ["101", "<script>alert(1)</script>", "Иван", "001"],
        ],
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/roster")
    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text or "&#" in response.text
