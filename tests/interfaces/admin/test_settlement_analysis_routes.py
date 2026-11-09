from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests._company_roles_for_panels import company_roles_for_test_panels

from src.application.master_data import (
    InMemoryMasterDataCounterStore,
    InMemoryMasterDataStores,
    InMemorySystemUserStore,
    SaveSystemUsers,
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
from src.application.technician_settlement import (
    AggregateSettlementClusters,
    BuildPeriodAnalysisView,
    BuildSessionAnalysisView,
    BuildSettlementAnalysisTree,
    InMemorySettlementAnalysisPrefsStore,
    SettlementAnalysisPrefs,
)
from src.domain.ids import (
    EventId,
    MachineId,
    ReconciliationSessionId,
    RevisionId,
    TechnicianId,
)
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.system_user import AdminPanel, BotRole, SystemUser, SystemUserId
from src.domain.technician_settlement.events import (
    TechnicianReconciliationSessionCommitted,
    TechnicianReconciliationSessionCompleted,
)
from src.infrastructure.testing.settlement_fakes import (
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
)
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes
from src.interfaces.admin.session import admin_session_cookie_name, pack_admin_session

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_FROZEN_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
_TECH = TechnicianId("001")
_SESSION_A = "sess-a"
_SESSION_B = "sess-b"
_PERIOD_A = "period-a"


def _completed(
    *,
    session_id: str,
    mode: str,
    period_ids: tuple[str, ...],
    residual: dict[str, Decimal],
    warehouse_delta: dict[str, Decimal] | None = None,
) -> TechnicianReconciliationSessionCompleted:
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    return TechnicianReconciliationSessionCompleted(
        event_id=EventId(f"event-{session_id}"),
        session_id=ReconciliationSessionId(session_id),
        technician_id=_TECH,
        mode=mode,  # type: ignore[arg-type]
        anchor_at=now,
        period_ids=period_ids,
        deferred_period_ids=(),
        warehouse_inventory_id=f"inv-{session_id}",
        warehouse_inventory_moment=now,
        warehouse_delta_by_sku=dict(warehouse_delta or {"COFFEE": Decimal("-1")}),
        warehouse_source="domain_technician_warehouse",
        warehouse_transfer_refs=(),
        ledger_balance_before={},
        residual_by_sku=dict(residual),
        finalized_at=now,
        occurred_at=now,
        executed_at=now,
    )


def _committed(
    *,
    session_id: str,
    mode: str,
    period_ids: tuple[str, ...],
    residual: dict[str, Decimal],
    warehouse_delta: dict[str, Decimal] | None = None,
) -> TechnicianReconciliationSessionCommitted:
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    cleared = dict(residual)
    return TechnicianReconciliationSessionCommitted(
        event_id=EventId(f"event-{session_id}"),
        session_id=ReconciliationSessionId(session_id),
        technician_id=_TECH,
        mode=mode,  # type: ignore[arg-type]
        anchor_at=now,
        period_ids=period_ids,
        deferred_period_ids=(),
        warehouse_inventory_id=f"inv-{session_id}",
        warehouse_inventory_moment=now,
        warehouse_delta_by_sku=dict(warehouse_delta or {"COFFEE": Decimal("-1")}),
        warehouse_source="domain_technician_warehouse",
        warehouse_transfer_refs=(),
        ledger_balance_before=dict(cleared),
        cleared_by_sku=dict(cleared),
        residual_by_sku=dict(residual),
        finalized_at=now,
        occurred_at=now,
        executed_at=now,
    )


def _snapshot(period_id: str) -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=MachineId("vm-01"),
        responsible_technician_id=_TECH,
        opening_revision_id=RevisionId(f"open-{period_id}"),
        closing_revision_id=RevisionId(f"close-{period_id}"),
        opened_at=datetime(2026, 7, 1, 8, 0, tzinfo=UTC),
        closed_at=datetime(2026, 7, 7, 18, 0, tzinfo=UTC),
        lines=(
            ReconciliationLine(
                product_code="COFFEE",
                actual_prev=Decimal("0"),
                actual=Decimal("0"),
                calculated=Decimal("0"),
                delta=Decimal("-2"),
                sales_total=Decimal("10"),
            ),
        ),
        sales_lines=(),
        load_count=0,
        status="complete",
        ledger_posted=True,
        location_name="Школа",
    )


def _seed_analysis_data() -> tuple[
    InMemoryTechnicianSettlementEventStore,
    InMemoryPeriodReconciliationRepository,
]:
    events = InMemoryTechnicianSettlementEventStore()
    events.append(
        _committed(
            session_id=_SESSION_A,
            mode="inventory_delta",
            period_ids=(_PERIOD_A,),
            residual={"COFFEE": Decimal("-3")},
        ),
        expected_version=0,
    )
    events.append(
        _completed(
            session_id=_SESSION_B,
            mode="exit_warehouse_closed",
            period_ids=(),
            residual={"COFFEE": Decimal("-1")},
        ),
        expected_version=1,
    )
    periods = InMemoryPeriodReconciliationRepository()
    periods.save(_snapshot(_PERIOD_A))
    return events, periods


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


def _build_app(
    *,
    enabled: bool = True,
    settlement_analysis_enabled: bool = True,
    users_enabled: bool = False,
    panels: frozenset[AdminPanel] | None = None,
    telegram_user_id: int = _ADMIN_TG,
    prefs_store: InMemorySettlementAnalysisPrefsStore | None = None,
    admin_max_body_bytes: int = 1_048_576,
) -> tuple[FastAPI, AdminHttpDeps, InMemorySettlementAnalysisPrefsStore]:
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

    effective_panels = panels if panels is not None else frozenset(AdminPanel)
    user = _system_user(tg=telegram_user_id, panels=effective_panels)
    provider.apply_system_users_snapshot(
        SystemUsersSnapshot(
            users_by_telegram_id={telegram_user_id: user},
            users_by_technician_id={},
        ),
    )

    events, periods = _seed_analysis_data()
    tree = BuildSettlementAnalysisTree(event_store=events, period_repository=periods)
    aggregate = AggregateSettlementClusters(event_store=events, period_repository=periods)
    session_view = BuildSessionAnalysisView(event_store=events)
    period_view = BuildPeriodAnalysisView(period_repository=periods)
    store = prefs_store if prefs_store is not None else InMemorySettlementAnalysisPrefsStore()

    system_user_store = None
    save_system_users = None
    if users_enabled:
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
        save_system_users = SaveSystemUsers(
            store=system_user_store,
            counters=InMemoryMasterDataCounterStore(),
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
        admin_max_body_bytes=admin_max_body_bytes,
        master_stores=InMemoryMasterDataStores(),
        users_enabled=users_enabled,
        system_user_store=system_user_store,
        save_system_users=save_system_users,
        settlement_analysis_enabled=settlement_analysis_enabled,
        build_settlement_analysis_tree=tree if settlement_analysis_enabled else None,
        aggregate_settlement_clusters=aggregate if settlement_analysis_enabled else None,
        build_session_analysis_view=session_view if settlement_analysis_enabled else None,
        build_period_analysis_view=period_view if settlement_analysis_enabled else None,
        settlement_analysis_prefs_store=store if settlement_analysis_enabled else None,
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=enabled)
    return app, deps, store


def _login(client: TestClient, *, tg: int = _ADMIN_TG) -> None:
    response = client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(tg)},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}


def test_settlement_analysis_404_when_disabled() -> None:
    app, _deps, _store = _build_app(settlement_analysis_enabled=False)
    client = TestClient(app)
    _login(client)
    assert client.get("/admin/settlement-analysis").status_code == 404


def test_settlement_analysis_forbidden_without_panel() -> None:
    app, _deps, _store = _build_app(
        users_enabled=True,
        panels=frozenset({AdminPanel.ROSTER}),
    )
    client = TestClient(app)
    token = pack_admin_session(
        telegram_user_id=_ADMIN_TG,
        issued_at=int(_FROZEN_NOW.timestamp()),
        secret=_SESSION_SECRET,
    )
    client.cookies.set(admin_session_cookie_name(), token)
    assert client.get("/admin/settlement-analysis").status_code == 403


def test_settlement_analysis_get_offloads_sync_builder_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    real = asyncio.to_thread

    async def recording(func, /, *args, **kwargs):
        calls.append(func)
        return await real(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", recording)
    app, _deps, _prefs = _build_app()
    client = TestClient(app)
    _login(client)
    response = client.get("/admin/settlement-analysis")
    assert response.status_code == 200
    assert any(getattr(f, "__name__", "") == "build_settlement_analysis_page_sync" for f in calls)


def test_settlement_analysis_sessions_query_aggregates() -> None:
    prefs = InMemorySettlementAnalysisPrefsStore()
    prefs.save(
        _ADMIN_TG,
        SettlementAnalysisPrefs(
            unit_prices={"COFFEE": Decimal("1.5")},
            recoverable_product_codes=frozenset({"COFFEE"}),
            allowed_loss_pct=Decimal("2"),
        ),
    )
    app, _deps, _store = _build_app(prefs_store=prefs)
    client = TestClient(app)
    _login(client)
    response = client.get(
        f"/admin/settlement-analysis?technician_id=001&sessions={_SESSION_A},{_SESSION_B}",
    )
    assert response.status_code == 200
    body = response.text
    assert "/admin/static/admin.css?v=" in body
    assert "Кофе" in body or "COFFEE" in body
    assert "data-aggregate-block" in body
    # Checkbox selection must not auto-expand cluster details.
    assert 'class="settlement-cluster" open' not in body
    assert 'class="settlement-cluster"open' not in body
    assert "-4" in body or "−4" in body or "4" in body
    assert 'data-sku-group="loss"' in body
    assert 'data-sku-group="recoverable"' in body
    assert "Группа" not in body
    assert "Residual" not in body
    assert "Итог" in body
    assert "Недостача ₽" not in body
    assert "Сверх нормы ₽" not in body
    assert ">Недостача<" in body or "Недостача</th>" in body
    assert "Сверх нормы" in body
    aggregate_html = body.split('data-aggregate-block="1"', 1)[1].split(
        "settlement-analysis-prefs",
        1,
    )[0]
    assert aggregate_html.count("<thead") == 2
    assert (
        "<thead"
        in aggregate_html.split('data-sku-group="loss"', 1)[1].split(
            'data-sku-group="recoverable"',
            1,
        )[0]
    )
    assert "<thead" in aggregate_html.split('data-sku-group="recoverable"', 1)[1]
    assert "Недостача (всего)" not in body
    # money display is whole rubles (4 * 1.5 = 6.0 → 6); COFFEE is recoverable
    assert 'data-sku-shortage="loss"' in body
    assert 'data-sku-shortage="recoverable"' in body
    assert 'data-sku-excess="loss"' in body
    assert 'data-sku-excess="recoverable"' in body
    loss_shortage = body.split('data-sku-shortage="loss"', 1)[1].split("</td>", 1)[0]
    recoverable_shortage = body.split('data-sku-shortage="recoverable"', 1)[1].split(
        "</td>",
        1,
    )[0]
    assert "0" in loss_shortage
    assert "6" in recoverable_shortage
    assert "₽" not in aggregate_html.split("<tfoot", 1)[1]


def test_aggregate_empty_group_still_renders_table_and_zero_total() -> None:
    prefs = InMemorySettlementAnalysisPrefsStore()
    prefs.save(
        _ADMIN_TG,
        SettlementAnalysisPrefs(
            unit_prices={"COFFEE": Decimal("1.5")},
            recoverable_product_codes=frozenset(),
            allowed_loss_pct=Decimal("2"),
        ),
    )
    app, _deps, _store = _build_app(prefs_store=prefs)
    client = TestClient(app)
    _login(client)
    body = client.get(
        f"/admin/settlement-analysis?technician_id=001&sessions={_SESSION_A}",
    ).text
    assert 'data-sku-group="loss"' in body
    assert 'data-sku-group="recoverable"' in body
    recoverable_chunk = body.split('data-sku-group="recoverable"', 1)[1]
    recoverable_table = recoverable_chunk.split("</table>", 1)[0]
    assert "<tbody>" in recoverable_table
    assert "<tfoot>" in recoverable_table
    recoverable_shortage = body.split('data-sku-shortage="recoverable"', 1)[1].split(
        "</td>",
        1,
    )[0]
    assert "0" in recoverable_shortage
    loss_shortage = body.split('data-sku-shortage="loss"', 1)[1].split("</td>", 1)[0]
    # SESSION_A residual -3 × 1.5 = 4.5 → 5
    assert "5" in loss_shortage
    assert 'data-sku-excess="loss"' in body
    assert 'data-sku-excess="recoverable"' in body


def test_cluster_checkbox_only_on_roots() -> None:
    app, _deps, _store = _build_app()
    client = TestClient(app)
    _login(client)
    html = client.get("/admin/settlement-analysis?technician_id=001").text
    assert 'data-cluster-checkbox="1"' in html
    assert f'value="{_SESSION_A}"' in html
    assert "data-period-row" in html
    assert "settlement-period-table" in html
    assert ">Локация<" in html or "Локация</th>" in html
    assert "admin-entity-link" in html
    assert html.count('data-cluster-checkbox="1"') == 2
    period_chunks = html.split('data-period-row="1"')[1:]
    assert period_chunks
    for chunk in period_chunks:
        row_html = chunk.split("</tr>", 1)[0]
        assert "data-cluster-checkbox" not in row_html
        assert 'type="checkbox"' not in row_html


def test_empty_completed_shows_message() -> None:
    # edge: tree object exists with clusters==() — empty_message must still render
    app, deps, _store = _build_app()
    deps.provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Иван"], ["002", "Пётр"]],
    )
    client = TestClient(app)
    _login(client)
    response = client.get("/admin/settlement-analysis?technician_id=002")
    assert response.status_code == 200
    body = response.text
    assert "Нет завершённых сверки" in body
    assert 'aria-label="Кластеры сверки"' not in body
    assert "data-cluster-checkbox" not in body


def test_prefs_post_persists() -> None:
    app, _deps, store = _build_app()
    client = TestClient(app)
    _login(client)
    response = client.post(
        "/admin/settlement-analysis/prefs",
        data={
            "technician_id": "001",
            "sessions": _SESSION_A,
            "prices[COFFEE]": "1.5",
            "recoverable[COFFEE]": "on",
            "allowed_loss_pct": "2",
        },
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "/admin/settlement-analysis" in response.headers["location"]
    saved = store.get(_ADMIN_TG)
    assert saved.unit_prices["COFFEE"] == Decimal("1.5")
    assert "COFFEE" in saved.recoverable_product_codes
    assert saved.allowed_loss_pct == Decimal("2")


def test_session_drilldown_ok() -> None:
    app, _deps, _store = _build_app()
    client = TestClient(app)
    _login(client)
    response = client.get(
        f"/admin/settlement-analysis/sessions/{_SESSION_A}?technician_id=001",
    )
    assert response.status_code == 200
    body = response.text
    assert "warehouse_delta" in body
    assert "residual" in body
    assert "COFFEE" in body
    assert 'aria-label="periods"' not in body
    assert f"/admin/settlement-analysis/periods/{_PERIOD_A}" not in body


def test_period_drilldown_ok() -> None:
    app, _deps, _store = _build_app()
    client = TestClient(app)
    _login(client)
    response = client.get(f"/admin/settlement-analysis/periods/{_PERIOD_A}")
    assert response.status_code == 200
    body = response.text
    assert "Школа" in body
    assert "sales_total" in body
    assert "COFFEE" in body


def test_settlement_analysis_nav_when_enabled() -> None:
    app, _deps, _store = _build_app()
    client = TestClient(app)
    _login(client)
    roster = client.get("/admin/roster")
    assert b"/admin/settlement-analysis" in roster.content
