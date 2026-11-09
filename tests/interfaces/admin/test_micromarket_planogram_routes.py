from __future__ import annotations

import hashlib
import hmac
import io
import logging
import re
import time
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.application.product_identity.fakes import FakeCatalogLookup
from tests.interfaces.admin import test_planogram_panel_gates as panel_gates

from src.application.master_data import InMemoryMasterDataStores, MachineKind, MachineStatus
from src.application.master_data.models import MasterMachine
from src.application.micromarket_loading import (
    MicromarketLoadingCycleStore,
    MicromarketPlanogram,
    MicromarketPlanogramLine,
    MicromarketPlanogramShelf,
    ShopListPublishStatus,
)
from src.application.micromarket_loading.shop_list_publish_journal import (
    ShopListIntendedLine,
    ShopListPublishEffects,
    ShopListPublishJournalEntry,
    ShopListPublishJournalStatus,
    ShopListPublishTrigger,
)
from src.application.micromarket_loading.supply_order_forecast import (
    AlwaysUnavailableSupplyOrderForecast,
)
from src.application.product_identity import (
    CatalogProduct,
    DomainProduct,
    create_domain_product,
    link_domain_product,
)
from src.application.product_identity.ports import DomainProductStore
from src.application.product_identity.procurement_mirror import ProcurementMirror
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.reference_data.ms_product_catalog import MsEntityKind, MsProductEntry
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.domain.ids import MachineId
from src.domain.micromarket_loading import MicromarketDeviceStock
from src.domain.micromarket_loading.supply_order import (
    MicromarketSupplyOrder,
    MicromarketSupplyOrderLine,
    MicromarketSupplyOrderMachine,
)
from src.infrastructure.product_identity import MemoryDomainProductStore
from src.infrastructure.product_identity.memory_procurement_mirror_store import (
    MemoryProcurementMirrorStore,
)
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
    InMemoryMicromarketPlanogramStore,
    InMemoryMicromarketSupplyOrderStore,
    InMemoryShopListPublishJournal,
)
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.planogram_publish_messages import (
    NOTHING_SENT_MICROMARKET,
    skipped_names_message_micromarket,
)
from src.interfaces.admin.routes import register_admin_routes
from src.interfaces.admin.routes.micromarket_planogram import _parse_planogram_form
from src.interfaces.admin.routes.micromarket_planograms import _live_need_machine

_TABLE_JS_PATH = Path("src/interfaces/admin/static/micromarket_planogram_table.js")

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_FROZEN_NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
_FUTURE_ARRIVAL_FORM = "2026-10-10T15:00"
_PAST_ARRIVAL_FORM = "2026-09-01T10:00"
_SKIPPED_PREFIX_MICROMARKET = "Не отправлено, нет доменного товара: "


@dataclass(frozen=True, slots=True)
class _FakeMicromarketAssortmentReader:
    """In-memory fake: returns only codes mapped for the requested path names."""

    _by_path: dict[str, dict[str, str]]

    async def list_by_folder_ids(
        self,
        *,
        entity_kind: str,
        folder_ids: Sequence[UUID],
    ) -> list[MsProductEntry]:
        del entity_kind
        items: dict[str, str] = {}
        for path in folder_ids:
            items.update(self._by_path.get(path, {}))
        return [
            MsProductEntry(code=code, name=name, entity_kind=MsEntityKind.PRODUCT)
            for code, name in items.items()
        ]


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


def _seed_product_catalog(provider: ReferenceDataProvider) -> None:
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_CATALOG,
        [
            ["code", "name", "entity_kind"],
            ["2311", "Салат Цезарь", "product"],
            ["2312", "Вода 0.5", "product"],
        ],
    )


def _lookup_for(_store: DomainProductStore) -> FakeCatalogLookup:
    return FakeCatalogLookup(())


def _publishable_domain_product(
    store: MemoryDomainProductStore | None = None,
) -> tuple[MemoryDomainProductStore, DomainProduct]:
    products = store if store is not None else MemoryDomainProductStore()
    product = create_domain_product("Салат", store=products, lookup=_lookup_for(products))
    return products, product


_READY_FOLDER = "7203a901-b1b2-11f1-0a80-115a00344501"
_SNACKS_FOLDER = "4c2738f1-f43a-11ef-0a80-1a2b002150a4"


class FakeSupplyOrderCategoryFacts:
    def __init__(self, *, days: int = 7, fail: bool = False, missing_days: bool = False) -> None:
        self._days = days
        self._fail = fail
        self._missing_days = missing_days

    def fetch_by_catalog_codes(self, catalog_codes):
        from src.application.micromarket_loading.supply_order_category import (
            SupplyOrderCategoryFactsFetchFailed,
            SupplyOrderCategoryProductFacts,
        )

        if self._fail:
            return SupplyOrderCategoryFactsFetchFailed()
        return tuple(
            SupplyOrderCategoryProductFacts(
                catalog_code=code,
                folder_ancestor_ids=(_READY_FOLDER,),
                shelf_life_days=None if self._missing_days else self._days,
            )
            for code in catalog_codes
        )


def _build_app(
    *,
    machine_kind: MachineKind = MachineKind.MICRO_MARKET,
    machine_id: str = "701",
    folder_ids: tuple[UUID, ...] = (),
    micromarket_assortment_reader: _FakeMicromarketAssortmentReader | None = None,
    domain_product_store: DomainProductStore | None = None,
    micromarket_loading_cycle_store: MicromarketLoadingCycleStore | None = None,
    supply_order_category_facts: object | None = None,
    procurement_mirror_enabled: bool = False,
    procurement_mirror_store: object | None = None,
) -> tuple[FastAPI, AdminHttpDeps]:
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
    _seed_product_catalog(provider)
    roster_store = InMemoryLocationRosterStore()
    provider.configure_roster(enabled=True, store=roster_store)
    master_stores = InMemoryMasterDataStores()
    master_stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId(machine_id),
            kind=machine_kind,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        ),
    )
    planogram_store = InMemoryMicromarketPlanogramStore()
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
        users_enabled=False,
        micromarket_planogram_store=planogram_store,
        micromarket_stock_store=InMemoryMicromarketDeviceStockStore(),
        micromarket_loading_cycle_store=micromarket_loading_cycle_store,
        shop_list_publish_journal=InMemoryShopListPublishJournal(),
        micromarket_supply_order_store=InMemoryMicromarketSupplyOrderStore(),
        supply_order_category_facts=(
            FakeSupplyOrderCategoryFacts()
            if supply_order_category_facts is None
            else supply_order_category_facts  # type: ignore[arg-type]
        ),
        supply_order_demand_forecast=AlwaysUnavailableSupplyOrderForecast(),
        supply_order_snacks_folder_id=_SNACKS_FOLDER,
        supply_order_ready_meals_folder_id=_READY_FOLDER,
        supply_order_shelf_life_days_threshold=7,
        micromarket_ms_product_folder_ids=folder_ids,
        micromarket_assortment_reader=micromarket_assortment_reader,
        domain_product_store=domain_product_store,
        procurement_mirror_enabled=procurement_mirror_enabled,
        procurement_mirror_store=procurement_mirror_store,  # type: ignore[arg-type]
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return app, deps


def _seed_line(
    deps: AdminHttpDeps,
    *,
    product_code: str = "",
    domain_product_id: str | None = None,
    published: bool = False,
    kit_group_id: int | None = 6348,
    price_rub: Decimal = Decimal("10"),
    target_qty: int = 1,
    active: bool = True,
    extra_lines: tuple[MicromarketPlanogramLine, ...] = (),
) -> None:
    assert deps.micromarket_planogram_store is not None
    first = MicromarketPlanogramLine(
        product_code=product_code,
        target_qty=target_qty,
        price_rub=price_rub,
        active=active,
        sort_order=0,
        kit_group_id=kit_group_id,
        domain_product_id=domain_product_id,
    )
    lines = (first, *extra_lines)
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=lines,
            updated_at=_FROZEN_NOW,
            shop_list_status=(
                ShopListPublishStatus.PUBLISHED if published else ShopListPublishStatus.UNPUBLISHED
            ),
        ),
    )


def _build_app_with_micromarket_planogram() -> tuple[FastAPI, AdminHttpDeps]:
    return _build_app(machine_kind=MachineKind.MICRO_MARKET, machine_id="701")


def _build_app_with_snack_machine() -> tuple[FastAPI, AdminHttpDeps]:
    return _build_app(machine_kind=MachineKind.SNACK, machine_id="501")


def test_planogram_get_happy_for_micro_market() -> None:
    app, _deps = _build_app_with_micromarket_planogram()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert b"admin-save-bar" in response.content
    assert b"micromarket-planogram-form" in response.content
    assert "Добавить полку" not in response.text
    assert "add_shelf_kit_group_id" not in response.text
    assert "micromarket-planogram-copy-form" in response.text
    assert "Скопировать планограмму с" in response.text


def test_micromarket_planogram_has_bottom_scroll_spacer() -> None:
    # happy: spacer/min-height present so last row can scroll near top
    app, _deps = _build_app_with_micromarket_planogram()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert "planogram-scroll-spacer" in response.text
    css = Path("src/interfaces/admin/static/planogram.css").read_text(encoding="utf-8")
    assert ".planogram-scroll-spacer" in css
    assert "min-height: 100vh" in css


def test_planogram_post_persists_lines() -> None:
    app, deps = _build_app_with_micromarket_planogram()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram",
        data={
            "shelf_kit_group_id-0": "6348",
            "product_code-0": "2311",
            "target_qty-0": "5",
            "price_rub-0": "189.00",
            "active-0": "on",
            "kit_group_id-0": "6348",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    assert deps.micromarket_planogram_store is not None
    doc = deps.micromarket_planogram_store.get("701")
    assert doc is not None
    assert doc.lines[0].target_qty == 5
    assert doc.shelves == (MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),)


def test_micromarket_planogram_price_whole_rubles_display_and_save() -> None:
    # happy: 189 displays/saves as whole rubles (no .00 chrome)
    app, deps = _build_app_with_micromarket_planogram()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("", ((6348, "Основная"),)),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram",
        data={
            "shelf_kit_group_id-0": "6348",
            "product_code-0": "2311",
            "target_qty-0": "5",
            "price_rub-0": "189",
            "active-0": "on",
            "kit_group_id-0": "6348",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    assert deps.micromarket_planogram_store is not None
    doc = deps.micromarket_planogram_store.get("701")
    assert doc is not None
    assert doc.lines[0].price_rub == Decimal("189")
    page = client.get("/admin/micromarket-planograms/701")
    assert page.status_code == 200
    assert 'name="price_rub-0"\n                           value="189"' in page.text or (
        'name="price_rub-0"' in page.text and 'value="189"' in page.text
    )
    assert 'value="189.00"' not in page.text
    assert 'value="0.00"' not in page.text


def test_micromarket_planogram_rejects_non_integer_price_on_save() -> None:
    # edge: fractional price rejected on save
    app, deps = _build_app_with_micromarket_planogram()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram",
        data={
            "shelf_kit_group_id-0": "6348",
            "product_code-0": "2311",
            "target_qty-0": "5",
            "price_rub-0": "12,5",
            "active-0": "on",
            "kit_group_id-0": "6348",
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 400
    assert deps.micromarket_planogram_store is not None
    assert deps.micromarket_planogram_store.get("701") is None


def test_micromarket_planogram_empty_price_blocks_save() -> None:
    # edge: empty price → validation error (not coerced to 0)
    app, deps = _build_app_with_micromarket_planogram()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram",
        data={
            "shelf_kit_group_id-0": "6348",
            "product_code-0": "2311",
            "target_qty-0": "5",
            "price_rub-0": "",
            "active-0": "on",
            "kit_group_id-0": "6348",
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 400
    assert "цен" in response.text.casefold()
    assert deps.micromarket_planogram_store is not None
    assert deps.micromarket_planogram_store.get("701") is None


def test_micromarket_planogram_empty_price_keeps_prior_shelves() -> None:
    # error: missing price rejects save but UI keeps prior shelves/products (LOK-293)
    app, deps = _build_app_with_micromarket_planogram()
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=5,
                    price_rub=Decimal("189"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                ),
            ),
            shelves=(
                MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),
                MicromarketPlanogramShelf(kit_group_id=7001, sort_order=1),
            ),
            updated_at=_FROZEN_NOW,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram",
        data={
            "shelf_kit_group_id-0": "6348",
            "shelf_kit_group_id-1": "7001",
            "product_code-0": "2311",
            "target_qty-0": "5",
            "price_rub-0": "",
            "active-0": "on",
            "kit_group_id-0": "6348",
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 400
    assert "цен" in response.text.casefold()
    doc = deps.micromarket_planogram_store.get("701")
    assert doc is not None
    assert doc.lines[0].price_rub == Decimal("189")
    assert doc.shelves == (
        MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),
        MicromarketPlanogramShelf(kit_group_id=7001, sort_order=1),
    )
    text = response.text
    assert 'name="shelf_kit_group_id-0" value="6348"' in text
    assert 'name="shelf_kit_group_id-1" value="7001"' in text
    assert re.search(r'name="price_rub-\d+"[^>]*value="189"', text)
    assert re.search(r'name="product_code-\d+"[^>]*value="2311"', text)
    # enroll-only blank shelves would have empty product_code/price on every row
    assert any(
        code == "2311" for code in re.findall(r'name="product_code-\d+"[^>]*value="([^"]*)"', text)
    )


def test_micromarket_planogram_publish_blocked_when_price_zero() -> None:
    # error: typed 0 / unpriced active row blocks publish
    store, product = _publishable_domain_product()
    app, deps = _build_app(domain_product_store=store)
    events: list[object] = []

    class _Publisher:
        def publish(self, event: object) -> None:
            events.append(event)

    object.__setattr__(deps, "micromarket_shop_list_publisher", _Publisher())
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="",
                    target_qty=1,
                    price_rub=Decimal("0"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                    domain_product_id=product.domain_product_id,
                ),
            ),
            shelves=(MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),),
            updated_at=_FROZEN_NOW,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram/publish",
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 422
    assert "цен" in response.text.casefold()
    assert events == []


def test_planogram_wrong_kind_404() -> None:
    app, _deps = _build_app_with_snack_machine()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/machines/501/micromarket-planogram")
    assert response.status_code == 404


def test_planogram_duplicate_flash_preserves_form() -> None:
    app, _deps = _build_app_with_micromarket_planogram()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram",
        data={
            "shelf_kit_group_id-0": "6348",
            "product_code-0": "2311",
            "target_qty-0": "1",
            "price_rub-0": "10",
            "active-0": "on",
            "kit_group_id-0": "6348",
            "product_code-1": "2311",
            "target_qty-1": "2",
            "price_rub-1": "10",
            "active-1": "on",
            "kit_group_id-1": "6348",
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 400 or b"duplicate" in response.content.lower()
    assert b"2311" in response.content


def test_planogram_has_admin_save_bar() -> None:
    app, _deps = _build_app_with_micromarket_planogram()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert b"admin-save-bar" in response.content


def test_planogram_get_picker_respects_path_names() -> None:
    # Path filter does not drive domain-product enroll (spec out of scope); page still opens.
    app, _deps = _build_app(
        machine_kind=MachineKind.MICRO_MARKET,
        machine_id="701",
        folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
        micromarket_assortment_reader=_FakeMicromarketAssortmentReader(
            {"Готовая еда": {"2311": "Салат Цезарь"}},
        ),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert 'id="planogram-domain-product-options"' in response.text
    assert b"micromarket-planogram-form" in response.content
    assert "Добавить полку" not in response.text
    assert "add_shelf_kit_group_id" not in response.text


class _CountingMicromarketAssortmentReader:
    list_calls = 0

    async def list_by_folder_ids(
        self,
        *,
        entity_kind: str,
        folder_ids: Sequence[UUID],
    ) -> list[MsProductEntry]:
        del entity_kind, folder_ids
        type(self).list_calls += 1
        return []


def test_loading_tab_skips_folder_filter_moysklad_calls() -> None:
    from src.interfaces.admin.routes import micromarket_planogram as planogram_mod

    planogram_mod._PATH_ALLOWED_CODES_CACHE.clear()
    planogram_mod._PATH_ALLOWED_CODES_FAILED_AT.clear()
    _CountingMicromarketAssortmentReader.list_calls = 0
    folder_id = UUID("11111111-1111-1111-1111-111111111111")
    app, _deps = _build_app(
        machine_kind=MachineKind.MICRO_MARKET,
        machine_id="701",
        folder_ids=(folder_id,),
        micromarket_assortment_reader=_CountingMicromarketAssortmentReader(),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    loading = client.get("/admin/micromarket-planograms/701?tab=loading")
    assert loading.status_code == 200
    assert _CountingMicromarketAssortmentReader.list_calls == 0
    planogram = client.get("/admin/micromarket-planograms/701")
    assert planogram.status_code == 200
    assert _CountingMicromarketAssortmentReader.list_calls == 1


def test_machine_profile_has_no_planogram_loading_or_layout_links() -> None:
    micro_app, _micro_deps = _build_app_with_micromarket_planogram()
    micro_client = TestClient(micro_app)
    micro_client.post("/admin/auth/telegram", data=_signed_widget_fields())
    micro_profile = micro_client.get("/admin/machines/701")
    assert micro_profile.status_code == 200
    assert b"/machines/701/micromarket-planogram" not in micro_profile.content
    assert b"/machines/701/micromarket-loading" not in micro_profile.content
    assert b"/layout" not in micro_profile.content
    assert "← Парк" in micro_profile.text
    assert "Включать в логи отсутствия продаж" in micro_profile.text

    snack_app, snack_deps = _build_app_with_snack_machine()
    from src.application.matrix_automation.snack_machine_layout_memory import (
        InMemorySnackMachineLayoutStore,
    )

    object.__setattr__(snack_deps, "layout_master_enabled", True)
    object.__setattr__(snack_deps, "snack_layout_store", InMemorySnackMachineLayoutStore())
    snack_client = TestClient(snack_app)
    snack_client.post("/admin/auth/telegram", data=_signed_widget_fields())
    snack_profile = snack_client.get("/admin/machines/501")
    assert snack_profile.status_code == 200
    assert b"/machines/501/micromarket-planogram" not in snack_profile.content
    assert b"/machines/501/micromarket-loading" not in snack_profile.content
    assert b"/layout" not in snack_profile.content
    assert "← Парк" in snack_profile.text
    assert "Включать в логи отсутствия продаж" in snack_profile.text


def test_planogram_page_has_end_of_row_shelf_move() -> None:
    app, deps = _build_app_with_micromarket_planogram()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("", ((6348, "probe-Салаты"), (7001, "probe-Напитки"))),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    client.post(
        "/admin/machines/701/micromarket-planogram",
        data={
            "shelf_kit_group_id-0": "6348",
            "shelf_kit_group_id-1": "7001",
            "product_code-0": "2311",
            "target_qty-0": "5",
            "price_rub-0": "189",
            "kit_group_id-0": "6348",
            "active-0": "on",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert "probe-Салаты" in response.text
    assert 'name="kit_group_id-0"' in response.text
    assert 'type="hidden"' in response.text
    assert "planogram-move-shelf" in response.text
    assert 'aria-label="Перенести на полку"' in response.text
    assert 'aria-label="Полка"' not in response.text
    form_html = response.text.split('id="micromarket-planogram-form"', 1)[1].split("</form>", 1)[0]
    assert ">Полка<" not in form_html
    assert ">Группа<" not in form_html


def test_planogram_move_select_includes_current_shelf_option_hidden() -> None:
    # happy: product on shelf 10 keeps value="10" in DOM (hidden) so round-trip move works
    app, deps = _build_app_with_micromarket_planogram()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("", ((10, "Салаты"), (20, "Напитки"))),
    )
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=10,
                ),
            ),
            shelves=(
                MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),
                MicromarketPlanogramShelf(kit_group_id=20, sort_order=1),
            ),
            updated_at=_FROZEN_NOW,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    form_html = response.text.split('id="micromarket-planogram-form"', 1)[1].split("</form>", 1)[0]
    shelf_blocks = form_html.split('class="planogram-shelf"', 1)[1]
    shelf_select = shelf_blocks.split("planogram-move-shelf", 1)[1].split("</select>", 1)[0]
    assert re.search(r'<option value="10"[^>]*\bhidden\b', shelf_select)
    assert 'value="20"' in shelf_select
    table_js = _TABLE_JS_PATH.read_text(encoding="utf-8")
    assert "option.hidden = option.value === value" in table_js


def test_planogram_page_opens_when_groups_fail() -> None:
    app, deps = _build_app_with_micromarket_planogram()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("Группы Kit Shop не загрузились", ()),
    )
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=5,
                    price_rub=Decimal("189.00"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                ),
            ),
            shelves=(MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),),
            updated_at=_FROZEN_NOW,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert "Группы Kit Shop не загрузились" in response.text
    assert "Полка Kit #6348" in response.text
    assert 'name="kit_group_id-0"' in response.text
    assert 'name="shelf_kit_group_id-0"' in response.text


def test_planogram_page_shows_unpublished_and_publish_again() -> None:
    store, product = _publishable_domain_product()
    app, deps = _build_app(domain_product_store=store)
    events: list[object] = []

    class _Publisher:
        def publish(self, event: object) -> None:
            events.append(event)

    object.__setattr__(deps, "micromarket_shop_list_publisher", _Publisher())
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    save_response = client.post(
        "/admin/machines/701/micromarket-planogram",
        data={
            "shelf_kit_group_id-0": "6348",
            "domain_product_id-0": product.domain_product_id,
            "product_code-0": "",
            "target_qty-0": "5",
            "price_rub-0": "189.00",
            "active-0": "on",
            "kit_group_id-0": "6348",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert save_response.status_code in {302, 303}
    get_response = client.get("/admin/micromarket-planograms/701")
    assert get_response.status_code == 200
    assert "Опубликовать" in get_response.text
    assert "Список Kit:" not in get_response.text
    publish_response = client.post(
        "/admin/machines/701/micromarket-planogram/publish",
        headers={"Origin": "http://testserver"},
    )
    assert deps.micromarket_planogram_store is not None
    doc = deps.micromarket_planogram_store.get("701")
    assert doc is not None
    assert doc.lines[0].domain_product_id == product.domain_product_id
    assert doc.lines[0].target_qty == 5
    assert "Задача выполняется" in publish_response.text
    assert len(events) == 1


def test_publish_enqueues_and_shows_publishing() -> None:
    store, product = _publishable_domain_product()
    app, deps = _build_app(domain_product_store=store)
    events: list[object] = []

    class _Publisher:
        def publish(self, event: object) -> None:
            events.append(event)

    object.__setattr__(deps, "micromarket_shop_list_publisher", _Publisher())
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    client.post(
        "/admin/machines/701/micromarket-planogram",
        data={
            "shelf_kit_group_id-0": "6348",
            "domain_product_id-0": product.domain_product_id,
            "product_code-0": "",
            "target_qty-0": "5",
            "price_rub-0": "189.00",
            "kit_group_id-0": "6348",
            "active-0": "on",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    response = client.post(
        "/admin/machines/701/micromarket-planogram/publish",
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    assert "Задача выполняется" in response.text
    assert len(events) == 1


def test_publish_while_publishing_does_not_enqueue() -> None:
    store, product = _publishable_domain_product()
    app, deps = _build_app(domain_product_store=store)
    events: list[object] = []

    class _Publisher:
        def publish(self, event: object) -> None:
            events.append(event)

    object.__setattr__(deps, "micromarket_shop_list_publisher", _Publisher())
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    client.post(
        "/admin/machines/701/micromarket-planogram",
        data={
            "shelf_kit_group_id-0": "6348",
            "domain_product_id-0": product.domain_product_id,
            "product_code-0": "",
            "target_qty-0": "5",
            "price_rub-0": "189.00",
            "kit_group_id-0": "6348",
            "active-0": "on",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    first = client.post(
        "/admin/machines/701/micromarket-planogram/publish",
        headers={"Origin": "http://testserver"},
    )
    second = client.post(
        "/admin/machines/701/micromarket-planogram/publish",
        headers={"Origin": "http://testserver"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert "Публикация уже идёт" in second.text
    assert len(events) == 1


def test_publish_without_group_is_422() -> None:
    store, product = _publishable_domain_product()
    app, deps = _build_app(domain_product_store=store)
    events: list[object] = []

    class _Publisher:
        def publish(self, event: object) -> None:
            events.append(event)

    object.__setattr__(deps, "micromarket_shop_list_publisher", _Publisher())
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=None,
                    domain_product_id=product.domain_product_id,
                ),
            ),
            updated_at=datetime(2026, 9, 25, tzinfo=UTC),
        ),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram/publish",
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 422
    assert product.number in response.text
    assert events == []
    stored = deps.micromarket_planogram_store.get("701")
    assert stored is not None
    assert stored.shop_list_status is ShopListPublishStatus.UNPUBLISHED


def test_publish_after_failed_enqueues() -> None:
    store, product = _publishable_domain_product()
    app, deps = _build_app(domain_product_store=store)
    events: list[object] = []

    class _Publisher:
        def publish(self, event: object) -> None:
            events.append(event)

    object.__setattr__(deps, "micromarket_shop_list_publisher", _Publisher())
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                    domain_product_id=product.domain_product_id,
                ),
            ),
            updated_at=datetime(2026, 9, 25, tzinfo=UTC),
            shop_list_status=ShopListPublishStatus.FAILED,
            shop_list_error="База товаров на терминал не ушла",
            shop_list_publication_id="old",
        ),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram/publish",
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    assert "Задача выполняется" in response.text
    assert len(events) == 1


def test_publish_without_publisher_does_not_change_status() -> None:
    app, deps = _build_app_with_micromarket_planogram()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    client.post(
        "/admin/machines/701/micromarket-planogram",
        data={
            "shelf_kit_group_id-0": "6348",
            "product_code-0": "2311",
            "target_qty-0": "5",
            "price_rub-0": "189.00",
            "kit_group_id-0": "6348",
            "active-0": "on",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    response = client.post(
        "/admin/machines/701/micromarket-planogram/publish",
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    assert "Магазин Kit Shop для этого аппарата не найден" in response.text
    assert deps.micromarket_planogram_store is not None
    stored = deps.micromarket_planogram_store.get("701")
    assert stored is not None
    assert stored.shop_list_status is ShopListPublishStatus.UNPUBLISHED


def test_micromarket_planogram_picker_links_unlinked_product() -> None:
    store = MemoryDomainProductStore()
    product = create_domain_product("Кефир", store=store, lookup=_lookup_for(store))
    app, deps = _build_app(domain_product_store=store)
    _seed_line(
        deps,
        product_code="",
        domain_product_id=product.domain_product_id,
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert f'href="/admin/domain-products/{product.domain_product_id}"' in response.text
    assert 'target="_blank"' in response.text
    assert "planogram-product-unlinked" in response.text
    assert "planogram-product-search" in response.text
    assert 'aria-label="Новый товар"' not in response.text
    assert 'aria-label="Список товаров"' not in response.text
    assert ">Товар<" in response.text
    shelves = response.text.split('id="micromarket-planogram-shelves"', 1)[1]
    shelves = shelves.split('id="micromarket-assembly-table"', 1)[0]
    assert "planogram-shelf-table" in shelves
    assert ">Код<" not in shelves
    assert ">Имя<" not in shelves


def test_micromarket_planogram_legacy_code_has_no_unlinked_class() -> None:
    app, deps = _build_app(domain_product_store=MemoryDomainProductStore())
    _seed_line(deps, product_code="2311", domain_product_id=None)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert "planogram-product-unlinked" not in response.text
    assert "/admin/domain-products/" not in response.text
    assert "2311" in response.text


def test_micromarket_planogram_legacy_code_shows_matching_product() -> None:
    store = MemoryDomainProductStore()
    lookup = FakeCatalogLookup(
        (CatalogProduct(code="2311", name="Салат Цезарь", archived=False),),
    )
    product = create_domain_product("Салат", store=store, lookup=lookup)
    link_domain_product(product.domain_product_id, "2311", store=store, lookup=lookup)
    app, deps = _build_app(domain_product_store=store)
    _seed_line(deps, product_code="2311", domain_product_id=None)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert f'href="/admin/domain-products/{product.domain_product_id}"' in response.text
    assert "Салат" in response.text


def test_micromarket_planogram_missing_product_is_unlinked_without_link() -> None:
    app, deps = _build_app(domain_product_store=MemoryDomainProductStore())
    _seed_line(deps, product_code="", domain_product_id="missing")
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert "Товар не найден" in response.text
    assert "planogram-product-unlinked" in response.text
    assert 'href="/admin/domain-products/missing"' not in response.text
    assert 'name="domain_product_id-0"' in response.text
    assert 'value="missing"' in response.text


def test_micromarket_planogram_hides_create_when_product_store_missing() -> None:
    app, deps = _build_app(domain_product_store=None)
    _seed_line(deps, product_code="2311", domain_product_id=None)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert "planogram-product-search" in response.text
    assert 'aria-label="Новый товар"' not in response.text
    assert "planogram-product-create" not in response.text


def test_micromarket_planogram_save_keeps_unknown_domain_product_id() -> None:
    store = MemoryDomainProductStore()
    app, deps = _build_app(domain_product_store=store)
    _seed_line(
        deps,
        product_code="",
        domain_product_id="missing",
        price_rub=Decimal("10"),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram",
        data={
            "shelf_kit_group_id-0": "6348",
            "domain_product_id-0": "missing",
            "product_code-0": "",
            "target_qty-0": "1",
            "price_rub-0": "99",
            "active-0": "on",
            "kit_group_id-0": "6348",
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 422
    assert "unknown domain_product_id" in response.text
    assert deps.micromarket_planogram_store is not None
    doc = deps.micromarket_planogram_store.get("701")
    assert doc is not None
    assert doc.lines[0].price_rub == Decimal("10")
    assert doc.lines[0].domain_product_id == "missing"


def test_micromarket_publish_empty_snapshot_keeps_status_text() -> None:
    app, deps = _build_app()
    _seed_line(
        deps,
        product_code="2311",
        domain_product_id=None,
        published=True,
        kit_group_id=6348,
    )
    events: list[object] = []

    class _Publisher:
        def publish(self, event: object) -> None:
            events.append(event)

    object.__setattr__(deps, "micromarket_shop_list_publisher", _Publisher())
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram/publish",
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    assert NOTHING_SENT_MICROMARKET in response.text
    assert "МойСклад" not in response.text
    doc = deps.micromarket_planogram_store.get("701")
    assert doc is not None
    assert doc.shop_list_status is ShopListPublishStatus.PUBLISHED
    assert events == []


def test_micromarket_publish_skip_message_has_no_moysklad_phrase() -> None:
    store = MemoryDomainProductStore()
    lookup = FakeCatalogLookup(
        (CatalogProduct(code="2311", name="Салат Цезарь", archived=False),),
    )
    salad = create_domain_product("Салат", store=store, lookup=lookup)
    link_domain_product(salad.domain_product_id, "2311", store=store, lookup=lookup)
    app, deps = _build_app(domain_product_store=store)
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="legacy-only",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=None,
                    domain_product_id=None,
                ),
                MicromarketPlanogramLine(
                    product_code="",
                    target_qty=1,
                    price_rub=Decimal("20"),
                    active=True,
                    sort_order=1,
                    kit_group_id=6348,
                    domain_product_id=salad.domain_product_id,
                ),
            ),
            updated_at=_FROZEN_NOW,
        ),
    )
    events: list[object] = []

    class _Publisher:
        def publish(self, event: object) -> None:
            events.append(event)

    object.__setattr__(deps, "micromarket_shop_list_publisher", _Publisher())
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram/publish",
        headers={"Origin": "http://testserver"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    notice = skipped_names_message_micromarket(("legacy-only",))
    assert notice in response.text
    assert "МойСклад" not in notice
    assert "доменн" in notice.lower() or "товар" in notice.lower()
    assert events


def test_micromarket_publish_logs_skipped_count(caplog: pytest.LogCaptureFixture) -> None:
    store = MemoryDomainProductStore()
    lookup = FakeCatalogLookup(
        (CatalogProduct(code="2311", name="Салат Цезарь", archived=False),),
    )
    salad = create_domain_product("Салат", store=store, lookup=lookup)
    link_domain_product(salad.domain_product_id, "2311", store=store, lookup=lookup)
    app, deps = _build_app(domain_product_store=store)
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="legacy-kefir",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=None,
                    domain_product_id=None,
                ),
                MicromarketPlanogramLine(
                    product_code="",
                    target_qty=1,
                    price_rub=Decimal("20"),
                    active=True,
                    sort_order=1,
                    kit_group_id=6348,
                    domain_product_id=salad.domain_product_id,
                ),
            ),
            updated_at=_FROZEN_NOW,
        ),
    )
    events: list[object] = []

    class _Publisher:
        def publish(self, event: object) -> None:
            events.append(event)

    object.__setattr__(deps, "micromarket_shop_list_publisher", _Publisher())
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    with caplog.at_level(logging.INFO, logger="src.interfaces.admin.routes.micromarket_planogram"):
        response = client.post(
            "/admin/machines/701/micromarket-planogram/publish",
            headers={"Origin": "http://testserver"},
        )
    assert response.status_code == 200
    assert _SKIPPED_PREFIX_MICROMARKET + "legacy-kefir" in response.text or (
        _SKIPPED_PREFIX_MICROMARKET + "legacy-kefir"
        in unquote(response.headers.get("location", ""))
    )
    skipped = [
        record
        for record in caplog.records
        if record.getMessage() == "admin_planogram_publish_skipped"
    ]
    assert len(skipped) == 1
    assert skipped[0].skipped_count == 1
    assert "2311" not in repr(skipped[0].__dict__)
    assert len(events) == 1


def test_micromarket_planogram_options_json_escapes_script_breakout() -> None:
    store = MemoryDomainProductStore()
    create_domain_product("</script><img src=x>", store=store, lookup=_lookup_for(store))
    app, _deps = _build_app(domain_product_store=store)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    marker = 'id="planogram-domain-product-options">'
    start = response.text.index(marker) + len(marker)
    end = response.text.index("</script>", start)
    blob = response.text[start:end]
    assert "<" not in blob
    assert "\\u003c" in blob


def test_micromarket_planogram_page_includes_enroll_dnd_script() -> None:
    # happy: страница холодильника грузит enroll script; DnD-ручка полок — кусок 04
    app, _deps = _build_app_with_micromarket_planogram()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    html = response.text
    assert "micromarket_planogram_table.js" in html
    assert "micromarket_planogram_sort_key.js" in html
    assert 'id="micromarket-planogram-shelves"' in html


def test_micromarket_planogram_script_ensure_trailing_enroll_row() -> None:
    table_js = _TABLE_JS_PATH.read_text(encoding="utf-8")
    assert "ensureTrailingEnrollRow" in table_js or "ensureShelfEnrollRow" in table_js


def test_micromarket_planogram_script_reindexes_row_names() -> None:
    table_js = _TABLE_JS_PATH.read_text(encoding="utf-8")
    assert "reindexRowNames" in table_js
    assert "domain_product_id-" in table_js


def test_micromarket_planogram_script_keeps_one_enroll_per_shelf() -> None:
    # happy: одна enroll на полку; вставка по ключу; без row-DnD товара
    table_js = _TABLE_JS_PATH.read_text(encoding="utf-8")
    assert "micromarket-planogram-shelves" in table_js
    assert "ensureShelfEnrollRow" in table_js or "ensureTrailingEnrollRow" in table_js
    assert "planogram-enroll-row" in table_js
    assert "MicromarketPlanogramSortKey" in table_js or "comparePlanogramLines" in table_js
    assert "insertRowBySortKey" in table_js
    assert "bindRowDnD" not in table_js


def test_micromarket_planogram_script_shelf_move_control_relocates_row() -> None:
    # happy: end-of-row move control relocates row and persists kit_group_id
    table_js = _TABLE_JS_PATH.read_text(encoding="utf-8")
    assert "moveRowToShelf" in table_js
    assert "planogram-move-shelf" in table_js
    assert "bindShelfMove" in table_js
    assert "kit_group_id" in table_js
    assert "insertRowBySortKey" in table_js
    assert "target_qty" in table_js
    assert "pending_exit" in table_js
    assert "findShelfByKitGroupId" in table_js


def test_micromarket_planogram_script_skips_enroll_on_ungrouped_after_move() -> None:
    # error: ensureShelfEnrollRow не создаёт enroll в «Без полки»
    table_js = _TABLE_JS_PATH.read_text(encoding="utf-8")
    start = table_js.index("function ensureShelfEnrollRow")
    next_fn = table_js.index("\n  function ", start + 1)
    body = table_js[start:next_fn]
    assert "planogram-ungrouped" in body


def test_micromarket_planogram_script_reindexes_shelves_and_rows_before_submit() -> None:
    # happy: перед submit — shelf_kit_group_id и строки; DnD только полок
    table_js = _TABLE_JS_PATH.read_text(encoding="utf-8")
    assert "reindexShelfNames" in table_js
    assert "shelf_kit_group_id-" in table_js
    assert "reindexRowNames" in table_js
    assert "bindShelfDnD" in table_js
    assert "submit" in table_js
    assert "bindRowDnD" not in table_js


def test_micromarket_planogram_clear_empty_shelf_enabled_only_when_empty() -> None:
    # edge: снятие только пустой; collapse без form-поля; GET раскрыты; pending_exit
    app, deps = _build_app_with_micromarket_planogram()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("", ((10, "Салаты"), (20, "Напитки"))),
    )
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=10,
                    pending_exit=True,
                ),
            ),
            shelves=(
                MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),
                MicromarketPlanogramShelf(kit_group_id=20, sort_order=1),
            ),
            updated_at=_FROZEN_NOW,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    html = response.text
    assert "is-collapsed" not in html
    assert 'name="collapsed"' not in html
    assert 'name="shelf_collapsed' not in html
    assert "planogram-pending-exit" in html

    filled_clear = 'data-kit-group-id="10"'
    empty_clear = 'data-kit-group-id="20"'
    filled_chunk = html[html.index(filled_clear) : html.index(empty_clear)]
    empty_chunk = html[html.index(empty_clear) :]
    assert "planogram-shelf-clear" in filled_chunk
    assert "disabled" in filled_chunk[filled_chunk.index("planogram-shelf-clear") :][:120]
    clear_btn = empty_chunk[empty_chunk.index("planogram-shelf-clear") :][:160]
    assert "disabled" not in clear_btn

    table_js = _TABLE_JS_PATH.read_text(encoding="utf-8")
    assert "toggleShelfCollapse" in table_js
    assert "clearEmptyShelf" in table_js
    assert "updateShelfClearButton" in table_js
    css = Path("src/interfaces/admin/static/planogram.css").read_text(encoding="utf-8")
    assert "is-collapsed" in css
    assert ".planogram-pending-exit" in css


def test_micromarket_planogram_parse_skips_empty_trailing_row() -> None:
    # edge: пустая хвостовая строка без id/кода не попадает в lines
    parsed = {
        "shelf_kit_group_id-0": ["6348"],
        "domain_product_id-0": ["dp-salad"],
        "product_code-0": [""],
        "target_qty-0": ["5"],
        "price_rub-0": ["189.00"],
        "active-0": ["on"],
        "kit_group_id-0": ["6348"],
        "domain_product_id-1": [""],
        "product_code-1": [""],
        "target_qty-1": ["0"],
        "price_rub-1": ["0"],
        "active-1": ["on"],
        "kit_group_id-1": [""],
    }
    _shelves, lines = _parse_planogram_form(parsed)
    assert len(lines) == 1
    assert lines[0].sort_order == 0
    assert lines[0].domain_product_id == "dp-salad"


def test_parse_planogram_form_reads_pending_exit_and_forces_active() -> None:
    # happy: hidden pending_exit; active всегда true даже без active-* в POST
    checked_shelves, checked = _parse_planogram_form(
        {
            "shelf_kit_group_id-0": ["6348"],
            "product_code-0": ["2311"],
            "target_qty-0": ["1"],
            "price_rub-0": ["10"],
            "pending_exit-0": ["1"],
            "kit_group_id-0": ["6348"],
        }
    )
    assert checked_shelves == (MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),)
    assert len(checked) == 1
    assert checked[0].pending_exit is True
    assert checked[0].active is True
    _unchecked_shelves, unchecked = _parse_planogram_form(
        {
            "shelf_kit_group_id-0": ["6348"],
            "product_code-0": ["2311"],
            "target_qty-0": ["1"],
            "price_rub-0": ["10"],
            "kit_group_id-0": ["6348"],
        }
    )
    assert unchecked[0].pending_exit is False
    assert unchecked[0].active is True


def test_parse_planogram_form_missing_active_checkbox_is_not_false() -> None:
    # error: отсутствие чекбокса Active не роняет строку и не пишет active=false
    _shelves, lines = _parse_planogram_form(
        {
            "shelf_kit_group_id-0": ["6348"],
            "product_code-0": ["2311"],
            "target_qty-0": ["2"],
            "price_rub-0": ["15"],
            "kit_group_id-0": ["6348"],
        }
    )
    assert len(lines) == 1
    assert lines[0].active is True
    assert lines[0].product_code == "2311"
    assert lines[0].target_qty == 2


def test_planogram_get_legacy_doc_groups_into_shelves() -> None:
    # happy: shelves is None → блоки по группам; «Без полки»; нет колонки «Группа»
    app, deps = _build_app_with_micromarket_planogram()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("", ((10, "Салаты"), (20, "Напитки"))),
    )
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=10,
                ),
                MicromarketPlanogramLine(
                    product_code="2312",
                    target_qty=1,
                    price_rub=Decimal("20"),
                    active=True,
                    sort_order=1,
                    kit_group_id=20,
                ),
                MicromarketPlanogramLine(
                    product_code="2313",
                    target_qty=1,
                    price_rub=Decimal("30"),
                    active=False,
                    sort_order=2,
                    kit_group_id=None,
                ),
            ),
            shelves=None,
            updated_at=_FROZEN_NOW,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    html = response.text
    assert 'name="shelf_kit_group_id-0" value="10"' in html
    assert 'name="shelf_kit_group_id-1" value="20"' in html
    assert "Без полки" in html
    form_html = html.split('id="micromarket-planogram-form"', 1)[1].split("</form>", 1)[0]
    assert ">Полка<" not in form_html
    assert "planogram-move-shelf" in form_html
    assert 'name="kit_group_id-' in form_html
    assert ">Группа<" not in form_html


def test_planogram_get_recorded_shelves_and_ungrouped_block() -> None:
    # happy: записанные полки (в т.ч. пустая); orphan → «Без полки» без enroll
    app, deps = _build_app_with_micromarket_planogram()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("", ((10, "Салаты"), (20, "Напитки"))),
    )
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=10,
                ),
                MicromarketPlanogramLine(
                    product_code="2312",
                    target_qty=1,
                    price_rub=Decimal("20"),
                    active=True,
                    sort_order=1,
                    kit_group_id=99,
                ),
            ),
            shelves=(
                MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),
                MicromarketPlanogramShelf(kit_group_id=20, sort_order=1),
            ),
            updated_at=_FROZEN_NOW,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    html = response.text
    assert 'name="shelf_kit_group_id-0" value="10"' in html
    assert 'name="shelf_kit_group_id-1" value="20"' in html
    assert "Без полки" in html
    assert 'data-ungrouped="true"' in html
    assert html.count("planogram-enroll-row") == 2
    assert ">Группа<" not in html


def test_planogram_post_persists_shelves_and_lines() -> None:
    # happy: POST с двумя полками и enroll → shelves + alphabet order
    app, deps = _build_app_with_micromarket_planogram()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram",
        data={
            "shelf_kit_group_id-0": "10",
            "shelf_kit_group_id-1": "20",
            "product_code-0": "2311",
            "target_qty-0": "1",
            "price_rub-0": "10",
            "active-0": "on",
            "kit_group_id-0": "10",
            "product_code-1": "2312",
            "target_qty-1": "2",
            "price_rub-1": "20",
            "active-1": "on",
            "kit_group_id-1": "10",
            "product_code-2": "",
            "domain_product_id-2": "",
            "target_qty-2": "0",
            "price_rub-2": "0",
            "kit_group_id-2": "20",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    assert deps.micromarket_planogram_store is not None
    doc = deps.micromarket_planogram_store.get("701")
    assert doc is not None
    assert doc.shelves == (MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),)
    # catalog: 2312=Вода, 2311=Салат — alphabet on shelf 10
    assert [line.product_code for line in doc.lines] == ["2312", "2311"]
    assert [line.kit_group_id for line in doc.lines] == [10, 10]
    assert [line.sort_order for line in doc.lines] == [0, 1]


def test_planogram_save_new_category_appends_shelf() -> None:
    # happy: категория строки без поля полки сохраняется, пустая полка не пишется
    app, deps = _build_app_with_micromarket_planogram()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram",
        data={
            "shelf_kit_group_id-0": "10",
            "product_code-0": "2311",
            "target_qty-0": "1",
            "price_rub-0": "10",
            "active-0": "on",
            "kit_group_id-0": "99",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    assert deps.micromarket_planogram_store is not None
    doc = deps.micromarket_planogram_store.get("701")
    assert doc is not None
    assert doc.shelves == (MicromarketPlanogramShelf(kit_group_id=99, sort_order=0),)
    assert doc.lines[0].kit_group_id == 99
    assert doc.lines[0].product_code == "2311"


def test_planogram_save_persists_moved_kit_group_id() -> None:
    # happy: move updates shelf; edge: last item leaves source shelf empty-ok
    app, deps = _build_app_with_micromarket_planogram()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("", ((10, "Салаты"), (20, "Напитки"))),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram",
        data={
            "shelf_kit_group_id-0": "10",
            "shelf_kit_group_id-1": "20",
            "product_code-0": "2311",
            "target_qty-0": "1",
            "price_rub-0": "10",
            "active-0": "on",
            "kit_group_id-0": "20",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    assert deps.micromarket_planogram_store is not None
    doc = deps.micromarket_planogram_store.get("701")
    assert doc is not None
    assert doc.lines[0].kit_group_id == 20
    assert doc.lines[0].product_code == "2311"


def test_planogram_save_duplicate_shelf_is_422() -> None:
    # error: две полки с одним id → 422
    app, _deps = _build_app_with_micromarket_planogram()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram",
        data={
            "shelf_kit_group_id-0": "10",
            "shelf_kit_group_id-1": "10",
            "product_code-0": "2311",
            "target_qty-0": "1",
            "price_rub-0": "10",
            "active-0": "on",
            "kit_group_id-0": "10",
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 422
    assert "Две полки с одной группой Kit" in response.text


def test_planogram_save_error_rerenders_submitted_shelves() -> None:
    # edge: после отказа пустая присланная полка на страницу не возвращается
    app, deps = _build_app_with_micromarket_planogram()
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=10,
                ),
            ),
            shelves=(MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),),
            updated_at=_FROZEN_NOW,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram",
        data={
            "shelf_kit_group_id-0": "10",
            "shelf_kit_group_id-1": "30",
            "product_code-0": "2311",
            "target_qty-0": "1",
            "price_rub-0": "10",
            "active-0": "on",
            "kit_group_id-0": "",
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 400
    assert 'value="30"' not in response.text


def test_planogram_page_groups_fail_disables_add_shelf_keeps_label() -> None:
    # edge: groups fail → add disabled; подпись Полка Kit #{id}; POST лежащих полок ok
    app, deps = _build_app_with_micromarket_planogram()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("Группы Kit Shop не загрузились", ()),
    )
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=5,
                    price_rub=Decimal("189.00"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                ),
            ),
            shelves=(MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),),
            updated_at=_FROZEN_NOW,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert "Группы Kit Shop не загрузились" in response.text
    assert "Полка Kit #6348" in response.text
    assert "add_shelf_kit_group_id" not in response.text
    assert "planogram-move-shelf" not in response.text
    assert 'name="kit_group_id-0"' in response.text
    assert 'value="6348"' in response.text
    save = client.post(
        "/admin/machines/701/micromarket-planogram",
        data={
            "shelf_kit_group_id-0": "6348",
            "product_code-0": "2311",
            "target_qty-0": "5",
            "price_rub-0": "189.00",
            "active-0": "on",
            "kit_group_id-0": "6348",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert save.status_code in {302, 303}


def test_planogram_category_select_lists_group_not_on_page() -> None:
    app, deps = _build_app_with_micromarket_planogram()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("", ((10, "1. Напитки"), (77, "7. Закуски"))),
    )
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=10,
                ),
            ),
            shelves=(MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),),
            updated_at=_FROZEN_NOW,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert "7. Закуски" in response.text
    assert 'value="77"' in response.text
    assert "add_shelf_kit_group_id" not in response.text
    editor_sources = [
        Path("src/interfaces/admin/routes/micromarket_planogram.py"),
        *sorted(Path("src/interfaces/admin/routes").glob("micromarket_planogram_*.py")),
    ]
    assert len(editor_sources) >= 2
    for editor_source in editor_sources:
        assert "GetProductBaseTemplate" not in editor_source.read_text(encoding="utf-8")


def test_planogram_zero_shelves_shows_one_enroll_row() -> None:
    app, deps = _build_app_with_micromarket_planogram()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("", ((10, "1. Напитки"),)),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    html = response.text
    start = html.index('id="micromarket-planogram-shelves"')
    end = html.index('class="admin-save-bar"', start)
    block = html[start:end]
    assert block.count("planogram-enroll-row") == 1
    assert 'name="shelf_kit_group_id-' not in block
    assert "1. Напитки" in block


def test_parse_planogram_form_reads_shelf_kit_group_ids() -> None:
    # happy: полки по индексу и строки с kit_group_id полок; enroll не в lines
    parsed = {
        "shelf_kit_group_id-0": ["10"],
        "shelf_kit_group_id-1": ["20"],
        "product_code-0": ["2311"],
        "target_qty-0": ["1"],
        "price_rub-0": ["10"],
        "active-0": ["on"],
        "kit_group_id-0": ["10"],
        "product_code-1": ["2312"],
        "target_qty-1": ["2"],
        "price_rub-1": ["20"],
        "active-1": ["on"],
        "kit_group_id-1": ["20"],
        "product_code-2": [""],
        "domain_product_id-2": [""],
        "target_qty-2": ["0"],
        "price_rub-2": ["0"],
        "kit_group_id-2": ["20"],
    }
    shelves, lines = _parse_planogram_form(parsed)
    assert shelves == (
        MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),
        MicromarketPlanogramShelf(kit_group_id=20, sort_order=1),
    )
    assert [line.product_code for line in lines] == ["2311", "2312"]
    assert [line.kit_group_id for line in lines] == [10, 20]


def test_parse_planogram_form_skips_enroll_keeps_empty_shelf() -> None:
    # edge: пустая полка остаётся; enroll без товара не в lines
    parsed = {
        "shelf_kit_group_id-0": ["10"],
        "shelf_kit_group_id-1": ["30"],
        "product_code-0": ["2311"],
        "target_qty-0": ["1"],
        "price_rub-0": ["10"],
        "active-0": ["on"],
        "kit_group_id-0": ["10"],
        "product_code-1": [""],
        "domain_product_id-1": [""],
        "target_qty-1": ["0"],
        "price_rub-1": ["0"],
        "kit_group_id-1": ["30"],
    }
    shelves, lines = _parse_planogram_form(parsed)
    assert shelves == (
        MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),
        MicromarketPlanogramShelf(kit_group_id=30, sort_order=1),
    )
    assert len(lines) == 1
    assert lines[0].product_code == "2311"
    assert lines[0].kit_group_id == 10


def test_micromarket_planogram_page_marks_pending_exit_row() -> None:
    app, deps = _build_app_with_micromarket_planogram()
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                    pending_exit=True,
                ),
            ),
            updated_at=_FROZEN_NOW,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    html = response.text
    assert 'name="pending_exit-0"' in html
    assert 'type="hidden"' in html
    assert 'value="1"' in html
    assert "planogram-pending-exit" in html
    assert ">Active<" not in html
    assert ">Выбытие<" not in html
    css = Path("src/interfaces/admin/static/planogram.css").read_text(encoding="utf-8")
    assert ".planogram-pending-exit" in css


def test_micromarket_planogram_page_hides_active_exit_and_marks_persisted() -> None:
    # edge: нет колонок Active/Выбытие; data-persisted на Mongo; enroll без маркера
    app, deps = _build_app_with_micromarket_planogram()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("", ((6348, "Основная"),)),
    )
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                ),
            ),
            shelves=(MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),),
            updated_at=_FROZEN_NOW,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    html = response.text
    assert ">Active<" not in html
    assert ">Выбытие<" not in html
    assert 'name="active-' not in html
    assert "planogram-col-active" not in html
    assert "planogram-col-exit" not in html
    assert 'data-persisted="1"' in html
    assert 'class="planogram-enroll-row"' in html
    enroll_match = re.search(
        r'<tr class="planogram-enroll-row"[^>]*>',
        html,
    )
    assert enroll_match is not None
    assert "data-persisted" not in enroll_match.group(0)


def test_micromarket_planogram_table_js_reindexes_pending_exit() -> None:
    table_js = _TABLE_JS_PATH.read_text(encoding="utf-8")
    assert "pending_exit" in table_js
    assert "reindexRowNames" in table_js
    assert "function createShelfSection" in table_js
    assert "clearEmptyShelf" in table_js


def test_micromarket_planogram_soft_remove_and_restore_markers() -> None:
    # happy: soft-remove/restore на корне холодильника; group reorder; enroll last
    table_js = _TABLE_JS_PATH.read_text(encoding="utf-8")
    picker_js = Path("src/interfaces/admin/static/planogram_product_picker.js").read_text(
        encoding="utf-8"
    )
    assert "data-persisted" in table_js or "data-persisted" in picker_js
    assert "planogram-product-restore" in table_js or "planogram-product-restore" in picker_js
    assert "softRemovePersistedRow" in table_js
    assert "restore" in table_js.lower()
    assert "planogram-pending-exit" in table_js
    assert "insertRowBySortKey" in table_js
    assert "planogram-enroll-row" in table_js
    # edge: non-persisted path остаётся clearSelection без серого
    assert "clearSelection" in picker_js
    assert "micromarket-planogram-shelves" in picker_js
    css = Path("src/interfaces/admin/static/planogram.css").read_text(encoding="utf-8")
    assert ".planogram-pending-exit" in css
    assert ".planogram-product-restore" in css


def test_micromarket_planogram_page_has_shelf_drag_handle_not_on_product_row() -> None:
    # happy: ручка/collapse/снятие у полки; у строки товара и «Без полки» — нет
    app, deps = _build_app_with_micromarket_planogram()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("", ((10, "Салаты"), (20, "Напитки"))),
    )
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=10,
                ),
                MicromarketPlanogramLine(
                    product_code="2312",
                    target_qty=1,
                    price_rub=Decimal("20"),
                    active=True,
                    sort_order=1,
                    kit_group_id=99,
                ),
            ),
            shelves=(
                MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),
                MicromarketPlanogramShelf(kit_group_id=20, sort_order=1),
            ),
            updated_at=_FROZEN_NOW,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    html = response.text

    shelves_start = html.index('id="micromarket-planogram-shelves"')
    ungrouped_start = html.index('data-ungrouped="true"', shelves_start)
    shelves_html = html[shelves_start:ungrouped_start]
    ungrouped_html = html[ungrouped_start:]

    assert 'class="planogram-drag-handle"' in shelves_html
    assert "planogram-shelf-collapse" in shelves_html
    assert "planogram-shelf-clear" in shelves_html
    for tbody in shelves_html.split("<tbody>")[1:]:
        body = tbody.split("</tbody>", 1)[0]
        assert "planogram-drag-handle" not in body
    assert "planogram-drag-handle" not in ungrouped_html
    assert "planogram-shelf-clear" not in ungrouped_html
    assert "planogram-enroll-row" not in ungrouped_html
    assert "planogram-shelf-collapse" not in ungrouped_html


def test_micromarket_planogram_copy_overwrites_target() -> None:
    # happy: POST copy replaces target lines from source; no auto-publish
    app, deps = _build_app(machine_id="702")
    assert deps.master_stores is not None
    deps.master_stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId("701"),
            kind=MachineKind.MICRO_MARKET,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=5,
                    price_rub=Decimal("189"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                ),
            ),
            shelves=(MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),),
            updated_at=_FROZEN_NOW,
            shop_list_status=ShopListPublishStatus.PUBLISHED,
            shop_list_publication_id="src-pub",
        )
    )
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="702",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2312",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=100,
                ),
            ),
            shelves=(MicromarketPlanogramShelf(kit_group_id=100, sort_order=0),),
            updated_at=_FROZEN_NOW,
            shop_list_status=ShopListPublishStatus.PUBLISHED,
            shop_list_publication_id="dest-pub",
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/702/micromarket-planogram/copy",
        data={"source_machine_id": "701"},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}
    dest = deps.micromarket_planogram_store.get("702")
    assert dest is not None
    assert dest.lines[0].product_code == "2311"
    assert dest.shop_list_status is ShopListPublishStatus.UNPUBLISHED
    assert dest.shop_list_publication_id == ""


def test_micromarket_planogram_copy_same_machine_rejected() -> None:
    # edge: source == target rejected
    app, deps = _build_app_with_micromarket_planogram()
    assert deps.micromarket_planogram_store is not None
    _seed_line(deps, product_code="2311")
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram/copy",
        data={"source_machine_id": "701"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 400
    assert "copy_same_machine" in response.text


def test_micromarket_planogram_copy_empty_source_rejected() -> None:
    # error: missing source → error response
    app, _deps = _build_app_with_micromarket_planogram()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram/copy",
        data={"source_machine_id": ""},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 400
    assert "empty_copy_source" in response.text


def test_micromarket_planogram_copy_403_without_origin() -> None:
    # error: missing Origin mirrors snack layout copy gate
    app, deps = _build_app_with_micromarket_planogram()
    assert deps.micromarket_planogram_store is not None
    _seed_line(deps, product_code="2311")
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram/copy",
        data={"source_machine_id": "702"},
    )
    assert response.status_code == 403


def test_micromarket_planogram_copy_403_without_panel() -> None:
    # error: без сессии / панели — не copy (303 login).
    # ROSTER+VISIT_BOARD+MASTER_DATA теперь → coordinator (+ micromarket_planograms).
    app, deps = panel_gates._build_app(
        panels=None,
        micromarket_stock_store=InMemoryMicromarketDeviceStockStore(),
    )
    assert deps.master_stores is not None
    deps.master_stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId("702"),
            kind=MachineKind.MICRO_MARKET,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    client = TestClient(app)
    response = client.post(
        "/admin/machines/701/micromarket-planogram/copy",
        data={"source_machine_id": "702"},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _prepare_publishable(client: TestClient, product: DomainProduct) -> None:
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    client.post(
        "/admin/machines/701/micromarket-planogram",
        data={
            "shelf_kit_group_id-0": "6348",
            "domain_product_id-0": product.domain_product_id,
            "product_code-0": "",
            "target_qty-0": "5",
            "price_rub-0": "189.00",
            "kit_group_id-0": "6348",
            "active-0": "on",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )


def test_fetch_publish_returns_json_ok_without_tasks_redirect() -> None:
    # happy: fetch publish → 200 JSON ok, no Location tab=tasks
    store, product = _publishable_domain_product()
    app, deps = _build_app(domain_product_store=store)

    class _Publisher:
        def publish(self, event: object) -> None:
            del event

    object.__setattr__(deps, "micromarket_shop_list_publisher", _Publisher())
    client = TestClient(app)
    _prepare_publishable(client, product)
    response = client.post(
        "/admin/machines/701/micromarket-planogram/publish",
        headers={
            "Origin": "http://testserver",
            "Accept": "application/json",
        },
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert response.headers.get("location") is None
    assert "tab=tasks" not in (response.headers.get("location") or "")
    payload = response.json()
    assert payload["ok"] is True
    assert deps.shop_list_publish_journal is not None
    rows = deps.shop_list_publish_journal.list_newest()
    assert len(rows) == 1
    assert rows[0].status is ShopListPublishJournalStatus.RUNNING


def test_publish_button_disabled_when_shop_list_publishing() -> None:
    # happy: publishing → button disabled + подпись
    app, deps = _build_app_with_micromarket_planogram()
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=5,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                ),
            ),
            shelves=(MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),),
            updated_at=_FROZEN_NOW,
            shop_list_status=ShopListPublishStatus.PUBLISHING,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert "disabled" in response.text
    assert "Задача выполняется" in response.text
    assert 'id="micromarket-planogram-publish-form"' in response.text


def test_non_fetch_publish_stays_on_planogram_without_tasks_redirect() -> None:
    # edge/error path: non-JSON client still no machine tasks redirect
    store, product = _publishable_domain_product()
    app, deps = _build_app(domain_product_store=store)

    class _Publisher:
        def publish(self, event: object) -> None:
            del event

    object.__setattr__(deps, "micromarket_shop_list_publisher", _Publisher())
    client = TestClient(app)
    _prepare_publishable(client, product)
    response = client.post(
        "/admin/machines/701/micromarket-planogram/publish",
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert response.headers.get("location") is None
    assert "Задача выполняется" in response.text
    assert "disabled" in response.text
    assert 'aria-selected="true">Планограмма</button>' in response.text
    assert 'aria-selected="true">Задачи аппарата</button>' not in response.text


def test_fetch_already_publishing_returns_json_error_journal_unchanged() -> None:
    # edge: AlreadyPublishing message, journal unchanged
    store, product = _publishable_domain_product()
    app, deps = _build_app(domain_product_store=store)

    class _Publisher:
        def publish(self, event: object) -> None:
            del event

    object.__setattr__(deps, "micromarket_shop_list_publisher", _Publisher())
    client = TestClient(app)
    _prepare_publishable(client, product)
    first = client.post(
        "/admin/machines/701/micromarket-planogram/publish",
        headers={"Origin": "http://testserver", "Accept": "application/json"},
        follow_redirects=False,
    )
    assert first.status_code == 200
    assert first.json()["ok"] is True
    assert deps.shop_list_publish_journal is not None
    before = len(deps.shop_list_publish_journal.list_newest())
    second = client.post(
        "/admin/machines/701/micromarket-planogram/publish",
        headers={"Origin": "http://testserver", "Accept": "application/json"},
        follow_redirects=False,
    )
    assert second.status_code == 200
    payload = second.json()
    assert payload["ok"] is False
    assert "Публикация уже идёт" in payload["error"]
    assert len(deps.shop_list_publish_journal.list_newest()) == before


def test_fetch_publish_validation_returns_json_error() -> None:
    # error: validation 422 message
    store, product = _publishable_domain_product()
    app, deps = _build_app(domain_product_store=store)

    class _Publisher:
        def publish(self, event: object) -> None:
            del event

    object.__setattr__(deps, "micromarket_shop_list_publisher", _Publisher())
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=None,
                    domain_product_id=product.domain_product_id,
                ),
            ),
            updated_at=datetime(2026, 9, 25, tzinfo=UTC),
        ),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/machines/701/micromarket-planogram/publish",
        headers={"Origin": "http://testserver", "Accept": "application/json"},
        follow_redirects=False,
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["ok"] is False
    assert "error" in payload
    assert deps.shop_list_publish_journal is not None
    assert deps.shop_list_publish_journal.list_newest() == ()


def test_list_tasks_tab_renders_journal_rows_with_display_name() -> None:
    # happy: list ?tab=tasks → journal rows with display_name + code
    app, deps = _build_app()
    assert deps.shop_list_publish_journal is not None
    assert deps.master_stores is not None
    deps.master_stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId("702"),
            kind=MachineKind.MICRO_MARKET,
            status=MachineStatus.ACTIVE_ON_SITE,
            label="Холодильник Б",
        )
    )
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    deps.shop_list_publish_journal.append(
        ShopListPublishJournalEntry(
            publication_id="pub-701",
            machine_code="701",
            status=ShopListPublishJournalStatus.RUNNING,
            created_at=now,
            updated_at=now,
        )
    )
    deps.shop_list_publish_journal.append(
        ShopListPublishJournalEntry(
            publication_id="pub-702",
            machine_code="702",
            status=ShopListPublishJournalStatus.FAILED,
            created_at=now,
            updated_at=now,
            error_message="timeout",
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms?tab=tasks")
    assert response.status_code == 200
    assert 'data-tab="tasks"' in response.text
    assert "Задачи" in response.text
    assert "Аппараты" in response.text
    assert "admin-roster" in response.text
    assert "data-shop-list-publish-tasks" in response.text
    assert "Источник" in response.text
    assert "Итог" in response.text
    assert "публикация" in response.text
    assert "—" in response.text
    assert "701" in response.text
    assert "702" in response.text
    assert "[склад] 701" in response.text
    assert "[склад] Холодильник Б" in response.text
    assert "в процессе" in response.text
    assert "ошибка" in response.text
    assert "timeout" in response.text
    assert "tasks-poll-autostart" in response.text
    assert "7000" in response.text
    assert "reload()" in response.text
    assert 'class="admin-save-bar" hidden' in response.text
    # «Создать заказ» только на вкладке machines (save-bar body), не на tasks.
    assert "Создать заказ" not in response.text
    assert "Скачать Excel" not in response.text


def test_list_without_tab_shows_machines_not_tasks_poll() -> None:
    # edge: без tab — список аппаратов; poll только на tasks
    app, _deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms")
    assert response.status_code == 200
    assert "Аппараты" in response.text
    assert "Задачи" in response.text
    assert "Заказы" in response.text
    assert "micromarket-planograms-table" in response.text
    assert "Создать заказ" in response.text
    assert "Скачать Excel" not in response.text
    assert "tasks-poll-autostart" not in response.text
    assert 'aria-selected="true">Аппараты' in response.text or (
        'data-tab="machines"' in response.text and 'aria-selected="true"' in response.text
    )


def test_list_tasks_display_name_falls_back_to_machine_code() -> None:
    # edge: нет аппарата в master data → код
    app, deps = _build_app()
    assert deps.shop_list_publish_journal is not None
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    deps.shop_list_publish_journal.append(
        ShopListPublishJournalEntry(
            publication_id="pub-ghost",
            machine_code="ghost-99",
            status=ShopListPublishJournalStatus.SUCCEEDED,
            created_at=now,
            updated_at=now,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms?tab=tasks")
    assert response.status_code == 200
    assert "ghost-99" in response.text
    assert "успешно" in response.text


def test_machine_workspace_tasks_tab_filters_journal_by_machine() -> None:
    # happy: ?tab=tasks — только строки этого machine_code, без колонки «Аппарат»
    app, deps = _build_app()
    assert deps.shop_list_publish_journal is not None
    assert deps.master_stores is not None
    deps.master_stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId("702"),
            kind=MachineKind.MICRO_MARKET,
            status=MachineStatus.ACTIVE_ON_SITE,
            label="Холодильник Б",
        )
    )
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    deps.shop_list_publish_journal.append(
        ShopListPublishJournalEntry(
            publication_id="pub-701",
            machine_code="701",
            status=ShopListPublishJournalStatus.SUCCEEDED,
            created_at=now,
            updated_at=now,
            trigger=ShopListPublishTrigger.MANUAL,
            effects=ShopListPublishEffects(disabled_product_codes=("sku-701",)),
        )
    )
    deps.shop_list_publish_journal.append(
        ShopListPublishJournalEntry(
            publication_id="pub-702",
            machine_code="702",
            status=ShopListPublishJournalStatus.FAILED,
            created_at=now,
            updated_at=now,
            error_message="other-machine",
            effects=ShopListPublishEffects(disabled_product_codes=("sku-702",)),
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701?tab=tasks")
    assert response.status_code == 200
    text = response.text
    assert ">Задачи аппарата</button>" in text
    assert 'data-tab="tasks"' in text
    assert "data-shop-list-publish-tasks" in text
    assert "sku-701" in text
    assert "sku-702" not in text
    assert "other-machine" not in text
    assert ">Аппарат</th>" not in text
    assert "Опубликовать" in text
    assert "снято: sku-701" in text
    assert "tasks-poll-autostart" not in text


def test_machine_workspace_tasks_tab_empty_journal() -> None:
    # edge: пустой journal на вкладке задач аппарата
    app, _deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701?tab=tasks")
    assert response.status_code == 200
    text = response.text
    assert ">Задачи аппарата</button>" in text
    assert "data-shop-list-publish-tasks" in text
    assert "Пока нет задач" in text
    assert ">Аппарат</th>" not in text


def _open_loading_cycle_store(
    *,
    machine_code: str = "701",
    order_id: str = "order-ui-1",
    rolled_back: bool = False,
) -> object:
    from src.domain.micromarket_loading.order import DraftLine, MicromarketLoadingCycle

    class _MemoryCycleStore:
        def __init__(self) -> None:
            self.cycles: dict[str, MicromarketLoadingCycle] = {}

        def load(self, code: str) -> MicromarketLoadingCycle | None:
            return self.cycles.get(code)

        def save(self, cycle: MicromarketLoadingCycle) -> None:
            self.cycles[cycle.machine_code] = cycle

        def list_cycles(self) -> tuple[MicromarketLoadingCycle, ...]:
            return tuple(self.cycles.values())

    store = _MemoryCycleStore()
    cycle = MicromarketLoadingCycle(machine_code=machine_code)
    at = datetime(2026, 9, 24, 10, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    cycle.open_order(
        order_id=order_id,
        move_id=f"move-{order_id}",
        lines=(
            DraftLine(
                product_code="2311",
                target_qty=4,
                stock_qty=Decimal("1"),
                need_qty=Decimal("3"),
                launch_qty=Decimal("2"),
            ),
        ),
        opened_at=at,
        timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
    )
    cycle.link_visit(f"scheduled:{machine_code}:2026-09-24")
    if rolled_back:
        cycle.roll_back(at=at)
    store.save(cycle)
    return store


def test_list_tasks_tab_shows_loading_row_after_launch() -> None:
    # happy: launch → loading row in park Tasks alongside publish
    store = _open_loading_cycle_store()
    app, deps = _build_app(micromarket_loading_cycle_store=store)  # type: ignore[arg-type]
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    assert deps.shop_list_publish_journal is not None
    deps.shop_list_publish_journal.append(
        ShopListPublishJournalEntry(
            publication_id="pub-701",
            machine_code="701",
            status=ShopListPublishJournalStatus.SUCCEEDED,
            created_at=now,
            updated_at=now,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms?tab=tasks")
    assert response.status_code == 200
    text = response.text
    assert 'data-task-kind="loading"' in text
    assert "Загрузка" in text
    assert "открыта" in text
    assert "Ордер order-ui-1" in text
    assert "публикация" in text
    assert "успешно" in text


def test_list_page_ok_when_journal_created_at_naive_and_loading_aware() -> None:
    # error: Mongo journal often stores naive UTC; loading sort_at is aware — must not 500
    store = _open_loading_cycle_store()
    app, deps = _build_app(micromarket_loading_cycle_store=store)  # type: ignore[arg-type]
    naive_now = datetime(2026, 10, 8, 12, 0)  # no tzinfo — pymongo default
    assert deps.shop_list_publish_journal is not None
    deps.shop_list_publish_journal.append(
        ShopListPublishJournalEntry(
            publication_id="pub-naive",
            machine_code="701",
            status=ShopListPublishJournalStatus.SUCCEEDED,
            created_at=naive_now,
            updated_at=naive_now,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms")
    assert response.status_code == 200
    tasks = client.get("/admin/micromarket-planograms?tab=tasks")
    assert tasks.status_code == 200
    assert 'data-task-kind="loading"' in tasks.text
    assert "публикация" in tasks.text


def test_machine_workspace_tasks_tab_shows_loading_row_and_filters() -> None:
    # happy: machine Tasks shows own loading; other machine omitted
    store = _open_loading_cycle_store(machine_code="701", order_id="order-701")
    other = _open_loading_cycle_store(machine_code="702", order_id="order-702")
    # merge both into one store
    for cycle in other.list_cycles():  # type: ignore[attr-defined]
        store.save(cycle)  # type: ignore[attr-defined]
    app, _deps = _build_app(micromarket_loading_cycle_store=store)  # type: ignore[arg-type]
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701?tab=tasks")
    assert response.status_code == 200
    text = response.text
    assert 'data-task-kind="loading"' in text
    assert "Ордер order-701" in text
    assert "Ордер order-702" not in text
    assert ">Аппарат</th>" not in text


def test_list_tasks_tab_loading_row_after_rollback() -> None:
    # happy: rollback → status откат in park feed
    store = _open_loading_cycle_store(rolled_back=True)
    app, _deps = _build_app(micromarket_loading_cycle_store=store)  # type: ignore[arg-type]
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms?tab=tasks")
    assert response.status_code == 200
    text = response.text
    assert 'data-task-kind="loading"' in text
    assert "откат" in text
    assert "Загрузка" in text


def test_list_tasks_details_show_names_and_updated_field_diff() -> None:
    # happy: details — имя из catalog + пояснение цены для «изменено»
    app, deps = _build_app()
    assert deps.shop_list_publish_journal is not None
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    deps.shop_list_publish_journal.append(
        ShopListPublishJournalEntry(
            publication_id="pub-named-diff",
            machine_code="701",
            status=ShopListPublishJournalStatus.SUCCEEDED,
            created_at=now,
            updated_at=now,
            trigger=ShopListPublishTrigger.MANUAL,
            effects=ShopListPublishEffects(
                disabled_product_codes=("2312",),
                updated_product_codes=("2311",),
            ),
            intended_lines=(
                ShopListIntendedLine(
                    product_code="2311",
                    price_rub=Decimal("45"),
                    kit_group_id=1,
                    availability_off=False,
                ),
            ),
            baseline_lines=(
                ShopListIntendedLine(
                    product_code="2311",
                    price_rub=Decimal("40"),
                    kit_group_id=1,
                    availability_off=False,
                ),
            ),
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms?tab=tasks")
    assert response.status_code == 200
    text = response.text
    assert "снято: Вода 0.5" in text
    assert "изменено: Салат Цезарь — цена 40→45 ₽" in text


def test_machine_workspace_keeps_snapshot_groups_while_publishing() -> None:
    # happy: во время PUBLISHING имена полок из локального снимка, без голодания UI
    app, deps = _build_app_with_micromarket_planogram()
    calls: list[int] = []

    def _local_load_kit_product_groups() -> tuple[str, tuple[tuple[int, str], ...]]:
        calls.append(1)
        return ("", ((6348, "Основная"),))

    object.__setattr__(deps, "load_kit_product_groups", _local_load_kit_product_groups)
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                ),
            ),
            shelves=(MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),),
            updated_at=_FROZEN_NOW,
            shop_list_status=ShopListPublishStatus.PUBLISHING,
            shop_list_publication_id="pub-busy",
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    started = time.monotonic()
    response = client.get("/admin/micromarket-planograms/701")
    elapsed = time.monotonic() - started
    assert response.status_code == 200
    assert elapsed < 1.0
    # Вкладка планограммы читает группы Kit один раз. Имена полок загрузки
    # подгружаются при переходе на tab=assembly, отдельным запросом.
    assert calls == [1]
    assert "Задача выполняется" in response.text
    assert "Основная" in response.text
    assembly = client.get("/admin/micromarket-planograms/701?tab=assembly")
    assert assembly.status_code == 200
    assert calls == [1, 1, 1]
    assert "Основная" in assembly.text


def test_list_tasks_rows_include_trigger_label_and_effects_summary() -> None:
    # happy: list rows содержат trigger_label и effects_summary
    app, deps = _build_app()
    assert deps.shop_list_publish_journal is not None
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    deps.shop_list_publish_journal.append(
        ShopListPublishJournalEntry(
            publication_id="pub-zero",
            machine_code="701",
            status=ShopListPublishJournalStatus.RUNNING,
            created_at=now,
            updated_at=now,
            trigger=ShopListPublishTrigger.INVENTORY_ZERO,
            effects=ShopListPublishEffects(disabled_product_codes=("n-1", "n-2")),
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms?tab=tasks")
    assert response.status_code == 200
    assert "система · нуль" in response.text
    assert "снято 2" in response.text
    assert "<details" in response.text
    assert "снято: n-1" in response.text
    assert "снято: n-2" in response.text


def test_list_tasks_legacy_entry_renders_without_crash() -> None:
    # edge: legacy entry → label публикация, пустая/«—» сводка
    app, deps = _build_app()
    assert deps.shop_list_publish_journal is not None
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    deps.shop_list_publish_journal.append(
        ShopListPublishJournalEntry(
            publication_id="pub-legacy",
            machine_code="701",
            status=ShopListPublishJournalStatus.SUCCEEDED,
            created_at=now,
            updated_at=now,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms?tab=tasks")
    assert response.status_code == 200
    assert "публикация" in response.text
    assert "—" in response.text


def test_list_tasks_tab_shows_trigger_and_effects_summary() -> None:
    # happy: list rows содержат trigger_label и effects_summary
    app, deps = _build_app()
    assert deps.shop_list_publish_journal is not None
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    deps.shop_list_publish_journal.append(
        ShopListPublishJournalEntry(
            publication_id="pub-manual",
            machine_code="701",
            status=ShopListPublishJournalStatus.SUCCEEDED,
            created_at=now,
            updated_at=now,
            trigger=ShopListPublishTrigger.MANUAL,
            effects=ShopListPublishEffects(
                disabled_product_codes=("2311",),
                added_product_codes=("2311", "2312"),
                updated_product_codes=("2313",),
            ),
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms?tab=tasks")
    assert response.status_code == 200
    assert "Опубликовать" in response.text
    assert "снято 1" in response.text
    assert "+2" in response.text
    assert "~1" in response.text


def test_list_tasks_details_show_product_codes_from_effects() -> None:
    # happy: details раскрывают коды SKU из effects; summary остаётся компактным
    app, deps = _build_app()
    assert deps.shop_list_publish_journal is not None
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    deps.shop_list_publish_journal.append(
        ShopListPublishJournalEntry(
            publication_id="pub-detail",
            machine_code="701",
            status=ShopListPublishJournalStatus.SUCCEEDED,
            created_at=now,
            updated_at=now,
            trigger=ShopListPublishTrigger.MANUAL,
            effects=ShopListPublishEffects(
                disabled_product_codes=("sku-off",),
                enabled_product_codes=("sku-on",),
                added_product_codes=("sku-new",),
                removed_product_codes=("sku-gone",),
            ),
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms?tab=tasks")
    assert response.status_code == 200
    assert "снято 1" in response.text
    assert "<details" in response.text
    assert "снято: sku-off" in response.text
    assert "возвращено: sku-on" in response.text
    assert "добавлено: sku-new" in response.text
    assert "убрано: sku-gone" in response.text


def test_list_tasks_empty_effects_details_show_placeholder() -> None:
    # edge: пустые effects → placeholder в details, summary «—»
    app, deps = _build_app()
    assert deps.shop_list_publish_journal is not None
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    deps.shop_list_publish_journal.append(
        ShopListPublishJournalEntry(
            publication_id="pub-empty-effects",
            machine_code="701",
            status=ShopListPublishJournalStatus.SUCCEEDED,
            created_at=now,
            updated_at=now,
            trigger=ShopListPublishTrigger.MANUAL,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms?tab=tasks")
    assert response.status_code == 200
    assert "<details" in response.text
    assert "Нет изменений SKU" in response.text
    assert "—" in response.text


def test_list_tasks_tab_legacy_entry_uses_publication_label() -> None:
    # edge: legacy entry → label публикация, пустая/«—» сводка
    app, deps = _build_app()
    assert deps.shop_list_publish_journal is not None
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    deps.shop_list_publish_journal.append(
        ShopListPublishJournalEntry(
            publication_id="pub-legacy",
            machine_code="701",
            status=ShopListPublishJournalStatus.RUNNING,
            created_at=now,
            updated_at=now,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms?tab=tasks")
    assert response.status_code == 200
    assert "публикация" in response.text
    assert "—" in response.text


def test_list_tasks_tab_without_panel_is_forbidden() -> None:
    # error: без сессии → redirect login (ROSTER+…MASTER_DATA теперь даёт planograms)
    app, _deps = panel_gates._build_app(
        panels=None,
        micromarket_stock_store=InMemoryMicromarketDeviceStockStore(),
    )
    client = TestClient(app)
    response = client.get(
        "/admin/micromarket-planograms?tab=tasks",
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_planogram_target_qty_uses_admin_quantity_stepper() -> None:
    # happy: Target обёрнут степпером; script подключён; POST name as-is
    app, deps = _build_app_with_micromarket_planogram()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("", ((6348, "Основная"),)),
    )
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=5,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                ),
            ),
            shelves=(MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),),
            updated_at=_FROZEN_NOW,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    html = response.text
    assert "admin_quantity_stepper.js" in html
    assert "admin-qty-stepper" in html
    assert 'name="target_qty-0"' in html
    target_idx = html.index('name="target_qty-0"')
    window = html[max(0, target_idx - 500) : target_idx + 450]
    assert "admin-qty-stepper" in window
    assert 'data-dir="-1"' in window
    assert 'data-dir="1"' in window
    assert "admin-qty-btn" in window


def test_planogram_price_rub_has_no_quantity_stepper_wrapper() -> None:
    # edge: цена без обёртки степпера
    app, deps = _build_app_with_micromarket_planogram()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("", ((6348, "Основная"),)),
    )
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("189"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                ),
            ),
            shelves=(MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),),
            updated_at=_FROZEN_NOW,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    html = response.text
    price_idx = html.index('name="price_rub-0"')
    window = html[max(0, price_idx - 250) : price_idx + 220]
    assert "admin-qty-stepper" not in window
    assert 'aria-label="Установленная цена"' in window
    assert 'value="189"' in window


def test_planogram_table_js_resyncs_qty_stepper_after_enroll_clone() -> None:
    # edge: enroll clone/reindex совместим со степпером Target
    table_js = _TABLE_JS_PATH.read_text(encoding="utf-8")
    assert "cloneEmptyRow" in table_js
    assert "AdminQuantityStepper" in table_js
    assert "syncQtySteppers" in table_js
    assert 'input[name^="target_qty-"]' in table_js


def test_planogram_workspace_title_uses_display_name() -> None:
    # happy: page title / h1 = display_name, not bare machine code
    app, _deps = _build_app_with_micromarket_planogram()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert "<title>[склад] 701</title>" in response.text
    assert "<h1>[склад] 701</h1>" in response.text
    assert "<title>701</title>" not in response.text
    planogram_panel = response.text.split('data-tab="planogram"', 1)[1].split(
        'data-tab="loading"', 1
    )[0]
    assert 'class="admin-muted"' not in planogram_panel
    assert "Список Kit:" not in planogram_panel


def test_planogram_columns_chrome_labels() -> None:
    # happy: Товар | Вместимость | Остатки | Цена; no Target / Цена ₽ / actions col
    app, deps = _build_app_with_micromarket_planogram()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("", ((10, "Салаты"),)),
    )
    _seed_line(deps, product_code="2311", kit_group_id=10)
    assert deps.micromarket_planogram_store is not None
    doc = deps.micromarket_planogram_store.get("701")
    assert doc is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=doc.lines,
            shelves=(MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),),
            updated_at=_FROZEN_NOW,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert ">Вместимость<" in response.text
    assert ">Остатки<" in response.text
    assert ">Цена<" in response.text
    assert ">Target<" not in response.text
    assert ">Цена ₽<" not in response.text
    assert "planogram-col-actions" not in response.text
    assert "Список Kit:" not in response.text


def test_admin_css_centers_table_headers() -> None:
    # edge: ADR-0045 — admin.css centers th
    css = Path("src/interfaces/admin/static/admin.css").read_text(encoding="utf-8")
    assert re.search(
        r"table\.admin-roster th\b[^}]*text-align:\s*center",
        css,
        re.DOTALL,
    )


def test_planogram_stock_column_shows_qty() -> None:
    # happy: row with device stock shows qty in Остатки
    app, deps = _build_app_with_micromarket_planogram()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("", ((10, "Салаты"),)),
    )
    _seed_line(deps, product_code="2311", kit_group_id=10)
    assert deps.micromarket_planogram_store is not None
    doc = deps.micromarket_planogram_store.get("701")
    assert doc is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=doc.lines,
            shelves=(MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),),
            updated_at=_FROZEN_NOW,
        )
    )
    assert deps.micromarket_stock_store is not None
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=_FROZEN_NOW,
        quantities={"2311": Decimal("7")},
        inventory_id="inv-planogram-stock-1",
    )
    deps.micromarket_stock_store.save(stock)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert 'class="planogram-stock-qty"' in response.text
    assert ">7<" in response.text


def test_planogram_stock_dash_without_code_or_stock_doc() -> None:
    # edge: enroll / missing stock document → —
    app, deps = _build_app_with_micromarket_planogram()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("", ((10, "Салаты"),)),
    )
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(),
            shelves=(MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),),
            updated_at=_FROZEN_NOW,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert 'class="planogram-stock-qty"' in response.text
    assert ">—<" in response.text or ">—</" in response.text


def test_planogram_move_button_beside_clear() -> None:
    # happy: ↓ move control next to clear; no visible Перенести… column label
    app, deps = _build_app_with_micromarket_planogram()
    object.__setattr__(
        deps,
        "load_kit_product_groups",
        lambda: ("", ((10, "Салаты"), (20, "Напитки"))),
    )
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=10,
                ),
            ),
            shelves=(
                MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),
                MicromarketPlanogramShelf(kit_group_id=20, sort_order=1),
            ),
            updated_at=_FROZEN_NOW,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert "planogram-product-move" in response.text
    assert ">↓<" in response.text
    assert "planogram-move-shelf" in response.text
    assert ">Перенести…<" in response.text
    assert (
        "Действия" not in response.text
        or "admin-sr-only"
        not in response.text.split("planogram-shelf-table", 1)[1].split("</thead>", 1)[0]
    )
    table_js = _TABLE_JS_PATH.read_text(encoding="utf-8")
    assert "planogram-product-move" in table_js


def test_planogram_publish_published_on_save_bar() -> None:
    # happy: published → disabled «опубликовано»; Publish inside save-bar
    app, deps = _build_app_with_micromarket_planogram()
    _seed_line(deps, product_code="2311", published=True)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    save_bar = response.text.split('class="admin-save-bar"', 1)[1].split(
        "planogram-scroll-spacer", 1
    )[0]
    assert 'id="micromarket-planogram-publish-button"' in save_bar
    assert "опубликовано" in save_bar
    assert re.search(
        r'id="micromarket-planogram-publish-button"[^>]*\bdisabled\b',
        save_bar,
    )
    assert 'id="micromarket-planogram-publish-form"' in response.text
    assert "data-publish-fetch" in response.text
    assert "Список Kit:" not in response.text


def test_planogram_publish_publishing_disables_button() -> None:
    # edge: publishing → disabled + «Задача выполняется»
    app, deps = _build_app_with_micromarket_planogram()
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                ),
            ),
            updated_at=_FROZEN_NOW,
            shop_list_status=ShopListPublishStatus.PUBLISHING,
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert "Задача выполняется" in response.text
    assert re.search(
        r'id="micromarket-planogram-publish-button"[^>]*\bdisabled\b',
        response.text,
    )


def test_planogram_publish_failed_shows_error_and_active_publish() -> None:
    # edge: failed → error text + active Опубликовать
    app, deps = _build_app_with_micromarket_planogram()
    assert deps.micromarket_planogram_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                ),
            ),
            updated_at=_FROZEN_NOW,
            shop_list_status=ShopListPublishStatus.FAILED,
            shop_list_error="kit boom",
        )
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert "kit boom" in response.text
    assert "admin-error" in response.text
    assert "Опубликовать" in response.text
    assert not re.search(
        r'id="micromarket-planogram-publish-button"[^>]*\bdisabled\b',
        response.text,
    )


def _seed_positive_need(deps: AdminHttpDeps) -> None:
    assert deps.micromarket_planogram_store is not None
    assert deps.micromarket_stock_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=5,
                    price_rub=Decimal("189.00"),
                    active=True,
                    sort_order=0,
                ),
            ),
            updated_at=_FROZEN_NOW,
        ),
    )
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=_FROZEN_NOW,
        quantities={"2311": Decimal("2")},
        inventory_id="inv-supply-1",
    )
    deps.micromarket_stock_store.save(stock)


def test_live_need_line_keeps_preview_shelf_and_target() -> None:
    _app, deps = _build_app()
    _seed_positive_need(deps)
    assert deps.master_stores is not None
    machine = deps.master_stores.machines.get(MachineId("701"))
    assert machine is not None
    live = _live_need_machine(deps, machine)
    assert len(live.lines) == 1
    line = live.lines[0]
    assert line.product_code == "2311"
    assert line.shelf_qty == Decimal("2")
    assert line.target_qty == Decimal("5")
    assert line.need_qty == Decimal("3")


def test_list_orders_tab_and_create_returns_xlsx() -> None:
    products = MemoryDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="dp-supply-2311",
            number="2311",
            name="Салат",
            catalog_code="2311",
            hidden=False,
        ),
    )
    app, deps = _build_app(domain_product_store=products)
    _seed_positive_need(deps)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    list_resp = client.get("/admin/micromarket-planograms?tab=orders")
    assert list_resp.status_code == 200
    assert "Заказы" in list_resp.text
    assert "data-micromarket-supply-orders" in list_resp.text

    create = client.post(
        "/admin/micromarket-planograms/orders",
        data={"machine_id": "701", "expected_arrival_at": _FUTURE_ARRIVAL_FORM},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert create.status_code == 303
    assert deps.micromarket_supply_order_store is not None
    orders = deps.micromarket_supply_order_store.list_newest()
    assert len(orders) == 1
    location = create.headers["location"]
    assert "tab=orders" in location
    assert f"download={orders[0].order_id}" in location
    orders_tab = client.get(location)
    assert orders_tab.status_code == 200
    assert orders[0].order_id in orders_tab.text
    assert "Скачать" in orders_tab.text
    assert "Удалить" in orders_tab.text
    assert f"/orders/{orders[0].order_id}/download" in orders_tab.text

    download = client.get(
        f"/admin/micromarket-planograms/orders/{orders[0].order_id}/download",
    )
    assert download.status_code == 200
    assert (
        download.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert len(download.content) > 0


def test_create_supply_order_redirects_to_orders_tab_with_new_row() -> None:
    # happy: create → redirect tab=orders; список сразу содержит новый заказ
    products = MemoryDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="dp-supply-refresh-2311",
            number="2311",
            name="Салат",
            catalog_code="2311",
            hidden=False,
        ),
    )
    app, deps = _build_app(domain_product_store=products)
    _seed_positive_need(deps)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())

    create = client.post(
        "/admin/micromarket-planograms/orders",
        data={"machine_id": "701", "expected_arrival_at": _FUTURE_ARRIVAL_FORM},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert create.status_code == 303
    assert deps.micromarket_supply_order_store is not None
    orders = deps.micromarket_supply_order_store.list_newest()
    assert len(orders) == 1
    order_id = orders[0].order_id
    location = create.headers["location"]
    assert location.startswith("/admin/micromarket-planograms?")
    assert "tab=orders" in location
    assert f"download={order_id}" in location

    landed = client.get(location)
    assert landed.status_code == 200
    assert 'aria-selected="true"' in landed.text
    orders_idx = landed.text.index('data-tab="orders"')
    selected_chunk = landed.text[orders_idx : orders_idx + 80]
    assert 'aria-selected="true"' in selected_chunk
    assert order_id in landed.text
    assert "Пока нет заказов снабжения" not in landed.text
    assert f'href="/admin/micromarket-planograms/orders/{order_id}/download"' in landed.text
    assert "location.assign" in landed.text or "window.location" in landed.text


def test_create_supply_order_from_empty_orders_list_shows_row() -> None:
    # edge: до create список пуст; после redirect — одна строка
    products = MemoryDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="dp-supply-empty-2311",
            number="2311",
            name="Салат",
            catalog_code="2311",
            hidden=False,
        ),
    )
    app, deps = _build_app(domain_product_store=products)
    _seed_positive_need(deps)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    before = client.get("/admin/micromarket-planograms?tab=orders")
    assert before.status_code == 200
    assert "Пока нет заказов снабжения" in before.text
    assert deps.micromarket_supply_order_store is not None
    assert deps.micromarket_supply_order_store.list_newest() == ()

    create = client.post(
        "/admin/micromarket-planograms/orders",
        data={"machine_id": "701", "expected_arrival_at": _FUTURE_ARRIVAL_FORM},
        headers={"Origin": "http://testserver"},
        follow_redirects=True,
    )
    assert create.status_code == 200
    assert "Пока нет заказов снабжения" not in create.text
    orders = deps.micromarket_supply_order_store.list_newest()
    assert len(orders) == 1
    assert orders[0].order_id in create.text


def test_create_supply_order_fail_leaves_orders_list_unchanged() -> None:
    # error: create 400 → вкладка Заказы без новых строк
    app, deps = _build_app(domain_product_store=MemoryDomainProductStore())
    _seed_positive_need(deps)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    before = client.get("/admin/micromarket-planograms?tab=orders")
    assert "Пока нет заказов снабжения" in before.text

    response = client.post(
        "/admin/micromarket-planograms/orders",
        data={"machine_id": "701"},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "Укажите дату и время прибытия в будущем" in response.text
    assert deps.micromarket_supply_order_store is not None
    assert deps.micromarket_supply_order_store.list_newest() == ()
    after = client.get("/admin/micromarket-planograms?tab=orders")
    assert after.status_code == 200
    assert "Пока нет заказов снабжения" in after.text
    assert after.text.count("Скачать") == before.text.count("Скачать")


def test_create_supply_order_past_arrival_returns_400() -> None:
    products = MemoryDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="dp-past-arrival",
            number="2311",
            name="Салат",
            catalog_code="2311",
            hidden=False,
        ),
    )
    app, deps = _build_app(domain_product_store=products)
    _seed_positive_need(deps)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/micromarket-planograms/orders",
        data={"machine_id": "701", "expected_arrival_at": _PAST_ARRIVAL_FORM},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 400
    assert "Укажите дату и время прибытия в будущем" in response.text
    assert deps.micromarket_supply_order_store is not None
    assert deps.micromarket_supply_order_store.list_newest() == ()


def test_create_supply_order_stub_forecast_shows_notice_and_xlsx_meta() -> None:
    # happy+edge: stub unavailable → create ok + notice; xlsx содержит прибытие
    products = MemoryDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="dp-forecast-notice",
            number="2311",
            name="Салат",
            catalog_code="2311",
            hidden=False,
        ),
    )
    app, deps = _build_app(domain_product_store=products)
    _seed_positive_need(deps)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    create = client.post(
        "/admin/micromarket-planograms/orders",
        data={"machine_id": "701", "expected_arrival_at": _FUTURE_ARRIVAL_FORM},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert create.status_code == 303
    location = create.headers["location"]
    assert "notice=" in location
    assert deps.micromarket_supply_order_store is not None
    orders = deps.micromarket_supply_order_store.list_newest()
    assert len(orders) == 1
    assert orders[0].expected_arrival_at is not None
    assert orders[0].machines[0].lines[0].forecast_qty == Decimal("0")

    landed = client.get(location)
    assert landed.status_code == 200
    assert "Прогноз недоступен" in landed.text
    assert "admin-hint" in landed.text

    download = client.get(
        f"/admin/micromarket-planograms/orders/{orders[0].order_id}/download",
    )
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.content)) as zf:
        sheet = zf.read("xl/worksheets/sheet1.xml").decode()
        shared = ""
        if "xl/sharedStrings.xml" in zf.namelist():
            shared = zf.read("xl/sharedStrings.xml").decode()
        blob = sheet + shared
        assert "прибытие" in blob


def test_orders_tab_switch_navigates_for_fresh_list() -> None:
    # happy: переключение на Заказы — navigate (не только replaceState)
    app, _deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms")
    assert response.status_code == 200
    script = response.text
    assert 'data-tab="orders"' in script
    assert "location.assign" in script
    assign_at = script.index("location.assign")
    orders_nav = script[assign_at - 120 : assign_at + 80]
    assert "orders" in orders_nav


def test_create_order_unlinked_returns_400_flash() -> None:
    app, deps = _build_app(domain_product_store=MemoryDomainProductStore())
    _seed_positive_need(deps)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/micromarket-planograms/orders",
        data={"machine_id": "701", "expected_arrival_at": _FUTURE_ARRIVAL_FORM},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 400
    assert "Сначала свяжите товары с карточками МойСклада" in response.text
    assert "2311" in response.text
    assert deps.micromarket_supply_order_store is not None
    assert deps.micromarket_supply_order_store.list_newest() == ()


def test_create_order_linked_domain_product_returns_xlsx() -> None:
    store = MemoryDomainProductStore()
    lookup = FakeCatalogLookup(
        (CatalogProduct(code="2311", name="Салат", archived=False),),
    )
    product = create_domain_product("Салат", store=store, lookup=lookup)
    link_domain_product(product.domain_product_id, "2311", store=store, lookup=lookup)
    app, deps = _build_app(domain_product_store=store)
    assert deps.micromarket_planogram_store is not None
    assert deps.micromarket_stock_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="",
                    target_qty=5,
                    price_rub=Decimal("189.00"),
                    active=True,
                    sort_order=0,
                    domain_product_id=product.domain_product_id,
                ),
            ),
            updated_at=_FROZEN_NOW,
        ),
    )
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=_FROZEN_NOW,
        quantities={product.number: Decimal("2")},
        inventory_id="inv-domain-supply-1",
    )
    deps.micromarket_stock_store.save(stock)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    create = client.post(
        "/admin/micromarket-planograms/orders",
        data={"machine_id": "701", "expected_arrival_at": _FUTURE_ARRIVAL_FORM},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert create.status_code == 303
    assert deps.micromarket_supply_order_store is not None
    orders = deps.micromarket_supply_order_store.list_newest()
    assert len(orders) == 1
    assert orders[0].machines[0].lines[0].product_code == product.number
    assert f"download={orders[0].order_id}" in create.headers["location"]
    download = client.get(
        f"/admin/micromarket-planograms/orders/{orders[0].order_id}/download",
    )
    assert download.status_code == 200
    assert (
        download.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def test_create_order_unlinked_domain_product_lists_items() -> None:
    store = MemoryDomainProductStore()
    lookup = FakeCatalogLookup(())
    product = create_domain_product("Кефир", store=store, lookup=lookup)
    app, deps = _build_app(domain_product_store=store)
    assert deps.micromarket_planogram_store is not None
    assert deps.micromarket_stock_store is not None
    deps.micromarket_planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="",
                    target_qty=5,
                    price_rub=Decimal("50.00"),
                    active=True,
                    sort_order=0,
                    domain_product_id=product.domain_product_id,
                ),
            ),
            updated_at=_FROZEN_NOW,
        ),
    )
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=_FROZEN_NOW,
        quantities={product.number: Decimal("1")},
        inventory_id="inv-domain-unlinked-1",
    )
    deps.micromarket_stock_store.save(stock)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/micromarket-planograms/orders",
        data={"machine_id": "701", "expected_arrival_at": _FUTURE_ARRIVAL_FORM},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 400
    assert "Сначала свяжите товары с карточками МойСклада" in response.text
    assert product.number in response.text
    assert "Кефир" in response.text
    assert deps.micromarket_supply_order_store is not None
    assert deps.micromarket_supply_order_store.list_newest() == ()


def test_create_order_empty_selection_returns_400() -> None:
    app, deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/micromarket-planograms/orders",
        data={},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 400
    assert deps.micromarket_supply_order_store is not None
    assert deps.micromarket_supply_order_store.list_newest() == ()


def test_download_and_delete_unknown_order_404() -> None:
    app, _deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    assert client.get("/admin/micromarket-planograms/orders/missing/download").status_code == 404
    assert (
        client.post(
            "/admin/micromarket-planograms/orders/missing/delete",
            headers={"Origin": "http://testserver"},
        ).status_code
        == 404
    )


def test_delete_supply_order_removes_row() -> None:
    app, deps = _build_app()
    assert deps.micromarket_supply_order_store is not None
    deps.micromarket_supply_order_store.save(
        MicromarketSupplyOrder(
            order_id="so-ui-1",
            created_at=_FROZEN_NOW,
            expected_arrival_at=datetime(2026, 10, 10, 12, 0, tzinfo=UTC),
            machines=(
                MicromarketSupplyOrderMachine(
                    machine_id="701",
                    lines=(
                        MicromarketSupplyOrderLine(
                            product_code="2311",
                            need_qty=Decimal("3"),
                            category=2,
                            name="Салат",
                        ),
                    ),
                ),
            ),
        ),
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/micromarket-planograms/orders/so-ui-1/delete",
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert deps.micromarket_supply_order_store.get("so-ui-1") is None


def test_machines_list_need_total_is_live_not_draft() -> None:
    from src.domain.micromarket_loading.order import DraftLine, MicromarketLoadingCycle

    class _MemoryCycleStore:
        def __init__(self) -> None:
            self.cycles: dict[str, MicromarketLoadingCycle] = {}

        def load(self, machine_code: str) -> MicromarketLoadingCycle | None:
            return self.cycles.get(machine_code)

        def save(self, cycle: MicromarketLoadingCycle) -> None:
            self.cycles[cycle.machine_code] = cycle

    cycle_store = _MemoryCycleStore()
    cycle = MicromarketLoadingCycle(machine_code="701")
    cycle.save_draft(
        (
            DraftLine(
                product_code="2311",
                target_qty=5,
                stock_qty=Decimal("2"),
                need_qty=Decimal("99"),
                launch_qty=Decimal("1"),
            ),
        ),
    )
    cycle_store.save(cycle)
    app, deps = _build_app(micromarket_loading_cycle_store=cycle_store)
    _seed_positive_need(deps)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms")
    assert response.status_code == 200
    # live: target 5 − shelf 2 = 3; draft need 99 must not appear as a cell
    assert re.search(r"<td>\s*3\s*</td>", response.text) is not None
    assert re.search(r"<td>\s*99\s*</td>", response.text) is None


def test_create_order_missing_shelf_life_returns_400_flash() -> None:
    products = MemoryDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="dp-missing-days",
            number="2311",
            name="Салат",
            catalog_code="2311",
            hidden=False,
        ),
    )
    app, deps = _build_app(
        domain_product_store=products,
        supply_order_category_facts=FakeSupplyOrderCategoryFacts(missing_days=True),
    )
    _seed_positive_need(deps)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/micromarket-planograms/orders",
        data={"machine_id": "701", "expected_arrival_at": _FUTURE_ARRIVAL_FORM},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 400
    assert "Срок хранения" in response.text
    assert "2311" in response.text
    assert deps.micromarket_supply_order_store is not None
    assert deps.micromarket_supply_order_store.list_newest() == ()


def test_create_order_ms_unavailable_returns_400_flash() -> None:
    products = MemoryDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="dp-ms-down",
            number="2311",
            name="Салат",
            catalog_code="2311",
            hidden=False,
        ),
    )
    app, deps = _build_app(
        domain_product_store=products,
        supply_order_category_facts=FakeSupplyOrderCategoryFacts(fail=True),
    )
    _seed_positive_need(deps)
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.post(
        "/admin/micromarket-planograms/orders",
        data={"machine_id": "701", "expected_arrival_at": _FUTURE_ARRIVAL_FORM},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 400
    assert "МойСклада" in response.text
    assert deps.micromarket_supply_order_store is not None
    assert deps.micromarket_supply_order_store.list_newest() == ()


def test_planogram_shows_last_buy_between_stock_and_price() -> None:
    # happy: linked product + mirror price rendered as Закуп
    products = MemoryDomainProductStore()
    lookup = FakeCatalogLookup(
        (CatalogProduct(code="2311", name="Салат МС", archived=False),),
    )
    product = create_domain_product("Салат", store=products, lookup=lookup)
    link_domain_product(product.domain_product_id, "2311", store=products, lookup=lookup)
    mirrors = MemoryProcurementMirrorStore()
    mirrors.upsert(
        ProcurementMirror(
            catalog_code="2311",
            supplier_id="a1",
            supplier_name="ООО",
            last_buy_price=Decimal("12.5"),
            supply_moment=_FROZEN_NOW,
            synced_at=_FROZEN_NOW,
        )
    )
    app, deps = _build_app(
        domain_product_store=products,
        procurement_mirror_enabled=True,
        procurement_mirror_store=mirrors,
    )
    _seed_line(deps, domain_product_id=product.domain_product_id, product_code="")
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    html = response.text
    assert ">Закуп<" in html
    assert 'class="planogram-buy-price">12,50<' in html
    assert 'id="planogram-last-buy-prices"' in html
    assert product.domain_product_id in html
    assert "12,50" in html
    stock_idx = html.find('class="planogram-stock-qty"')
    buy_idx = html.find('class="planogram-buy-price"')
    price_idx = html.find('name="price_rub-0"')
    assert 0 <= stock_idx < buy_idx < price_idx


def test_planogram_last_buy_em_dash_when_mirror_off() -> None:
    # edge: mirror disabled → Закуп still present as —
    products = MemoryDomainProductStore()
    lookup = FakeCatalogLookup(
        (CatalogProduct(code="2311", name="Салат МС", archived=False),),
    )
    product = create_domain_product("Салат", store=products, lookup=lookup)
    link_domain_product(product.domain_product_id, "2311", store=products, lookup=lookup)
    app, deps = _build_app(domain_product_store=products, procurement_mirror_enabled=False)
    _seed_line(deps, domain_product_id=product.domain_product_id, product_code="")
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert ">Закуп<" in response.text
    assert 'class="planogram-buy-price">—<' in response.text


def test_planogram_last_buy_from_line_product_code_when_domain_unlinked() -> None:
    # edge: domain product без catalog_code, MS-код на строке планограммы
    products = MemoryDomainProductStore()
    product = create_domain_product("BonaAqua", store=products, lookup=FakeCatalogLookup(()))
    mirrors = MemoryProcurementMirrorStore()
    mirrors.upsert(
        ProcurementMirror(
            catalog_code="16161616003392",
            supplier_id="a1",
            supplier_name="ООО",
            last_buy_price=Decimal("42"),
            supply_moment=_FROZEN_NOW,
            synced_at=_FROZEN_NOW,
        )
    )
    app, deps = _build_app(
        domain_product_store=products,
        procurement_mirror_enabled=True,
        procurement_mirror_store=mirrors,
    )
    _seed_line(
        deps,
        domain_product_id=product.domain_product_id,
        product_code="16161616003392",
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert 'class="planogram-buy-price">42,00<' in response.text


def test_planogram_last_buy_prefers_line_code_when_primary_catalog_misses_mirror() -> None:
    # edge: у домена есть catalog_code без зеркала, живой закуп на product_code строки
    products = MemoryDomainProductStore()
    lookup = FakeCatalogLookup(
        (CatalogProduct(code="stale-ms", name="BonaAqua stale", archived=False),),
    )
    product = create_domain_product("BonaAqua", store=products, lookup=lookup)
    link_domain_product(product.domain_product_id, "stale-ms", store=products, lookup=lookup)
    mirrors = MemoryProcurementMirrorStore()
    mirrors.upsert(
        ProcurementMirror(
            catalog_code="16161616003392",
            supplier_id="a1",
            supplier_name="ООО",
            last_buy_price=Decimal("42"),
            supply_moment=_FROZEN_NOW,
            synced_at=_FROZEN_NOW,
        )
    )
    app, deps = _build_app(
        domain_product_store=products,
        procurement_mirror_enabled=True,
        procurement_mirror_store=mirrors,
    )
    _seed_line(
        deps,
        domain_product_id=product.domain_product_id,
        product_code="16161616003392",
    )
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert 'class="planogram-buy-price">42,00<' in response.text


def test_planogram_last_buy_from_extra_catalog_code() -> None:
    # edge: закуп только на extra_catalog_codes, primary пустой
    products = MemoryDomainProductStore()
    product = create_domain_product("BonaAqua", store=products, lookup=FakeCatalogLookup(()))
    products.save(
        replace(
            product,
            extra_catalog_codes=("16161616003392",),
        )
    )
    mirrors = MemoryProcurementMirrorStore()
    mirrors.upsert(
        ProcurementMirror(
            catalog_code="16161616003392",
            supplier_id="a1",
            supplier_name="ООО",
            last_buy_price=Decimal("42"),
            supply_moment=_FROZEN_NOW,
            synced_at=_FROZEN_NOW,
        )
    )
    app, deps = _build_app(
        domain_product_store=products,
        procurement_mirror_enabled=True,
        procurement_mirror_store=mirrors,
    )
    _seed_line(deps, domain_product_id=product.domain_product_id, product_code="")
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert 'class="planogram-buy-price">42,00<' in response.text


def test_planogram_last_buy_em_dash_when_unlinked() -> None:
    # edge: no catalog_code → —
    products, product = _publishable_domain_product()
    app, deps = _build_app(
        domain_product_store=products,
        procurement_mirror_enabled=True,
        procurement_mirror_store=MemoryProcurementMirrorStore(),
    )
    _seed_line(deps, domain_product_id=product.domain_product_id, product_code="")
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert 'class="planogram-buy-price">—<' in response.text


def test_picker_js_updates_last_buy_from_page_map() -> None:
    # happy: typeahead selection updates Закуп from page JSON map
    js = Path("src/interfaces/admin/static/planogram_product_picker.js").read_text(encoding="utf-8")
    assert "planogram-last-buy-prices" in js
    assert "planogram-buy-price" in js
    assert "updateRowLastBuy" in js
