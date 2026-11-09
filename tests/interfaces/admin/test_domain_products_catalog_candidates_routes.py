from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests._company_roles_for_panels import company_roles_for_test_panels
from tests.application.product_identity.fakes import FakeCatalogLookup

from src.application.master_data import (
    InMemoryMasterDataStores,
    InMemorySystemUserStore,
    SystemUserRecord,
)
from src.application.product_identity import (
    CatalogProduct,
    create_domain_product,
    link_domain_product,
)
from src.application.product_identity.ports import CatalogProductLookup
from src.application.reference_data import (
    ReferenceDataProvider,
    ReferenceDataSourceId,
)
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.reference_data.ms_product_catalog import MsEntityKind, MsProductEntry
from src.application.reference_data.ports import ReferenceDataSnapshotStore
from src.application.reference_data.sync_product_catalog_ms import SyncProductCatalogFromMs
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.sheets import SystemUsersSnapshot
from src.domain.system_user import AdminPanel, BotRole, SystemUser, SystemUserId
from src.infrastructure.product_identity import (
    MemoryDomainProductStore,
    SnapshotCatalogProductLookup,
)
from src.infrastructure.reference_data.memory_store import InMemoryReferenceDataSnapshotStore
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_FROZEN_NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
_ORIGIN = {"origin": "http://testserver"}
_MILK = CatalogProduct(code="2311", name="Молоко", archived=False)
_TEA = CatalogProduct(code="4001", name="Чай", archived=False)
_ARCHIVED = CatalogProduct(code="9001", name="Старое молоко", archived=True)


@dataclass(frozen=True, slots=True)
class _App:
    client: TestClient
    store: MemoryDomainProductStore
    lookup: CatalogProductLookup
    http: FastAPI


def _login(client: TestClient, telegram_user_id: int = _ADMIN_TG) -> None:
    response = client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(telegram_user_id)},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}


def _build(
    *,
    panels: frozenset[AdminPanel],
    cards: tuple[CatalogProduct, ...] = (_MILK, _TEA, _ARCHIVED),
    lookup: CatalogProductLookup | None = None,
    product_catalog_sync: Callable[[], Awaitable[None]] | None = None,
    catalog_snapshot_store: ReferenceDataSnapshotStore | None = None,
) -> _App:
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
    store = MemoryDomainProductStore()
    resolved_lookup: CatalogProductLookup = (
        lookup if lookup is not None else FakeCatalogLookup(cards)
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
        master_stores=InMemoryMasterDataStores(),
        domain_product_store=store,
        catalog_product_lookup=resolved_lookup,
        catalog_snapshot_store=catalog_snapshot_store,
        product_catalog_sync=product_catalog_sync,
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return _App(
        client=TestClient(app),
        store=store,
        lookup=resolved_lookup,
        http=app,
    )


def _post_import(
    client: TestClient,
    codes: list[str],
    *,
    origin: dict[str, str] | None = _ORIGIN,
) -> httpx.Response:
    pairs: list[tuple[str, str]] = [("action", "import")]
    pairs.extend(("code", code) for code in codes)
    headers = {"content-type": "application/x-www-form-urlencoded", **(origin or {})}
    return client.post(
        "/admin/domain-products/catalog-candidates",
        content=urlencode(pairs, doseq=True),
        headers=headers,
        follow_redirects=False,
    )


def test_catalog_candidates_get_shows_free_codes_including_archive() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    product = create_domain_product("Занятый", store=app.store, lookup=app.lookup)
    link_domain_product(product.domain_product_id, "2311", store=app.store, lookup=app.lookup)

    html = app.client.get("/admin/domain-products/catalog-candidates").text

    assert "Чай" in html
    assert "4001" in html
    assert "Старое молоко" in html
    assert "9001" in html
    assert 'value="2311"' not in html
    assert 'name="code"' in html
    assert "Выбрать все видимые" in html
    assert "Импортировать" in html


def test_catalog_candidates_post_creates_and_stays_with_summary() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)

    response = _post_import(app.client, ["4001", "9001"])

    assert response.status_code == 200
    assert "Кандидаты" in response.text
    assert "Создано: 2." in response.text
    assert "Без изменений: 0." in response.text
    assert len(app.store.list_visible()) == 2
    assert {p.catalog_code for p in app.store.list_visible()} == {"4001", "9001"}
    assert 'value="4001"' not in response.text
    assert 'value="9001"' not in response.text


def test_catalog_candidates_empty_post_shows_hint_without_writes() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)

    response = _post_import(app.client, [])

    assert response.status_code == 200
    assert "Выберите позиции" in response.text
    assert app.store.list_visible() == ()


def test_catalog_candidates_refresh_stays_on_page() -> None:
    catalog_provider = ReferenceDataProvider()
    snapshot_store = InMemoryReferenceDataSnapshotStore()
    lookup = SnapshotCatalogProductLookup(catalog_provider)

    class _OneCard:
        async def list_by_folder_ids(
            self,
            *,
            entity_kind: str,
            folder_ids: object,
        ) -> list[MsProductEntry]:
            _ = entity_kind, folder_ids
            return [MsProductEntry("7777", "Свежее", MsEntityKind.PRODUCT)]

    sync = SyncProductCatalogFromMs(
        reader=_OneCard(),
        store=snapshot_store,
        provider=catalog_provider,
        product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
        now=lambda: datetime(2026, 9, 24, 8, 0, tzinfo=UTC),
    )
    app = _build(
        panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}),
        lookup=lookup,
        product_catalog_sync=sync.sync_once,
        catalog_snapshot_store=snapshot_store,
    )
    _login(app.client)

    response = app.client.post(
        "/admin/domain-products/catalog-candidates",
        data={"action": "refresh-catalog"},
        headers=_ORIGIN,
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "Свежее" in response.text
    assert "7777" in response.text
    assert "Снимок: 24.09.2026 11:00" in response.text
    assert "Кандидаты" in response.text


def test_catalog_candidates_linked_code_disappears_after_import() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    before = app.client.get("/admin/domain-products/catalog-candidates").text
    assert 'value="4001"' in before

    _post_import(app.client, ["4001"])
    after = app.client.get("/admin/domain-products/catalog-candidates").text

    assert 'value="4001"' not in after
    assert 'value="2311"' in after


def test_catalog_candidates_forbidden_without_panel() -> None:
    app = _build(panels=frozenset({AdminPanel.ROSTER}))
    _login(app.client)
    assert app.client.get("/admin/domain-products/catalog-candidates").status_code == 403
    assert _post_import(app.client, ["4001"]).status_code == 403


def test_catalog_candidates_forbidden_bad_origin() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    response = _post_import(
        app.client,
        ["4001"],
        origin={"origin": "http://evil.example"},
    )
    assert response.status_code == 403
    assert app.store.list_visible() == ()


def test_catalog_candidates_import_logs_counters_without_codes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    with caplog.at_level(logging.INFO):
        _post_import(app.client, ["4001"])
    records = [
        r for r in caplog.records if r.getMessage() == "admin_domain_products_catalog_import"
    ]
    assert len(records) == 1
    assert records[0].created_count == 1  # type: ignore[attr-defined]
    assert records[0].unchanged_count == 0  # type: ignore[attr-defined]
    assert records[0].failures_count == 0  # type: ignore[attr-defined]
    assert "4001" not in caplog.text
    assert "Чай" not in records[0].getMessage()
