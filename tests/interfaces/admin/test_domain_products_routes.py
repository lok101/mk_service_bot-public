from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import Response
from tests._company_roles_for_panels import company_roles_for_test_panels
from tests.application.product_identity.fakes import FakeCatalogLookup

from src.application.master_data import (
    InMemoryMasterDataStores,
    InMemorySystemUserStore,
    SystemUserRecord,
)
from src.application.product_identity import (
    EMPTY_NAME_TEXT,
    CatalogProduct,
    create_domain_product,
    link_domain_product,
)
from src.application.product_identity.ports import CatalogProductLookup, ProcurementMirrorStore
from src.application.product_identity.procurement_mirror import ProcurementMirror
from src.application.reference_data import (
    ReferenceDataProvider,
    ReferenceDataSnapshot,
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
from src.infrastructure.product_identity.memory_procurement_mirror_store import (
    MemoryProcurementMirrorStore,
)
from src.infrastructure.reference_data.memory_store import InMemoryReferenceDataSnapshotStore
from src.interfaces.admin.clock_display import format_admin_moment
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_FROZEN_NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
_ORIGIN = {"origin": "http://testserver"}
_MILK = CatalogProduct(code="2311", name="Молоко", archived=False)
_ARCHIVED = CatalogProduct(code="9001", name="Старое молоко", archived=True)


@dataclass(frozen=True, slots=True)
class _DomainProductsApp:
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


def _seed(app: _DomainProductsApp, name: str, *, code: str | None = None):
    product = create_domain_product(name, store=app.store, lookup=app.lookup)
    if code is None:
        return product
    return link_domain_product(
        product.domain_product_id,
        code,
        store=app.store,
        lookup=app.lookup,
    )


def _build(
    *,
    panels: frozenset[AdminPanel],
    cards: tuple[CatalogProduct, ...] = (_MILK,),
    lookup: CatalogProductLookup | None = None,
    product_catalog_sync: Callable[[], Awaitable[None]] | None = None,
    catalog_snapshot_store: ReferenceDataSnapshotStore | None = None,
    admin_max_body_bytes: int = 1_048_576,
    procurement_mirror_enabled: bool = False,
    procurement_mirror_store: ProcurementMirrorStore | None = None,
) -> _DomainProductsApp:
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
        admin_max_body_bytes=admin_max_body_bytes,
        procurement_mirror_enabled=procurement_mirror_enabled,
        procurement_mirror_store=procurement_mirror_store,
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return _DomainProductsApp(
        client=TestClient(app),
        store=store,
        lookup=resolved_lookup,
        http=app,
    )


_SUPPLIER_NAME = "ООО Ромашка"
_SUPPLY_MOMENT = datetime(2026, 3, 15, 10, 30, tzinfo=UTC)
_EMPTY_MIRROR = ProcurementMirror(
    catalog_code="2311",
    supplier_id=None,
    supplier_name=None,
    last_buy_price=None,
    supply_moment=None,
    synced_at=_FROZEN_NOW,
)
_FILLED_MIRROR = ProcurementMirror(
    catalog_code="2311",
    supplier_id="agent-1",
    supplier_name=_SUPPLIER_NAME,
    last_buy_price=Decimal("12.5"),
    supply_moment=_SUPPLY_MOMENT,
    synced_at=_FROZEN_NOW,
)


def _build_with_mirror(
    *,
    mirrors: Sequence[ProcurementMirror] = (),
) -> _DomainProductsApp:
    store = MemoryProcurementMirrorStore()
    for mirror in mirrors:
        store.upsert(mirror)
    return _build(
        panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}),
        procurement_mirror_enabled=True,
        procurement_mirror_store=store,
    )


def test_domain_products_list_get_offloads_store_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # happy
    calls: list[object] = []
    real = asyncio.to_thread

    async def recording(func, /, *args, **kwargs):
        calls.append(func)
        return await real(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", recording)
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    response = app.client.get("/admin/domain-products")
    assert response.status_code == 200
    assert calls, "GET list must call asyncio.to_thread"


def test_domain_products_list_is_table_without_row_inputs() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    product = _seed(app, "Виден")
    html = app.client.get("/admin/domain-products").text
    assert 'href="/admin/domain-products/new"' in html
    assert "Добавить" in html
    assert f'href="/admin/domain-products/{product.domain_product_id}"' in html
    assert "Виден" in html
    assert 'class="admin-save-bar"' not in html
    assert 'name="action"' not in html
    assert 'name="catalog_code"' not in html
    assert "Поиск карточки" not in html
    assert "filter=unlinked" not in html
    assert 'data-name="Виден"' in html
    assert f'data-number="{product.number}"' in html
    assert 'data-state="нет связи"' in html


def test_domain_products_list_shows_import_button() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    html = app.client.get("/admin/domain-products").text
    assert "Импорт" in html
    assert 'enctype="multipart/form-data"' in html
    assert 'action="/admin/domain-products/import"' in html
    assert 'accept=".csv,.xls,.xlsx"' in html
    assert 'name="file"' in html


def test_domain_products_list_shows_catalog_candidates_link() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    html = app.client.get("/admin/domain-products").text
    assert "Кандидаты каталога" in html
    assert 'href="/admin/domain-products/catalog-candidates"' in html


def _import_file(
    client: TestClient,
    *,
    filename: str,
    content: bytes,
    origin: dict[str, str] | None = _ORIGIN,
) -> httpx.Response:
    files = {"file": (filename, content, "application/octet-stream")}
    return client.post(
        "/admin/domain-products/import",
        files=files,
        headers=origin or {},
        follow_redirects=False,
    )


def test_domain_products_import_csv_creates_product() -> None:
    app = _build(
        panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}),
        cards=(CatalogProduct(code="2311", name="Молоко", archived=False),),
    )
    _login(app.client)
    raw = "name,code\nМолоко,2311\n".encode()
    response = _import_file(app.client, filename="goods.csv", content=raw)
    assert response.status_code == 200
    assert "Создано: 1." in response.text
    assert "Связано: 1." in response.text
    assert len(app.store.list_visible()) == 1
    assert app.store.list_visible()[0].catalog_code == "2311"


def test_domain_products_import_xlsx_links_integer_code() -> None:
    from io import BytesIO

    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(["name", "code"])
    sheet.append(["Молоко", 12345.0])
    buffer = BytesIO()
    book.save(buffer)
    app = _build(
        panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}),
        cards=(CatalogProduct(code="12345", name="Молоко", archived=False),),
    )
    _login(app.client)
    response = _import_file(app.client, filename="a.xlsx", content=buffer.getvalue())
    assert response.status_code == 200
    assert app.store.list_visible()[0].catalog_code == "12345"


def test_domain_products_import_repeat_unchanged() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    raw = "n,c\nЧай,\n".encode()
    assert _import_file(app.client, filename="a.csv", content=raw).status_code == 200
    again = _import_file(app.client, filename="a.csv", content=raw)
    assert again.status_code == 200
    assert "Без изменений: 1." in again.text
    assert len(app.store.list_visible()) == 1


def test_domain_products_import_unreadable_400() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    response = _import_file(app.client, filename="a.txt", content=b"x")
    assert response.status_code == 400
    assert "Файл не читается." in response.text
    assert app.store.list_visible() == ()


def test_domain_products_import_forbidden_without_domain_products_panel() -> None:
    app = _build(panels=frozenset({AdminPanel.ROSTER}))
    _login(app.client)
    response = _import_file(app.client, filename="a.csv", content=b"n,c\nA,\n")
    assert response.status_code == 403


def test_domain_products_import_forbidden_bad_origin() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    response = _import_file(
        app.client,
        filename="a.csv",
        content=b"n,c\nA,\n",
        origin={"origin": "http://evil.example"},
    )
    assert response.status_code == 403


def test_domain_products_import_body_too_large() -> None:
    app = _build(
        panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}),
        admin_max_body_bytes=64,
    )
    _login(app.client)
    response = _import_file(
        app.client,
        filename="a.csv",
        content=b"n,c\n" + b"A,\n" * 40,
    )
    assert response.status_code == 413
    assert app.store.list_visible() == ()


def test_domain_products_list_orders_by_name_then_number() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    _seed(app, "Бета")
    _seed(app, "Альфа")
    first = _seed(app, "Молоко")
    second = _seed(app, "Молоко")
    html = app.client.get("/admin/domain-products").text
    assert html.index("Альфа") < html.index("Бета")
    assert html.index(first.number) < html.index(second.number)


def test_domain_products_hide_returns_to_list() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    product = _seed(app, "Скрыть")
    response = _post_card(app.client, product.domain_product_id, {"action": "hide"})
    assert response.status_code == 303
    assert response.headers["location"].endswith("/admin/domain-products")
    html = app.client.get("/admin/domain-products").text
    assert "Скрыть" not in html
    stored = app.store.get(product.domain_product_id)
    assert stored is not None
    assert stored.hidden is True


def test_domain_products_repeat_hide_returns_to_list() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    product = _seed(app, "Скрыть дважды")
    first = _post_card(app.client, product.domain_product_id, {"action": "hide"})
    second = _post_card(app.client, product.domain_product_id, {"action": "hide"})
    assert first.status_code == 303
    assert second.status_code == 303
    stored = app.store.get(product.domain_product_id)
    assert stored is not None
    assert stored.hidden is True
    assert len(app.store.numbers()) == 1


def test_domain_products_hidden_card_still_opens() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    product = _seed(app, "Скрытая карточка")
    _post_card(app.client, product.domain_product_id, {"action": "hide"})
    page = app.client.get(f"/admin/domain-products/{product.domain_product_id}")
    assert page.status_code == 200
    assert product.number in page.text
    assert "Скрытая карточка" not in app.client.get("/admin/domain-products").text


def test_domain_products_unknown_id_is_not_found() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    missing = "missing-product"
    assert app.client.get(f"/admin/domain-products/{missing}").status_code == 404
    posted = _post_card(app.client, missing, {"name": "Нет", "catalog_code": ""})
    assert posted.status_code == 404


def test_domain_products_new_screen_has_only_name_input() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    html = app.client.get("/admin/domain-products/new").text
    assert html.count('name="name"') == 1
    assert 'name="catalog_code"' not in html
    assert "Удалить" not in html
    assert "Убрать" not in html
    assert 'id="domain-product-number"' in html
    assert 'class="admin-save-bar"' in html
    assert 'action="/admin/domain-products/new"' in html


def _post_new(client: TestClient, data: dict[str, str]) -> Response:
    return client.post(
        "/admin/domain-products/new",
        data=data,
        headers=_ORIGIN,
        follow_redirects=False,
    )


def test_domain_products_get_new_does_not_create() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    opened = app.client.get("/admin/domain-products/new")
    assert opened.status_code == 200
    assert app.store.list_visible() == ()


def test_domain_products_post_new_creates_and_redirects_to_card() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    response = _post_new(app.client, {"name": "Молоко локальное"})
    assert response.status_code == 303
    visible = app.store.list_visible()
    assert len(visible) == 1
    product = visible[0]
    assert product.name == "Молоко локальное"
    assert product.number.startswith("d-")
    location = response.headers["location"]
    assert location.endswith(f"/admin/domain-products/{product.domain_product_id}")
    page = app.client.get(location)
    assert page.status_code == 200
    assert product.number in page.text
    assert "Молоко локальное" in page.text


def test_domain_products_empty_name_stays_on_new_screen() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    response = _post_new(app.client, {"name": "  "})
    assert response.status_code == 400
    assert "Название не может быть пустым." in response.text
    assert app.store.list_visible() == ()


def test_domain_product_quick_create_returns_id_and_empty_catalog_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    with caplog.at_level(logging.INFO):
        response = app.client.post(
            "/admin/domain-products/quick",
            json={"name": "Кефир"},
            headers=_ORIGIN,
        )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Кефир"
    assert body["catalog_code"] is None
    assert body["domain_product_id"]
    assert body["number"].startswith("d-")
    stored = app.store.get(body["domain_product_id"])
    assert stored is not None
    assert stored.catalog_code is None
    assert any(
        getattr(record, "domain_product_id", None) == body["domain_product_id"]
        for record in caplog.records
        if record.getMessage() == "admin_domain_product_quick_create"
    )


def test_domain_product_quick_create_rejects_empty_name() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    before = app.store.list_visible()
    response = app.client.post(
        "/admin/domain-products/quick",
        json={"name": "   "},
        headers=_ORIGIN,
    )
    assert response.status_code == 400
    assert response.json()["error"] == EMPTY_NAME_TEXT
    assert app.store.list_visible() == before


def test_domain_product_quick_create_without_origin_is_forbidden() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    response = app.client.post(
        "/admin/domain-products/quick",
        json={"name": "Кефир"},
    )
    assert response.status_code == 403
    assert app.store.list_visible() == ()


def test_domain_product_quick_create_forbidden_without_domain_products_panel() -> None:
    app = _build(panels=frozenset({AdminPanel.ROSTER}))
    _login(app.client)
    response = app.client.post(
        "/admin/domain-products/quick",
        json={"name": "Кефир"},
        headers=_ORIGIN,
    )
    assert response.status_code == 403
    assert app.store.list_visible() == ()


def test_domain_product_quick_create_rejects_invalid_json() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    response = app.client.post(
        "/admin/domain-products/quick",
        content=b"{",
        headers={**_ORIGIN, "content-type": "application/json"},
    )
    assert response.status_code == 400
    assert app.store.list_visible() == ()


def test_domain_products_post_without_origin_is_forbidden() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    response = app.client.post(
        "/admin/domain-products/new",
        data={"name": "Без origin"},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert app.store.list_visible() == ()


def _post_card(client: TestClient, product_id: str, data: dict[str, str]) -> Response:
    return client.post(
        f"/admin/domain-products/{product_id}",
        data=data,
        headers=_ORIGIN,
        follow_redirects=False,
    )


def test_domain_products_card_save_renames_and_links() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    product = _seed(app, "Старое")
    response = _post_card(
        app.client,
        product.domain_product_id,
        {"name": "Новое", "catalog_code": "2311"},
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith(
        f"/admin/domain-products/{product.domain_product_id}",
    )
    stored = app.store.get(product.domain_product_id)
    assert stored is not None
    assert stored.name == "Новое"
    assert stored.catalog_code == "2311"
    page = app.client.get(response.headers["location"])
    assert "Новое" in page.text
    assert 'id="catalog-card-name"' in page.text
    assert ">Молоко<" in page.text
    assert 'id="catalog-card-code"' in page.text
    assert ">2311<" in page.text
    assert "2311 · Молоко" not in page.text


def test_domain_products_empty_code_keeps_link() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    product = _seed(app, "Связан", code="2311")
    response = _post_card(
        app.client,
        product.domain_product_id,
        {"name": "Связан", "catalog_code": "  "},
    )
    assert response.status_code == 303
    stored = app.store.get(product.domain_product_id)
    assert stored is not None
    assert stored.catalog_code == "2311"


def test_domain_products_empty_name_stays_on_card() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    product = _seed(app, "Держится", code="2311")
    response = _post_card(
        app.client,
        product.domain_product_id,
        {"name": " ", "catalog_code": "2311"},
    )
    assert response.status_code == 400
    assert "Название не может быть пустым." in response.text
    stored = app.store.get(product.domain_product_id)
    assert stored is not None
    assert stored.name == "Держится"
    assert stored.catalog_code == "2311"


def test_domain_products_unknown_code_stays_on_card() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    product = _seed(app, "Без кода")
    response = _post_card(
        app.client,
        product.domain_product_id,
        {"name": "Без кода", "catalog_code": "0000"},
    )
    assert response.status_code == 400
    assert "Кода нет в снимке." in response.text
    stored = app.store.get(product.domain_product_id)
    assert stored is not None
    assert stored.catalog_code is None


def test_domain_products_taken_card_stays_on_card() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    _seed(app, "Первый", code="2311")
    second = _seed(app, "Второй")
    response = _post_card(
        app.client,
        second.domain_product_id,
        {"name": "Второй", "catalog_code": "2311"},
    )
    assert response.status_code == 400
    assert "Карточка уже занята другим товаром." in response.text
    stored = app.store.get(second.domain_product_id)
    assert stored is not None
    assert stored.catalog_code is None


def test_domain_products_list_allows_domain_products_panel() -> None:
    # happy — ROSTER нужен только чтобы stub-login нашёл landing в nav
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    assert app.client.get("/admin/domain-products").status_code == 200
    assert app.client.get("/admin/domain-products/new").status_code == 200
    assert _import_file(app.client, filename="a.csv", content=b"n,c\nA,\n").status_code == 200


def test_domain_products_denied_without_planogram_curator() -> None:
    # edge — v1 связывают domain_products и planograms в одной роли; без неё — 403
    app = _build(panels=frozenset({AdminPanel.ROSTER}))
    _login(app.client)
    assert app.client.get("/admin/domain-products").status_code == 403
    assert _import_file(app.client, filename="a.csv", content=b"n,c\nA,\n").status_code == 403
    assert app.store.list_visible() == ()


def test_domain_products_forbidden_without_panel() -> None:
    # error
    app = _build(panels=frozenset({AdminPanel.ROSTER}))
    _login(app.client)
    product = "missing-product"
    paths = (
        "/admin/domain-products",
        "/admin/domain-products/new",
        f"/admin/domain-products/{product}",
    )
    for path in paths:
        assert app.client.get(path).status_code == 403
    assert _post_new(app.client, {"name": "Чужой"}).status_code == 403
    assert _post_card(app.client, product, {"action": "hide"}).status_code == 403
    assert app.store.list_visible() == ()


def test_domain_products_list_exposes_filter_markup() -> None:
    app = _build(
        panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}),
        cards=(_MILK, _ARCHIVED),
    )
    _login(app.client)
    unlinked = _seed(app, "Свободный")
    linked = _seed(app, "Живой", code="2311")
    archived = _seed(app, "Архивный", code="9001")
    broken = _seed(app, "Дыра")
    app.store.save(replace(broken, catalog_code="missing"))
    html = app.client.get("/admin/domain-products").text
    assert 'id="domain-products-search"' in html
    assert 'type="search"' in html
    assert 'id="domain-products-state-filter"' in html
    for state in ("все", "нет связи", "связана", "архив", "порвана"):
        assert state in html
    assert 'data-sort-key="name"' in html
    assert 'data-sort-key="state"' in html
    assert 'id="domain-products-visible-count"' in html
    assert "/admin/static/domain_products.js?v=" in html
    assert 'data-state="нет связи"' in html
    assert 'data-catalog-code="2311"' in html
    assert 'data-catalog-name="Молоко"' in html
    assert 'data-state="архив"' in html
    assert 'data-state="порвана"' in html
    assert f'href="/admin/domain-products/{unlinked.domain_product_id}"' in html
    assert f'href="/admin/domain-products/{linked.domain_product_id}"' in html
    assert f'href="/admin/domain-products/{archived.domain_product_id}"' in html
    assert f'href="/admin/domain-products/{broken.domain_product_id}"' in html


def test_domain_products_script_filters_and_sorts() -> None:
    script = Path("src/interfaces/admin/static/domain_products.js").read_text(encoding="utf-8")
    assert "domain-products-search" in script
    assert "domain-products-state-filter" in script
    assert "domain-products-visible-count" in script
    assert "data-name" in script
    assert "data-number" in script
    assert "data-catalog-code" in script
    assert "data-catalog-name" in script
    assert "data-state" in script
    assert "row.hidden" in script
    assert "data-sort-key" in script


def test_domain_products_catalog_cards_returns_at_most_eight() -> None:
    cards = (
        CatalogProduct(code="zz", name="Чай", archived=False),
        CatalogProduct(code="milk", name="Точный", archived=False),
    ) + tuple(
        CatalogProduct(code=f"milk{index}", name=f"Рядом {index}", archived=False)
        for index in range(8)
    )
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}), cards=cards)
    _login(app.client)
    response = app.client.get("/admin/domain-products/catalog-cards?q=milk")
    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is True
    assert len(body["cards"]) == 8
    assert body["cards"][0]["code"] == "milk"
    assert body["cards"][0]["name"] == "Точный"


def test_domain_products_catalog_cards_empty_query_is_empty() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    response = app.client.get("/admin/domain-products/catalog-cards?q=%20%20")
    assert response.status_code == 200
    assert response.json() == {"cards": [], "truncated": False}


def test_domain_products_catalog_cards_marks_hidden_holder() -> None:
    app = _build(
        panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}),
        cards=(_MILK,),
    )
    _login(app.client)
    hidden = _seed(app, "Скрытый держатель", code="2311")
    _post_card(app.client, hidden.domain_product_id, {"action": "hide"})
    body = app.client.get("/admin/domain-products/catalog-cards?q=2311").json()
    assert body["cards"][0]["taken"] is True
    assert body["cards"][0]["code"] == "2311"


def test_domain_products_catalog_cards_forbidden_without_domain_products_panel() -> None:
    app = _build(panels=frozenset({AdminPanel.ROSTER}))
    _login(app.client)
    assert app.client.get("/admin/domain-products/catalog-cards?q=2311").status_code == 403


def test_domain_products_card_shows_unlinked_catalog_line() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    product = _seed(app, "Свободный")
    html = app.client.get(f"/admin/domain-products/{product.domain_product_id}").text
    assert 'id="catalog-card-block"' in html
    assert "Карточка МойСклада" in html
    assert "Нет связанного товара" in html
    assert 'id="catalog-card-query"' in html
    assert "Обновление из МойСклада не настроено" in html
    assert 'value="refresh-catalog"' not in html


def test_domain_products_new_has_no_catalog_block() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    html = app.client.get("/admin/domain-products/new").text
    assert 'id="catalog-card-block"' not in html
    assert 'id="catalog-card-query"' not in html
    assert 'name="catalog_code"' not in html
    assert 'value="refresh-catalog"' not in html


def test_domain_products_card_keeps_catalog_code_field() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    product = _seed(app, "С полем", code="2311")
    html = app.client.get(f"/admin/domain-products/{product.domain_product_id}").text
    assert 'name="catalog_code"' in html
    assert 'value="2311"' in html
    assert 'id="catalog-card-name"' in html
    assert ">Молоко<" in html
    assert 'id="catalog-card-code"' in html
    assert ">2311<" in html
    assert "2311 · Молоко" not in html


def test_domain_products_card_shows_archived_catalog_line() -> None:
    app = _build(
        panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}),
        cards=(_ARCHIVED,),
    )
    _login(app.client)
    product = _seed(app, "Архив", code="9001")
    html = app.client.get(f"/admin/domain-products/{product.domain_product_id}").text
    assert 'id="catalog-card-name">Старое молоко архив' in html
    assert 'id="catalog-card-code">9001' in html
    assert "<p>архив</p>" not in html


def test_domain_products_card_shows_torn_catalog_line() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    product = _seed(app, "Порвана", code="2311")
    assert isinstance(app.lookup, FakeCatalogLookup)
    del app.lookup.cards["2311"]
    html = app.client.get(f"/admin/domain-products/{product.domain_product_id}").text
    assert "2311 порвана" in html
    assert 'id="catalog-card-name"' not in html


def test_domain_products_card_panel_and_hide_on_save_bar() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    product = _seed(app, "Панель")
    html = app.client.get(f"/admin/domain-products/{product.domain_product_id}").text
    assert 'id="catalog-card-block"' in html
    assert "admin-catalog-panel" in html
    assert "admin-catalog-link" in html
    assert "Нет связанного товара" in html
    assert 'class="admin-save-bar"' in html
    assert 'class="admin-btn-danger"' in html
    assert 'value="hide"' in html
    assert "Удалить" in html
    assert "Убрать" not in html
    save_bar = html.split('class="admin-save-bar"', 1)[1].split("</form>", 1)[0]
    assert save_bar.index("Удалить") < save_bar.index("Сохранить")


def test_domain_products_danger_css_overrides_generic_submit() -> None:
    css = Path("src/interfaces/admin/static/admin.css").read_text(encoding="utf-8")
    assert 'button.admin-btn-danger[type="submit"]' in css
    start = css.index('button.admin-btn-danger[type="submit"]')
    chunk = css[start : start + 180]
    assert "#b42318" in chunk


def test_domain_product_editor_css_name_field_uses_full_label_width() -> None:
    """happy: long product name field spans label width (LOK-294)."""

    css = Path("src/interfaces/admin/static/admin.css").read_text(encoding="utf-8")
    field_rules = re.findall(
        r"\.admin-entity-name-field\s*\{[^}]+\}",
        css,
        re.DOTALL,
    )
    assert field_rules, "missing .admin-entity-name-field rule"
    field_rule = field_rules[0]
    assert "max-width" in field_rule
    assert "100%" in field_rule

    input_rules = re.findall(
        r"\.admin-entity-name-field\s+input\s*\{[^}]+\}",
        css,
        re.DOTALL,
    )
    assert input_rules, "missing .admin-entity-name-field input rule"
    assert "width: 100%" in input_rules[0] or "width:100%" in input_rules[0]


def test_domain_product_editor_name_field_markup_has_width_class() -> None:
    """happy: editor markup marks Name label for wide input (LOK-294)."""
    template = Path("src/interfaces/admin/templates/domain_product_editor.html").read_text(
        encoding="utf-8",
    )
    assert 'class="admin-entity-name-field"' in template
    assert 'name="name"' in template
    name_label = template.split('class="admin-entity-name-field"', 1)[1]
    assert 'name="name"' in name_label.split("</label>", 1)[0]


def test_domain_product_editor_script_fetches_catalog_cards() -> None:
    script = Path("src/interfaces/admin/static/domain_product_editor.js").read_text(
        encoding="utf-8",
    )
    assert "catalog-card-query" in script
    assert "/admin/domain-products/catalog-cards?q=" in script
    assert 'input[name="catalog_code"]' in script
    assert "preventDefault" in script
    assert "Нет связанного товара" not in script
    assert "catalog-card-name" in script
    assert "catalog-card-code" in script
    assert "Имя" in script
    assert "Статус" in script
    assert 'createElement("tr")' in script
    assert 'createElement("li")' not in script


def test_domain_product_editor_script_ignores_stale_catalog_cards() -> None:
    script = Path("src/interfaces/admin/static/domain_product_editor.js").read_text(
        encoding="utf-8",
    )
    assert '(queryEl.value || "") !== query' in script


def test_domain_product_editor_hide_is_not_default_submit() -> None:
    """happy: Enter saves; hide only on click (ISS-453)."""
    template = Path("src/interfaces/admin/templates/domain_product_editor.html").read_text(
        encoding="utf-8",
    )
    assert 'id="domain-product-hide"' in template
    assert 'type="button" id="domain-product-hide"' in template
    assert 'name="action" value="hide"' not in template
    assert ">Сохранить</button>" in template
    script = Path("src/interfaces/admin/static/domain_product_editor.js").read_text(
        encoding="utf-8",
    )
    assert "domain-product-hide" in script
    assert 'input.value = "hide"' in script


class _GatedAssortment:
    def __init__(self) -> None:
        self.entered = 0
        self.release = asyncio.Event()

    async def list_by_folder_ids(
        self,
        *,
        entity_kind: str,
        folder_ids: Sequence[UUID],
    ) -> list[MsProductEntry]:
        _ = entity_kind, folder_ids
        self.entered += 1
        await self.release.wait()
        return [MsProductEntry("7777", "Свежее", MsEntityKind.PRODUCT)]


def test_domain_products_refresh_keeps_unsaved_name_and_skips_link() -> None:
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
    product = _seed(app, "Старое")
    opened = app.client.get(f"/admin/domain-products/{product.domain_product_id}")
    assert 'value="refresh-catalog"' in opened.text
    response = _post_card(
        app.client,
        product.domain_product_id,
        {"action": "refresh-catalog", "name": "Черновик", "catalog_code": "7777"},
    )
    assert response.status_code == 200
    assert 'value="Черновик"' in response.text
    assert 'value="7777"' in response.text
    assert "Снимок: 24.09.2026 11:00" in response.text
    assert "UTC" not in response.text
    stored = app.store.get(product.domain_product_id)
    assert stored is not None
    assert stored.name == "Старое"
    assert stored.catalog_code is None
    found = app.client.get("/admin/domain-products/catalog-cards?q=7777").json()
    assert found["cards"][0]["code"] == "7777"
    assert found["cards"][0]["name"] == "Свежее"


def test_domain_products_refresh_failure_keeps_snapshot_and_shows_error() -> None:
    prior = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    snapshot_store = InMemoryReferenceDataSnapshotStore()
    snapshot_store.put(
        ReferenceDataSnapshot(
            source_id=ReferenceDataSourceId.PRODUCT_CATALOG,
            rows=(
                ("code", "name", "entity_kind", "archived"),
                ("2311", "Молоко", "product", "false"),
            ),
            content_hash="sha256:old",
            last_fetched_at=prior,
            content_updated_at=prior,
        ),
    )

    class _Down:
        async def list_by_folder_ids(
            self,
            *,
            entity_kind: str,
            folder_ids: object,
        ) -> list[MsProductEntry]:
            _ = entity_kind, folder_ids
            raise RuntimeError("ms down")

    sync = SyncProductCatalogFromMs(
        reader=_Down(),
        store=snapshot_store,
        provider=ReferenceDataProvider(),
        product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
        now=lambda: datetime(2026, 9, 24, 8, 0, tzinfo=UTC),
    )
    app = _build(
        panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}),
        product_catalog_sync=sync.sync_once,
        catalog_snapshot_store=snapshot_store,
    )
    _login(app.client)
    product = _seed(app, "Старое")
    response = _post_card(
        app.client,
        product.domain_product_id,
        {"action": "refresh-catalog", "name": "Черновик", "catalog_code": "7777"},
    )
    assert response.status_code == 200
    assert "ms down" in response.text
    assert "Снимок: 01.09.2026 11:00" in response.text
    assert "UTC" not in response.text
    stored = app.store.get(product.domain_product_id)
    assert stored is not None
    assert stored.name == "Старое"
    assert stored.catalog_code is None
    kept = snapshot_store.get(ReferenceDataSourceId.PRODUCT_CATALOG)
    assert kept is not None
    assert kept.last_fetched_at == prior


def test_domain_products_card_hides_refresh_when_sync_missing() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    product = _seed(app, "Без синка")
    html = app.client.get(f"/admin/domain-products/{product.domain_product_id}").text
    assert "Обновление из МойСклада не настроено" in html
    assert 'value="refresh-catalog"' not in html


def test_domain_products_refresh_joins_running_walk() -> None:
    catalog_provider = ReferenceDataProvider()
    snapshot_store = InMemoryReferenceDataSnapshotStore()
    gated = _GatedAssortment()
    sync = SyncProductCatalogFromMs(
        reader=gated,
        store=snapshot_store,
        provider=catalog_provider,
        product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
        now=lambda: datetime(2026, 9, 24, 8, 0, tzinfo=UTC),
    )
    app = _build(
        panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}),
        lookup=SnapshotCatalogProductLookup(catalog_provider),
        product_catalog_sync=sync.sync_once,
        catalog_snapshot_store=snapshot_store,
    )
    product = create_domain_product("Старое", store=app.store, lookup=app.lookup)

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app.http)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            login = await client.post(
                "/admin/auth/stub",
                data={"telegram_user_id": str(_ADMIN_TG)},
            )
            assert login.status_code in {302, 303}

            async def release_later() -> None:
                while gated.entered < 1:
                    await asyncio.sleep(0)
                await asyncio.sleep(0.05)
                gated.release.set()

            url = f"/admin/domain-products/{product.domain_product_id}"
            payload = {"action": "refresh-catalog", "name": "Черновик", "catalog_code": "7777"}
            first, second, _released = await asyncio.gather(
                client.post(url, data=payload, headers=_ORIGIN),
                client.post(url, data=payload, headers=_ORIGIN),
                release_later(),
            )
            assert first.status_code == 200
            assert second.status_code == 200

    asyncio.run(scenario())
    assert gated.entered == 1
    stored = app.store.get(product.domain_product_id)
    assert stored is not None
    assert stored.catalog_code is None


def test_domain_products_list_shows_supplier_column_when_mirror_enabled() -> None:
    # happy
    app = _build_with_mirror(mirrors=(_FILLED_MIRROR,))
    _login(app.client)
    _seed(app, "Молоко домен", code="2311")
    html = app.client.get("/admin/domain-products").text
    assert "Поставщик" in html
    assert _SUPPLIER_NAME in html
    assert f'data-supplier="{_SUPPLIER_NAME}"' in html
    assert ">0<" not in html
    assert "0,00" not in html


def test_domain_products_list_shows_em_dash_when_no_supplier() -> None:
    # edge
    app = _build_with_mirror()
    _login(app.client)
    _seed(app, "Без связи")
    linked = _seed(app, "Связь без зеркала", code="2311")
    html = app.client.get("/admin/domain-products").text
    assert "Поставщик" in html
    assert 'data-supplier="—"' in html
    assert linked.name in html
    assert ">0<" not in html
    assert "0,00" not in html


def test_domain_products_list_hides_supplier_column_when_mirror_disabled() -> None:
    # edge
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    _seed(app, "Виден", code="2311")
    html = app.client.get("/admin/domain-products").text
    assert "Поставщик" not in html
    assert "data-supplier" not in html


def test_domain_products_list_sorts_by_supplier_attr() -> None:
    # happy
    app = _build_with_mirror(mirrors=(_FILLED_MIRROR,))
    _login(app.client)
    _seed(app, "Молоко домен", code="2311")
    html = app.client.get("/admin/domain-products").text
    assert 'data-sort-key="supplier"' in html


def test_domain_product_card_shows_procurement_block_when_enabled() -> None:
    # happy
    app = _build_with_mirror(mirrors=(_FILLED_MIRROR,))
    _login(app.client)
    product = _seed(app, "Молоко домен", code="2311")
    html = app.client.get(f"/admin/domain-products/{product.domain_product_id}").text
    expected_moment = format_admin_moment(_SUPPLY_MOMENT, ZoneInfo("Europe/Moscow"))
    assert "Последняя приёмка" in html
    assert _SUPPLIER_NAME in html
    assert "12,50" in html
    assert expected_moment in html
    assert 'name="supplier' not in html
    assert 'name="last_buy_price"' not in html
    assert 'name="supply_moment"' not in html
    assert "agent-1" not in html


def test_domain_product_card_procurement_em_dash_when_empty() -> None:
    # edge
    app = _build_with_mirror(mirrors=(_EMPTY_MIRROR,))
    _login(app.client)
    product = _seed(app, "Пустая приёмка", code="2311")
    html = app.client.get(f"/admin/domain-products/{product.domain_product_id}").text
    assert "Последняя приёмка" in html
    assert "—" in html
    assert "0,00" not in html
    assert ">0<" not in html
    assert 'name="supplier' not in html


def test_domain_product_card_hides_procurement_when_disabled() -> None:
    # edge
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.ROSTER}))
    _login(app.client)
    product = _seed(app, "Без зеркала", code="2311")
    html = app.client.get(f"/admin/domain-products/{product.domain_product_id}").text
    assert "Последняя приёмка" not in html
    assert "Поставщик" not in html
    assert "12,50" not in html
