from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.master_data import InMemoryMasterDataStores
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
    VisitBoardCell,
    VisitBoardRow,
    VisitBoardTechnicianBlock,
    VisitBoardView,
)
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.domain.ids import MachineId, TechnicianId
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes
from src.interfaces.admin.session import admin_session_cookie_name, pack_admin_session

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_TECH_TG = 2002
_FROZEN_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _widget_hash(fields: dict[str, str], bot_token: str) -> str:
    data_check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields) if key != "hash")
    secret = hashlib.sha256(bot_token.encode()).digest()
    return hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()


def _signed_widget_fields(*, tg: int = _ADMIN_TG, auth_date: str | None = None) -> dict[str, str]:
    fields = {
        "id": str(tg),
        "auth_date": str(int(_FROZEN_NOW.timestamp())) if auth_date is None else auth_date,
    }
    fields["hash"] = _widget_hash(fields, _BOT_TOKEN)
    return fields


def _admin_rows(
    *,
    role: str = "администратор",
    active: str = "да",
    tg: int = _ADMIN_TG,
) -> list[list[str]]:
    return [
        ["Id", "Имя", "Роль", "телеграм id", "Id техника", "is active"],
        ["u1", "Ops", role, str(tg), "", active],
    ]


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


def _build_app(
    *,
    enabled: bool = True,
    with_master_stores: bool = False,
    with_visit_board: bool = False,
) -> tuple[FastAPI, AdminHttpDeps]:
    provider = ReferenceDataProvider()
    provider.apply_rows(ReferenceDataSourceId.BOT_USERS, _admin_rows())
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
    provider.configure_roster(enabled=enabled, store=roster_store)
    master_stores = InMemoryMasterDataStores() if with_master_stores else None
    build_visit_board = _empty_build_visit_board() if with_visit_board else None
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
        master_stores=master_stores,
        build_visit_board=build_visit_board,
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=enabled)
    return app, deps


def _login(client: TestClient) -> None:
    fields = _signed_widget_fields()
    response = client.post(
        "/admin/auth/telegram",
        data=fields,
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}


def test_visit_board_404_when_admin_disabled() -> None:
    app, _ = _build_app(enabled=False, with_master_stores=True, with_visit_board=True)
    client = TestClient(app)
    assert client.get("/admin/visit-board").status_code == 404


def test_visit_board_404_without_master_stores() -> None:
    app, _ = _build_app(enabled=True, with_master_stores=False, with_visit_board=True)
    client = TestClient(app)
    assert client.get("/admin/visit-board").status_code == 404


def test_visit_board_requires_login() -> None:
    app, _ = _build_app(enabled=True, with_master_stores=True, with_visit_board=True)
    client = TestClient(app)
    response = client.get("/admin/visit-board", follow_redirects=False)
    assert response.status_code in {302, 303}
    assert "/admin/login" in response.headers["location"]


def test_visit_board_get_offloads_sync_builder_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    real = asyncio.to_thread

    async def recording(func, /, *args, **kwargs):
        calls.append(func)
        return await real(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", recording)
    app, _deps = _build_app(enabled=True, with_master_stores=True, with_visit_board=True)
    client = TestClient(app)
    _login(client)
    response = client.get("/admin/visit-board")
    assert response.status_code == 200
    assert any(getattr(f, "__name__", "") == "build_visit_board_page_sync" for f in calls)


def test_visit_board_default_month() -> None:
    app, _deps = _build_app(enabled=True, with_master_stores=True, with_visit_board=True)
    client = TestClient(app)
    _login(client)
    response = client.get("/admin/visit-board")
    assert response.status_code == 200
    assert b"2026" in response.content
    assert b"8" in response.content or "август".encode() in response.content.lower()


def test_visit_board_invalid_month_redirects() -> None:
    app, _ = _build_app(enabled=True, with_master_stores=True, with_visit_board=True)
    client = TestClient(app)
    _login(client)
    response = client.get("/admin/visit-board?year=2026&month=13", follow_redirects=False)
    assert response.status_code in {302, 303}
    assert "month=8" in response.headers["location"] or "month=08" in response.headers["location"]


def test_visit_board_forbidden_non_admin() -> None:
    app, deps = _build_app(enabled=True, with_master_stores=True, with_visit_board=True)
    provider = deps.provider
    provider.apply_rows(
        ReferenceDataSourceId.BOT_USERS,
        [
            ["Id", "Имя", "Роль", "телеграм id", "Id техника", "is active"],
            ["t1", "Tech", "техник", str(_TECH_TG), "001", "да"],
        ],
    )
    client = TestClient(app)
    # Login rejects non-admin; plant session to assert GET panel gate.
    token = pack_admin_session(
        telegram_user_id=_TECH_TG,
        issued_at=int(_FROZEN_NOW.timestamp()),
        secret=_SESSION_SECRET,
    )
    client.cookies.set(admin_session_cookie_name(), token)
    assert client.get("/admin/visit-board").status_code == 403


def test_visit_board_has_no_local_admin_header() -> None:
    app, _ = _build_app(enabled=True, with_master_stores=True, with_visit_board=True)
    client = TestClient(app)
    _login(client)
    html = client.get("/admin/visit-board").text
    assert 'class="admin-app-header"' in html
    assert 'class="admin-header"' not in html
    assert "Календарь визитов" in html


def test_visit_board_has_no_save_bar() -> None:
    app, _ = _build_app(enabled=True, with_master_stores=True, with_visit_board=True)
    client = TestClient(app)
    _login(client)
    response = client.get("/admin/visit-board")
    assert b"admin-save-bar" not in response.content


def test_visit_board_nav_when_master_on() -> None:
    app, _ = _build_app(enabled=True, with_master_stores=True, with_visit_board=True)
    client = TestClient(app)
    _login(client)
    roster = client.get("/admin/roster")
    assert b"/admin/visit-board" in roster.content


def test_every_admin_panel_includes_visit_board_route() -> None:
    route_by_panel = {
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
    assert set(route_by_panel) == set(AdminPanel)


_WEEKDAY_LABELS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_ADMIN_CSS = (
    Path(__file__).resolve().parents[3] / "src" / "interfaces" / "admin" / "static" / "admin.css"
)


def _two_tech_board() -> VisitBoardView:
    days = tuple(date(2026, 8, 1) + timedelta(days=offset) for offset in range(31))
    today = date(2026, 8, 21)

    def _row(title: str, location_id: str, machine_id: str) -> VisitBoardRow:
        return VisitBoardRow(
            location_id=location_id,
            title=title,
            machine_ids=(MachineId(machine_id),),
            cells=tuple(
                VisitBoardCell(day=day, background_planned=False, icons=()) for day in days
            ),
            placement_missing=False,
        )

    return VisitBoardView(
        year=2026,
        month=8,
        days=days,
        today=today,
        technicians=(
            VisitBoardTechnicianBlock(
                technician_id=TechnicianId("001"),
                display_name="Алексей",
                roster_rows=(_row("Школа", "101", "m-101"),),
                visited_rows=(),
            ),
            VisitBoardTechnicianBlock(
                technician_id=TechnicianId("002"),
                display_name="Борис",
                roster_rows=(_row("Офис", "102", "m-102"),),
                visited_rows=(),
            ),
        ),
    )


@dataclass(frozen=True, slots=True)
class _StubBuildVisitBoard:
    view: VisitBoardView

    def execute(self, *, year: int, month: int, now: datetime) -> VisitBoardView:
        return self.view


def _inject_two_tech_board(deps: AdminHttpDeps) -> None:
    object.__setattr__(deps, "build_visit_board", _StubBuildVisitBoard(_two_tech_board()))


def test_visit_board_single_date_weekday_header_for_two_technicians() -> None:
    """happy: one page-top header with dates and weekday row; not per technician."""
    app, deps = _build_app(enabled=True, with_master_stores=True, with_visit_board=True)
    _inject_two_tech_board(deps)
    client = TestClient(app)
    _login(client)
    html = client.get("/admin/visit-board").text

    assert html.count('class="visit-board-chrome-pin"') == 1
    assert html.count("visit-board-weekdays") == 1
    assert "Алексей" in html and "Борис" in html
    assert html.count('class="visit-board-block"') == 2
    for label in _WEEKDAY_LABELS:
        assert label in html
    # Aug 1 2026 is Saturday — first weekday label under day column is сб
    assert re.search(
        r'class="visit-board-weekdays"[^>]*>.*?<th[^>]*>\s*сб\s*</th>',
        html,
        flags=re.S,
    )
    blocks = re.findall(
        r'<section class="visit-board-block"[^>]*>.*?</section>',
        html,
        flags=re.S,
    )
    assert len(blocks) == 2
    for block in blocks:
        assert "<thead>" not in block


def test_visit_board_sticky_header_class_in_css() -> None:
    """edge: visit-board sticky chrome class present under app header."""
    css = _ADMIN_CSS.read_text(encoding="utf-8")
    assert ".visit-board-chrome-pin" in css
    pin_idx = css.find(".visit-board-chrome-pin")
    sticky_slice = css[pin_idx : pin_idx + 200]
    assert "position: sticky" in sticky_slice
    assert "var(--admin-app-header-height)" in sticky_slice
