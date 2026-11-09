from __future__ import annotations

import hashlib
import hmac
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.master_data import InMemoryMasterDataStores
from src.application.matrix_automation.matrix_sku_catalog import MatrixSkuCatalogEntry
from src.application.matrix_automation.matrix_sku_catalog_memory import (
    InMemoryMatrixSkuCatalogStore,
)
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes
from src.interfaces.admin.session import admin_session_cookie_name, pack_admin_session

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_TECH_TG = 2002
_FROZEN_NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _FakeMsProduct:
    code: str
    name: str
    archived: bool = False


class _FakeSnackAssortmentReader:
    def __init__(
        self,
        items: dict[str, str],
        *,
        archived_codes: frozenset[str] | set[str] = frozenset(),
        fail: bool = False,
    ) -> None:
        self._items = items
        self._archived_codes = frozenset(archived_codes)
        self._fail = fail

    async def list_by_folder_ids(
        self,
        *,
        entity_kind: str,
        folder_ids: Sequence[UUID],
    ) -> list[_FakeMsProduct]:
        if self._fail:
            raise RuntimeError("ms unavailable")
        return [
            _FakeMsProduct(
                code=code,
                name=name,
                archived=code in self._archived_codes,
            )
            for code, name in self._items.items()
        ]


def _widget_hash(fields: dict[str, str], bot_token: str) -> str:
    data_check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields) if key != "hash")
    secret = hashlib.sha256(bot_token.encode()).digest()
    return hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()


def _signed_widget_fields(*, tg: int = _ADMIN_TG) -> dict[str, str]:
    fields = {
        "id": str(tg),
        "auth_date": str(int(_FROZEN_NOW.timestamp())),
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


def _build_catalog_app(
    *,
    sku_catalog_master_enabled: bool = True,
    with_master_panel: bool = True,
    catalog: InMemoryMatrixSkuCatalogStore | None = None,
    snack_sku_assortment_reader: _FakeSnackAssortmentReader | None = None,
    wire_default_snack_reader: bool = True,
    snack_sku_folder_ids: tuple[UUID, ...] = (UUID("11111111-1111-1111-1111-111111111111"),),
    admin_max_body_bytes: int = 1_048_576,
) -> tuple[FastAPI, AdminHttpDeps, InMemoryMatrixSkuCatalogStore]:
    provider = ReferenceDataProvider()
    role = "администратор" if with_master_panel else "техник"
    tg = _ADMIN_TG if with_master_panel else _TECH_TG
    provider.apply_rows(
        ReferenceDataSourceId.BOT_USERS,
        [
            *_admin_rows(role=role, tg=tg),
            ["u2", "Иван", "техник", "3003", "001", "да"],
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
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_CATALOG,
        [
            ["code", "name", "entity_kind"],
            ["P1", "Product One", "product"],
            ["P2", "Product Two", "product"],
        ],
    )
    roster_store = InMemoryLocationRosterStore()
    provider.configure_roster(enabled=True, store=roster_store)
    master_stores = InMemoryMasterDataStores()
    sku_store = catalog if catalog is not None else InMemoryMatrixSkuCatalogStore()
    if snack_sku_assortment_reader is not None:
        reader: _FakeSnackAssortmentReader | None = snack_sku_assortment_reader
    elif wire_default_snack_reader:
        reader = _FakeSnackAssortmentReader({"1616": "Чудо", "9999": "Snack B"})
    else:
        reader = None
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
        admin_max_body_bytes=admin_max_body_bytes,
        master_stores=master_stores,
        sku_catalog_master_enabled=sku_catalog_master_enabled,
        matrix_sku_catalog_store=sku_store if sku_catalog_master_enabled else None,
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
        snack_sku_assortment_reader=reader if sku_catalog_master_enabled else None,
        snack_sku_folder_ids=snack_sku_folder_ids if sku_catalog_master_enabled else (),
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return app, deps, sku_store


def _authed_client(app: FastAPI, *, tg: int = _ADMIN_TG) -> TestClient:
    client = TestClient(app)
    if tg == _ADMIN_TG:
        client.post("/admin/auth/telegram", data=_signed_widget_fields())
    else:
        token = pack_admin_session(
            telegram_user_id=tg,
            issued_at=int(_FROZEN_NOW.timestamp()),
            secret=_SESSION_SECRET,
        )
        client.cookies.set(admin_session_cookie_name(), token)
    return client


def test_demo_matrix_sku_catalog_html_exists() -> None:
    path = Path("src/interfaces/admin/static/demo-matrix-sku-catalog.html")
    text = path.read_text(encoding="utf-8")
    assert "SKU матрицы" in text
    assert "admin-save-bar" in text
    assert "admin-cell-input" in text
    assert 'id="matrix-sku-catalog-table"' in text
    assert "matrix-sku-archived-filter" in text
    assert "data-archived" in text
    assert "matrix_sku_catalog.js" in text


def test_admin_css_matrix_sku_catalog_layout_and_sticky_default() -> None:
    """happy: SKU table headers centered + narrow cols; thead sticky without pin by default."""
    css = Path("src/interfaces/admin/static/admin.css").read_text(encoding="utf-8")
    assert "#matrix-sku-catalog-table thead th" in css
    assert "text-align: center" in css
    assert "#matrix-sku-catalog-table th:nth-child(1)" in css
    assert "#matrix-sku-catalog-table th:nth-child(2)" in css
    assert "#matrix-sku-catalog-table th:nth-child(4)" in css
    assert "#matrix-sku-catalog-table th:nth-child(5)" in css
    assert "width: 0" in css
    assert "white-space: nowrap" in css
    thead_block = css[
        css.find("table.admin-roster thead th") : css.find(
            ".admin-roster-chrome table.admin-roster thead th"
        )
    ]
    assert "top: var(--admin-app-header-height)" in thead_block
    assert "admin-roster-chrome-pin-offset" not in thead_block
    chrome_thead = css[css.find(".admin-roster-chrome table.admin-roster thead th") :]
    chrome_slice = chrome_thead[: chrome_thead.find("}") + 1]
    assert "admin-roster-chrome-pin-offset" in chrome_slice


def test_matrix_sku_catalog_shows_archived_status_and_filter() -> None:
    """happy: статус-колонка, data-archived, filter select default active."""
    app, _deps, _store = _build_catalog_app(
        snack_sku_assortment_reader=_FakeSnackAssortmentReader(
            {"1616": "Чудо", "OLD": "Archived snack"},
            archived_codes={"OLD"},
        ),
    )
    client = _authed_client(app)
    resp = client.get("/admin/matrix-sku-catalog")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="matrix-sku-archived-filter"' in html
    assert 'value="active" selected' in html or 'selected value="active"' in html
    assert 'value="archived"' in html
    assert 'value="all"' in html
    assert 'data-archived="false"' in html
    assert 'data-archived="true"' in html
    assert "✅" in html
    assert "❌" in html
    # archived row still in DOM (filter is client-side)
    assert 'value="OLD"' in html or "OLD" in html


def test_matrix_sku_catalog_archived_css_and_js_markers() -> None:
    """happy: CSS status col + JS file markers."""
    css = Path("src/interfaces/admin/static/admin.css").read_text(encoding="utf-8")
    assert "#matrix-sku-catalog-table th:nth-child(1)" in css
    assert "#matrix-sku-catalog-table th:nth-child(2)" in css
    assert "#matrix-sku-catalog-table th:nth-child(5)" in css
    js = Path("src/interfaces/admin/static/matrix_sku_catalog.js").read_text(encoding="utf-8")
    assert "matrix-sku-archived-filter" in js
    assert "data-archived" in js
    assert "row.hidden" in js
    assert "disabled" not in js  # не disable inputs скрытых строк


def test_matrix_sku_catalog_list_ok() -> None:
    app, _deps, store = _build_catalog_app(
        snack_sku_assortment_reader=_FakeSnackAssortmentReader(
            {"1616": "Чудо", "9999": "Snack B", "P1": "Product One"}
        ),
    )
    store.upsert(
        MatrixSkuCatalogEntry(
            product_code="P1",
            display_name="Product One",
            capacity=5,
            product_multiplier=Decimal("1"),
        )
    )
    client = _authed_client(app)
    response = client.get("/admin/matrix-sku-catalog")
    assert response.status_code == 200
    assert "P1" in response.text
    assert "Product One" in response.text


def test_matrix_sku_catalog_404_flag_off() -> None:
    app, _deps, _store = _build_catalog_app(sku_catalog_master_enabled=False)
    client = _authed_client(app)
    assert client.get("/admin/matrix-sku-catalog").status_code == 404


def test_matrix_sku_catalog_403_without_panel() -> None:
    app, _deps, _store = _build_catalog_app(with_master_panel=False)
    client = _authed_client(app, tg=_TECH_TG)
    assert client.get("/admin/matrix-sku-catalog").status_code == 403


def test_matrix_sku_catalog_list_shows_ms_rows() -> None:
    app, _deps, _store = _build_catalog_app()
    client = _authed_client(app)
    r = client.get("/admin/matrix-sku-catalog")
    assert r.status_code == 200
    assert "1616" in r.text
    assert "admin-cell-input" in r.text
    assert "Добавить SKU" not in r.text
    assert "P2" not in r.text  # sellable coffee-ish leftover из PRODUCT_CATALOG fixture


def test_matrix_sku_catalog_has_single_save_bar() -> None:
    app, _deps, _store = _build_catalog_app()
    client = _authed_client(app)
    r = client.get("/admin/matrix-sku-catalog")
    # Exact class (not substring of admin-save-bar-inner): one fixed save bar.
    assert r.text.count('class="admin-save-bar"') == 1
    assert "Сохранить" in r.text


def test_matrix_sku_catalog_no_enroll_section() -> None:
    app, _deps, _store = _build_catalog_app()
    client = _authed_client(app)
    r = client.get("/admin/matrix-sku-catalog")
    assert 'name="action" value="enroll"' not in r.text


def test_matrix_sku_catalog_bulk_save_post() -> None:
    app, _deps, store = _build_catalog_app()
    client = _authed_client(app)
    r = client.post(
        "/admin/matrix-sku-catalog",
        data={
            "action": "bulk_save",
            "product_code": ["1616", "9999"],
            "display_name": ["Чудо", "Snack B"],
            "capacity": ["5", ""],
            "product_multiplier": ["1", "1"],
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    row_new = store.get("9999")
    row_old = store.get("1616")
    assert row_new is not None and row_new.capacity == 0
    assert row_old is not None and row_old.capacity == 5


def test_matrix_sku_catalog_bulk_save_empty_capacity_becomes_zero() -> None:
    app, _deps, store = _build_catalog_app()
    client = _authed_client(app)
    r = client.post(
        "/admin/matrix-sku-catalog",
        data={
            "action": "bulk_save",
            "product_code": ["9999"],
            "display_name": ["Snack B"],
            "capacity": [""],
            "product_multiplier": ["1"],
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    got = store.get("9999")
    assert got is not None and got.capacity == 0


def test_matrix_sku_catalog_bulk_save_rejects_negative_capacity() -> None:
    app, _deps, store = _build_catalog_app()
    client = _authed_client(app)
    r = client.post(
        "/admin/matrix-sku-catalog",
        data={
            "action": "bulk_save",
            "product_code": ["1616"],
            "display_name": ["Чудо"],
            "capacity": ["-1"],
            "product_multiplier": ["1"],
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert store.get("1616") is None


def test_matrix_sku_catalog_bulk_save_rejects_empty_display_name() -> None:
    app, _deps, store = _build_catalog_app()
    client = _authed_client(app)
    r = client.post(
        "/admin/matrix-sku-catalog",
        data={
            "action": "bulk_save",
            "product_code": ["1616"],
            "display_name": ["  "],
            "capacity": ["1"],
            "product_multiplier": ["1"],
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert store.get("1616") is None


def test_matrix_sku_catalog_ms_fail_shows_error() -> None:
    app, _deps, _store = _build_catalog_app(
        snack_sku_assortment_reader=_FakeSnackAssortmentReader({}, fail=True),
    )
    client = _authed_client(app)
    r = client.get("/admin/matrix-sku-catalog")
    assert r.status_code == 502
    assert "P1" not in r.text
    assert "1616" not in r.text
    assert "ассортимент" in r.text.lower() or "МойСклад" in r.text


def test_matrix_sku_catalog_empty_ms_does_not_use_sellable() -> None:
    app, _deps, _store = _build_catalog_app(
        snack_sku_assortment_reader=_FakeSnackAssortmentReader({}),
    )
    client = _authed_client(app)
    r = client.get("/admin/matrix-sku-catalog")
    assert r.status_code == 200
    assert "P1" not in r.text
    assert "Product One" not in r.text


def test_matrix_sku_catalog_without_reader_uses_enrolled_store() -> None:
    # happy / ADR-0083: no live Remap reader → enrolled Mongo rows, not 502
    store = InMemoryMatrixSkuCatalogStore()
    store.upsert(
        MatrixSkuCatalogEntry(
            product_code="1616",
            display_name="Чудо enrolled",
            capacity=5,
            product_multiplier=Decimal("1"),
        )
    )
    app, _deps, _store = _build_catalog_app(
        catalog=store,
        wire_default_snack_reader=False,
    )
    client = _authed_client(app)
    r = client.get("/admin/matrix-sku-catalog")
    assert r.status_code == 200
    assert "1616" in r.text
    assert "Чудо enrolled" in r.text
    assert "ассортимент" not in r.text.lower()


def test_matrix_sku_catalog_edit_keeps_code() -> None:
    """product_code immutable: edit form shows code as text/readonly; POST cannot rename code."""
    app, _deps, store = _build_catalog_app()
    store.upsert(
        MatrixSkuCatalogEntry(
            product_code="1616",
            display_name="Old",
            capacity=1,
            product_multiplier=Decimal("1"),
        )
    )
    client = _authed_client(app)
    get_r = client.get("/admin/matrix-sku-catalog")
    assert get_r.status_code == 200
    assert "1616" in get_r.text
    assert 'name="product_code"' in get_r.text or "readonly" in get_r.text.lower()
    post_r = client.post(
        "/admin/matrix-sku-catalog",
        data={
            "action": "bulk_save",
            "product_code": ["1616"],
            "display_name": ["Still 1616"],
            "capacity": ["2"],
            "product_multiplier": ["1"],
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert post_r.status_code in {302, 303, 200}
    assert store.get("1616") is not None
    assert store.get("P2") is None  # no rename-via-POST


def test_matrix_sku_catalog_bulk_save_invalid_row_leaves_catalog_unchanged() -> None:
    store = InMemoryMatrixSkuCatalogStore()
    store.upsert(
        MatrixSkuCatalogEntry(
            product_code="1616",
            display_name="Before",
            capacity=1,
            product_multiplier=Decimal("1"),
        )
    )
    app, _deps, catalog = _build_catalog_app(catalog=store)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    body = (
        "action=bulk_save"
        "&product_code=1616&display_name=After&capacity=2&product_multiplier=1"
        "&product_code=9999&display_name=X&capacity=-1&product_multiplier=1"
    )
    response = client.post(
        "/admin/matrix-sku-catalog",
        content=body,
        headers={
            "Origin": "http://testserver",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    assert response.status_code == 400
    entry = catalog.get("1616")
    assert entry is not None
    assert entry.display_name == "Before"
    assert entry.capacity == 1
