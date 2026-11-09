from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests._company_roles_for_panels import company_roles_for_test_panels

from src.application.master_data import (
    InMemoryMasterDataCounterStore,
    InMemoryMasterDataStores,
    InMemorySystemUserStore,
    MachineKind,
    MachineStatus,
    MasterMachine,
    SaveSystemUsers,
    SystemUserRecord,
)
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.sales_monitoring import OFFLINE_CHECK_ABSENT
from src.application.service_visits import (
    BuildVisitBoardMonth,
    LocationDisplaySnapshot,
    NullMaintenanceOnOperationalDayLookup,
    PlacementAtSnapshot,
    RosterEntrySnapshot,
)
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.sheets import SystemUsersSnapshot
from src.domain.ids import MachineId, TechnicianId
from src.domain.system_user import AdminPanel, BotRole, SystemUser, SystemUserId
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes
from src.interfaces.admin.session import admin_session_cookie_name, pack_admin_session

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_FROZEN_NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


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


@dataclass
class _FakeOpenAudit:
    open_ids: frozenset[str] = field(default_factory=frozenset)
    offline_ids: frozenset[str] = field(default_factory=frozenset)
    controls_by_machine: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    session_from_event_id: bool = False
    cleared_documents: list[dict[str, object]] = field(default_factory=list)
    episode_documents: list[dict[str, object]] = field(default_factory=list)

    def list_open_no_sales(self) -> list[dict[str, object]]:
        documents: list[dict[str, object]] = []
        for machine_id in sorted(self.open_ids):
            document: dict[str, object] = {
                "machine_id": machine_id,
                "opened_at": _FROZEN_NOW,
                "status": "open",
                "kind": "no_sales",
            }
            if self.session_from_event_id:
                document["event_id"] = f"stale-opened:{machine_id}"
            else:
                document["opened_event_id"] = f"open-{machine_id}"
            documents.append(document)
        return documents

    def list_open_offline(self) -> list[dict[str, object]]:
        return [
            {
                "machine_id": machine_id,
                "status": "open",
                "kind": "offline",
            }
            for machine_id in sorted(self.offline_ids)
        ]

    def list_no_sales_controls(self, machine_id: MachineId) -> list[dict[str, object]]:
        return list(self.controls_by_machine.get(machine_id.value, []))

    def list_cleared_no_sales_since(
        self,
        *,
        cleared_at_gte: datetime,
    ) -> list[dict[str, object]]:
        return [
            document
            for document in self.cleared_documents
            if isinstance(document.get("cleared_at"), datetime)
            and document["cleared_at"] >= cleared_at_gte
        ]

    def list_no_sales_episodes_overlapping(
        self,
        *,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for document in self.episode_documents:
            opened_at = document.get("opened_at")
            cleared_at = document.get("cleared_at")
            opened_in = isinstance(opened_at, datetime) and start <= opened_at <= end
            cleared_in = isinstance(cleared_at, datetime) and start <= cleared_at <= end
            if opened_in or cleared_in:
                result.append(document)
        return result


@dataclass(frozen=True, slots=True)
class _FakeMaintenanceCompleted:
    completed_at: datetime


def _system_user(*, tg: int, panels: frozenset[AdminPanel]) -> SystemUser:
    return SystemUser(
        user_id=SystemUserId(str(tg)),
        name="Ops",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=tg,
        technician_id=None,
        company_roles=company_roles_for_test_panels(panels),
    )


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
    panels: frozenset[AdminPanel],
    open_ids: frozenset[str] | None = None,
    offline_ids: frozenset[str] | None = None,
    machines: tuple[MasterMachine, ...] = (),
    enqueue: Callable[..., None] | None = None,
    session_from_event_id: bool = False,
    cleared_documents: list[dict[str, object]] | None = None,
    episode_documents: list[dict[str, object]] | None = None,
    maintenance_by_machine: dict[str, tuple[_FakeMaintenanceCompleted, ...]] | None = None,
    incident_clear_pair_minutes: int | None = 30,
) -> tuple[FastAPI, AdminHttpDeps, _FakeOpenAudit]:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Иван"]],
    )
    roster_store = InMemoryLocationRosterStore()
    provider.configure_roster(enabled=True, store=roster_store)
    user = _system_user(tg=_ADMIN_TG, panels=panels)
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
    audit = _FakeOpenAudit(
        open_ids=open_ids if open_ids is not None else frozenset(),
        offline_ids=offline_ids if offline_ids is not None else frozenset(),
        session_from_event_id=session_from_event_id,
        cleared_documents=cleared_documents or [],
        episode_documents=episode_documents or [],
    )
    master_stores = InMemoryMasterDataStores()
    for machine in machines:
        master_stores.machines.upsert(machine)
    enqueued: list[tuple[object, ...]] = []
    maintenance_map = maintenance_by_machine or {}

    def _default_enqueue(**kwargs: object) -> None:
        enqueued.append(tuple(sorted(kwargs.items())))

    def list_maintenance(
        machine_id: MachineId,
        *,
        completed_at_start_inclusive: datetime,
        completed_at_end_exclusive: datetime,
    ) -> tuple[_FakeMaintenanceCompleted, ...]:
        return tuple(
            event
            for event in maintenance_map.get(machine_id.value, ())
            if completed_at_start_inclusive <= event.completed_at < completed_at_end_exclusive
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
        build_visit_board=_empty_build_visit_board(),
        users_enabled=True,
        system_user_store=system_user_store,
        save_system_users=SaveSystemUsers(
            store=system_user_store,
            counters=InMemoryMasterDataCounterStore(),
        ),
        list_open_no_sales=audit.list_open_no_sales,
        list_open_offline=audit.list_open_offline,
        list_no_sales_controls=audit.list_no_sales_controls,
        list_cleared_no_sales_since=audit.list_cleared_no_sales_since,
        list_no_sales_episodes_overlapping=audit.list_no_sales_episodes_overlapping,
        list_maintenance_completed_in_completed_at_window=list_maintenance,
        incident_clear_pair_minutes=incident_clear_pair_minutes,
        enqueue_no_sales_incident_control=enqueue if enqueue is not None else _default_enqueue,
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return app, deps, audit


def _client(
    *,
    panels: frozenset[AdminPanel],
    open_ids: frozenset[str] | None = None,
    offline_ids: frozenset[str] | None = None,
    machines: tuple[MasterMachine, ...] = (),
    cleared_documents: list[dict[str, object]] | None = None,
    episode_documents: list[dict[str, object]] | None = None,
    maintenance_by_machine: dict[str, tuple[_FakeMaintenanceCompleted, ...]] | None = None,
    incident_clear_pair_minutes: int | None = 30,
) -> TestClient:
    app, _deps, _audit = _build_app(
        panels=panels,
        open_ids=open_ids,
        offline_ids=offline_ids,
        machines=machines,
        cleared_documents=cleared_documents,
        episode_documents=episode_documents,
        maintenance_by_machine=maintenance_by_machine,
        incident_clear_pair_minutes=incident_clear_pair_minutes,
    )
    client = TestClient(app)
    token = pack_admin_session(
        telegram_user_id=_ADMIN_TG,
        issued_at=int(_FROZEN_NOW.timestamp()),
        secret=_SESSION_SECRET,
    )
    client.cookies.set(admin_session_cookie_name(), token)
    return client


def test_machine_incidents_requires_visit_board_panel() -> None:
    client = _client(panels=frozenset({AdminPanel.SETTLEMENT_ANALYSIS}))
    response = client.get("/admin/machine-incidents")
    assert response.status_code == 403


def test_mute_post_unknown_machine_returns_404() -> None:
    client = _client(
        panels=frozenset({AdminPanel.ROSTER, AdminPanel.VISIT_BOARD, AdminPanel.MASTER_DATA}),
        open_ids=frozenset(),
    )
    response = client.post(
        "/admin/machine-incidents/501/mute",
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 404


def test_mute_post_rejects_foreign_origin() -> None:
    calls: list[object] = []

    def enqueue(**kwargs: object) -> None:
        calls.append(kwargs)

    app, _deps, _audit = _build_app(
        panels=frozenset({AdminPanel.ROSTER, AdminPanel.VISIT_BOARD, AdminPanel.MASTER_DATA}),
        open_ids=frozenset({"501"}),
        enqueue=enqueue,
    )
    client = TestClient(app)
    token = pack_admin_session(
        telegram_user_id=_ADMIN_TG,
        issued_at=int(_FROZEN_NOW.timestamp()),
        secret=_SESSION_SECRET,
    )
    client.cookies.set(admin_session_cookie_name(), token)
    response = client.post(
        "/admin/machine-incidents/501/mute",
        headers={
            "Origin": "https://evil.example",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    assert response.status_code == 403
    assert calls == []


def test_machine_incidents_route_methods_are_get_and_post() -> None:
    client = _client(panels=frozenset({AdminPanel.VISIT_BOARD}))
    found = sorted(
        (method, route.path)
        for route in client.app.routes
        if str(getattr(route, "path", "")).startswith("/admin/machine-incidents")
        for method in (getattr(route, "methods", None) or set())
        if method != "HEAD"
    )
    assert found == [
        ("GET", "/admin/machine-incidents"),
        ("GET", "/admin/machine-incidents/history"),
        ("POST", "/admin/machine-incidents/{machine_id}/engineer-wait"),
        ("POST", "/admin/machine-incidents/{machine_id}/mute"),
        ("POST", "/admin/machine-incidents/{machine_id}/mute-cancel"),
    ]


def test_machine_incidents_shows_open_row_stored_without_opened_event_id() -> None:
    app, _deps, _audit = _build_app(
        panels=frozenset({AdminPanel.ROSTER, AdminPanel.VISIT_BOARD, AdminPanel.MASTER_DATA}),
        open_ids=frozenset({"188"}),
        session_from_event_id=True,
    )
    client = TestClient(app)
    token = pack_admin_session(
        telegram_user_id=_ADMIN_TG,
        issued_at=int(_FROZEN_NOW.timestamp()),
        secret=_SESSION_SECRET,
    )
    client.cookies.set(admin_session_cookie_name(), token)
    response = client.get("/admin/machine-incidents")
    assert response.status_code == 200
    assert "188" in response.text
    assert "Открытых инцидентов нет." not in response.text


def test_mute_post_uses_event_id_when_opened_field_missing() -> None:
    calls: list[dict[str, object]] = []

    def enqueue(**kwargs: object) -> None:
        calls.append(kwargs)

    app, _deps, _audit = _build_app(
        panels=frozenset({AdminPanel.ROSTER, AdminPanel.VISIT_BOARD, AdminPanel.MASTER_DATA}),
        open_ids=frozenset({"188"}),
        enqueue=enqueue,
        session_from_event_id=True,
    )
    client = TestClient(app)
    token = pack_admin_session(
        telegram_user_id=_ADMIN_TG,
        issued_at=int(_FROZEN_NOW.timestamp()),
        secret=_SESSION_SECRET,
    )
    client.cookies.set(admin_session_cookie_name(), token)
    response = client.post(
        "/admin/machine-incidents/188/mute",
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert calls == [
        {
            "machine_id": MachineId("188"),
            "opened_event_id": "stale-opened:188",
            "action": "mute",
        }
    ]


def test_incident_history_shows_display_clock_and_roster_table() -> None:
    client = _client(
        panels=frozenset({AdminPanel.ROSTER, AdminPanel.VISIT_BOARD, AdminPanel.MASTER_DATA}),
        open_ids=frozenset({"137"}),
        cleared_documents=[
            {
                "machine_id": "104",
                "opened_at": datetime(2026, 9, 28, 5, 42, 8, 776000, tzinfo=UTC),
                "cleared_at": datetime(2026, 9, 28, 6, 42, 8, tzinfo=UTC),
                "status": "cleared",
                "clear_reason": "cleared",
                "assigned_technician_display": "Александр Овчаров",
                "kind": "no_sales",
            }
        ],
    )
    response = client.get("/admin/machine-incidents/history")
    assert response.status_code == 200
    text = response.text
    assert "28.09.26 15:00" in text
    assert "28.09.26 08:42" in text
    assert "28.09.26 09:42" in text
    assert ">Код<" in text
    assert ">Имя<" in text
    assert ">Часов<" in text
    assert 'data-sort-key="hours"' in text
    assert 'data-sort-type="number"' in text
    assert 'data-sort-key="title"' not in text
    assert "+00:00" not in text
    assert "08:42:08" not in text
    assert "admin-roster" in text
    assert "incident-history-search" in text
    assert "incident-history-technician-filter" in text
    assert "Александр Овчаров" in text
    assert 'value="2026-09-22"' in text
    assert 'data-sort-key="opened"' in text
    assert 'data-sort-type="moment"' in text


def test_incident_history_clearance_column_uses_outcome() -> None:
    """happy: страница содержит исход эпизода и фильтр по нему."""
    last_sale = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
    client = _client(
        panels=frozenset({AdminPanel.ROSTER, AdminPanel.VISIT_BOARD, AdminPanel.MASTER_DATA}),
        episode_documents=[
            {
                "kind": "no_sales_episode",
                "machine_id": "174",
                "opened_event_id": "episode-174",
                "opened_at": datetime(2026, 9, 27, 8, 0, tzinfo=UTC),
                "cleared_at": datetime(2026, 9, 28, 10, 30, tzinfo=UTC),
                "last_sale_at": last_sale,
                "clear_trigger": "sale",
                "bypass_active": False,
                "assigned_technician_display": "Техник",
            }
        ],
        maintenance_by_machine={
            "174": (_FakeMaintenanceCompleted(completed_at=last_sale + timedelta(minutes=5)),),
        },
        incident_clear_pair_minutes=30,
    )
    response = client.get("/admin/machine-incidents/history")
    assert response.status_code == 200
    text = response.text
    assert "техник" in text
    assert 'id="incident-history-clear-filter"' in text
    assert 'data-clear-kind="техник"' in text
    assert 'value="техник"' in text


def test_incident_history_shows_two_episodes_and_open_sticky_same_machine() -> None:
    """happy: два эпизода одного machine_id + open sticky — три строки."""
    client = _client(
        panels=frozenset({AdminPanel.ROSTER, AdminPanel.VISIT_BOARD, AdminPanel.MASTER_DATA}),
        open_ids=frozenset({"174"}),
        episode_documents=[
            {
                "kind": "no_sales_episode",
                "machine_id": "174",
                "opened_event_id": "episode-174-a",
                "opened_at": datetime(2026, 9, 25, 8, 0, tzinfo=UTC),
                "cleared_at": datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
                "last_sale_at": datetime(2026, 9, 25, 11, 0, tzinfo=UTC),
                "clear_trigger": "sale",
                "bypass_active": False,
                "assigned_technician_display": "Техник",
            },
            {
                "kind": "no_sales_episode",
                "machine_id": "174",
                "opened_event_id": "episode-174-b",
                "opened_at": datetime(2026, 9, 27, 8, 0, tzinfo=UTC),
                "cleared_at": datetime(2026, 9, 27, 12, 0, tzinfo=UTC),
                "last_sale_at": datetime(2026, 9, 27, 11, 0, tzinfo=UTC),
                "clear_trigger": "sale",
                "bypass_active": False,
                "assigned_technician_display": "Техник",
            },
        ],
        incident_clear_pair_minutes=30,
    )
    response = client.get("/admin/machine-incidents/history")
    assert response.status_code == 200
    text = response.text
    assert text.count('data-machine-id="174"') == 3
    assert 'data-clear-kind="—"' in text


def test_incident_history_two_cycles_same_machine_id() -> None:
    """happy: период показывает две строки одного data-machine-id (два episode)."""
    client = _client(
        panels=frozenset({AdminPanel.ROSTER, AdminPanel.VISIT_BOARD, AdminPanel.MASTER_DATA}),
        episode_documents=[
            {
                "kind": "no_sales_episode",
                "machine_id": "174",
                "opened_event_id": "cycle-174-a",
                "opened_at": datetime(2026, 9, 25, 8, 0, tzinfo=UTC),
                "cleared_at": datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
                "last_sale_at": datetime(2026, 9, 25, 11, 0, tzinfo=UTC),
                "clear_trigger": "sale",
                "bypass_active": False,
                "assigned_technician_display": "Техник",
            },
            {
                "kind": "no_sales_episode",
                "machine_id": "174",
                "opened_event_id": "cycle-174-b",
                "opened_at": datetime(2026, 9, 27, 8, 0, tzinfo=UTC),
                "cleared_at": datetime(2026, 9, 27, 12, 0, tzinfo=UTC),
                "last_sale_at": datetime(2026, 9, 27, 11, 0, tzinfo=UTC),
                "clear_trigger": "sale",
                "bypass_active": False,
                "assigned_technician_display": "Техник",
            },
        ],
        incident_clear_pair_minutes=30,
    )
    response = client.get("/admin/machine-incidents/history")
    assert response.status_code == 200
    assert response.text.count('data-machine-id="174"') == 2


def test_incident_history_open_episode_shows_dash() -> None:
    """edge: open episode → data-clear-kind='—'."""
    client = _client(
        panels=frozenset({AdminPanel.ROSTER, AdminPanel.VISIT_BOARD, AdminPanel.MASTER_DATA}),
        episode_documents=[
            {
                "kind": "no_sales_episode",
                "machine_id": "174",
                "opened_event_id": "open-episode-174",
                "opened_at": datetime(2026, 9, 27, 8, 0, tzinfo=UTC),
                "cleared_at": None,
                "last_sale_at": None,
                "clear_trigger": None,
                "bypass_active": None,
                "assigned_technician_display": "Техник",
            }
        ],
        incident_clear_pair_minutes=30,
    )
    response = client.get("/admin/machine-incidents/history")
    assert response.status_code == 200
    text = response.text
    assert text.count('data-machine-id="174"') == 1
    assert 'data-clear-kind="—"' in text


def test_incident_history_orphan_cleared_and_paired_episode_not_duplicated() -> None:
    """edge: orphan cleared → cleared; paired episode+cleared — одна строка без cleared."""
    orphan_cleared_at = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)
    paired_opened = "episode-paired-104"
    last_sale = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
    client = _client(
        panels=frozenset({AdminPanel.ROSTER, AdminPanel.VISIT_BOARD, AdminPanel.MASTER_DATA}),
        episode_documents=[
            {
                "kind": "no_sales_episode",
                "machine_id": "104",
                "opened_event_id": paired_opened,
                "opened_at": datetime(2026, 9, 27, 8, 0, tzinfo=UTC),
                "cleared_at": datetime(2026, 9, 28, 10, 30, tzinfo=UTC),
                "last_sale_at": last_sale,
                "clear_trigger": "sale",
                "bypass_active": False,
                "assigned_technician_display": "Техник",
            }
        ],
        cleared_documents=[
            {
                "machine_id": "201",
                "opened_event_id": "orphan-cleared-201",
                "opened_at": datetime(2026, 9, 26, 8, 0, tzinfo=UTC),
                "cleared_at": orphan_cleared_at,
                "status": "cleared",
                "clear_reason": "cleared",
                "kind": "no_sales",
                "assigned_technician_display": "Сирота",
            },
            {
                "machine_id": "104",
                "opened_event_id": paired_opened,
                "opened_at": datetime(2026, 9, 27, 8, 0, tzinfo=UTC),
                "cleared_at": datetime(2026, 9, 28, 10, 30, tzinfo=UTC),
                "status": "cleared",
                "clear_reason": "cleared",
                "kind": "no_sales",
                "assigned_technician_display": "Техник",
            },
        ],
        maintenance_by_machine={
            "104": (_FakeMaintenanceCompleted(completed_at=last_sale + timedelta(minutes=5)),),
        },
        incident_clear_pair_minutes=30,
    )
    response = client.get("/admin/machine-incidents/history")
    assert response.status_code == 200
    text = response.text
    assert text.count('data-machine-id="201"') == 1
    assert 'data-machine-id="201"' in text and 'data-clear-kind="cleared"' in text
    assert text.count('data-machine-id="104"') == 1
    assert 'data-machine-id="104"' in text
    assert 'data-clear-kind="техник"' in text
    assert text.count('data-clear-kind="cleared"') == 1


def test_incident_history_pair_on_window_boundary_needs_exclusive_end_epsilon() -> None:
    """edge: completed ровно на +pair_minutes → техник (нужен ε exclusive end)."""
    pair_minutes = 30
    last_sale = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
    client = _client(
        panels=frozenset({AdminPanel.ROSTER, AdminPanel.VISIT_BOARD, AdminPanel.MASTER_DATA}),
        episode_documents=[
            {
                "kind": "no_sales_episode",
                "machine_id": "174",
                "opened_event_id": "episode-boundary-174",
                "opened_at": datetime(2026, 9, 27, 8, 0, tzinfo=UTC),
                "cleared_at": datetime(2026, 9, 28, 11, 0, tzinfo=UTC),
                "last_sale_at": last_sale,
                "clear_trigger": "sale",
                "bypass_active": False,
                "assigned_technician_display": "Техник",
            }
        ],
        maintenance_by_machine={
            "174": (
                _FakeMaintenanceCompleted(
                    completed_at=last_sale + timedelta(minutes=pair_minutes),
                ),
            ),
        },
        incident_clear_pair_minutes=pair_minutes,
    )
    response = client.get("/admin/machine-incidents/history")
    assert response.status_code == 200
    assert 'data-clear-kind="техник"' in response.text


def test_live_incidents_use_full_width_table_and_row_actions() -> None:
    client = _client(
        panels=frozenset({AdminPanel.ROSTER, AdminPanel.VISIT_BOARD, AdminPanel.MASTER_DATA}),
        open_ids=frozenset({"174"}),
    )
    response = client.get("/admin/machine-incidents")
    assert response.status_code == 200
    text = response.text
    assert "admin-main--full-width" in text
    assert "admin-roster" in text
    assert "admin-row-actions" in text
    assert "incident-live-search" in text
    assert text.count(">Код<") == 1
    assert ">Имя<" in text
    assert 'id="incident-live-table"' in text
    assert "machine-incidents-break" in text
    assert ">174<" in text
    assert "Глушить" in text
    assert "Инженер" in text
    assert "задача есть" in text


def test_machine_incidents_page_has_no_save_bar() -> None:
    client = _client(panels=frozenset({AdminPanel.VISIT_BOARD}))
    response = client.get("/admin/machine-incidents")
    assert response.status_code == 200
    assert b"admin-save-bar" not in response.content


def test_live_incidents_show_offline_check_absent_stub_for_micromarket() -> None:
    client = _client(
        panels=frozenset({AdminPanel.ROSTER, AdminPanel.VISIT_BOARD, AdminPanel.MASTER_DATA}),
        open_ids=frozenset({"701"}),
        offline_ids=frozenset({"701"}),
        machines=(
            MasterMachine(
                machine_id=MachineId("701"),
                kind=MachineKind.MICRO_MARKET,
                status=MachineStatus.ACTIVE_ON_SITE,
                label=None,
            ),
        ),
    )
    response = client.get("/admin/machine-incidents")
    assert response.status_code == 200
    assert OFFLINE_CHECK_ABSENT in response.text
    assert "не на связи" not in response.text


def test_live_incidents_keep_offline_note_for_coffee() -> None:
    client = _client(
        panels=frozenset({AdminPanel.ROSTER, AdminPanel.VISIT_BOARD, AdminPanel.MASTER_DATA}),
        open_ids=frozenset({"174"}),
        offline_ids=frozenset({"174"}),
        machines=(
            MasterMachine(
                machine_id=MachineId("174"),
                kind=MachineKind.COFFEE,
                status=MachineStatus.ACTIVE_ON_SITE,
                label=None,
            ),
        ),
    )
    response = client.get("/admin/machine-incidents")
    assert response.status_code == 200
    assert "не на связи" in response.text
    assert OFFLINE_CHECK_ABSENT not in response.text
