from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests._company_roles_for_panels import company_roles_for_test_panels
from tests.application.product_identity.fakes import FakeCatalogLookup

from src.application.form_inventory_policy import (
    COFFEE_LOADING_PROFILE_ID,
    MemoryFormInventoryPolicyStore,
)
from src.application.master_data import (
    InMemoryMasterDataStores,
    InMemorySystemUserStore,
    SystemUserRecord,
)
from src.application.product_identity import MemoryBorderRegistrationStore, note_unregistered_codes
from src.application.product_identity.models import CatalogProduct
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.sheets import SystemUsersSnapshot
from src.domain.product_catalog import ProductUnit
from src.domain.system_user import AdminPanel, BotRole, CompanyRole, SystemUser, SystemUserId
from src.infrastructure.product_identity import MemoryDomainProductStore
from src.infrastructure.testing.coffee_recipe_fakes import InMemoryCoffeeRecipeRepository
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_FROZEN_NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
_ORIGIN = {"origin": "http://testserver"}
_CREATE_POLICIES = {
    "loading_radio_n": "10",
    "revision_min_qty": "0",
    "revision_max_qty": "4999",
    "warehouse_min_qty": "0",
    "warehouse_max_qty": "12",
}
_INGREDIENT = CatalogProduct(code="raw-1", name="Зерно", archived=False)
_INGREDIENT_B = CatalogProduct(code="raw-2", name="Сироп", archived=False)
_DRINK = CatalogProduct(code="drink-legacy", name="Латте", archived=False)


@dataclass(frozen=True, slots=True)
class _CoffeeApp:
    client: TestClient
    store: MemoryDomainProductStore
    border: MemoryBorderRegistrationStore
    provider: ReferenceDataProvider
    policies: MemoryFormInventoryPolicyStore


def _login(client: TestClient) -> None:
    response = client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}


def _build(
    *,
    panels: frozenset[AdminPanel],
    with_border: bool = True,
    company_roles: frozenset[CompanyRole] | None = None,
    product_catalog_rows: list[list[str]] | None = None,
) -> _CoffeeApp:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["001", "Иван"]],
    )
    if product_catalog_rows is not None:
        provider.apply_rows(ReferenceDataSourceId.PRODUCT_CATALOG, product_catalog_rows)
    roster_store = InMemoryLocationRosterStore()
    provider.configure_roster(enabled=True, store=roster_store)
    user = SystemUser(
        user_id=SystemUserId("1"),
        name="Ops",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=_ADMIN_TG,
        technician_id=None,
        company_roles=(
            company_roles if company_roles is not None else company_roles_for_test_panels(panels)
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
    store = MemoryDomainProductStore()
    policies = MemoryFormInventoryPolicyStore()
    border = MemoryBorderRegistrationStore()
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
        form_inventory_policy_store=policies,
        catalog_product_lookup=FakeCatalogLookup((_INGREDIENT, _INGREDIENT_B, _DRINK)),
        coffee_recipe_repo=InMemoryCoffeeRecipeRepository(),
        border_registration_store=border if with_border else None,
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return _CoffeeApp(
        client=TestClient(app),
        store=store,
        border=border,
        provider=provider,
        policies=policies,
    )


def test_coffee_ingredient_create_without_link() -> None:
    app = _build(panels=frozenset({AdminPanel.COFFEE_RECIPES}))
    _login(app.client)
    form = app.client.get("/admin/coffee-ingredients/new")
    assert form.status_code == 200
    assert "Связи МойСклад" not in form.text
    assert "Код МС" not in form.text
    assert "loading_radio_n" in form.text
    assert "revision_max_qty" in form.text
    assert "warehouse_max_qty" in form.text
    created = app.client.post(
        "/admin/coffee-ingredients/new",
        data={
            "name": "Зерно Арабика",
            "unit": "g",
            "pack_size": "1000",
            **_CREATE_POLICIES,
            "action": "save",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert created.status_code == 303
    page = app.client.get("/admin/coffee-ingredients")
    assert page.status_code == 200
    assert "Зерно Арабика" in page.text
    assert 'href="/admin/coffee-ingredients/new"' in page.text
    assert "Связать" not in page.text
    products = [p for p in app.store.list_visible() if p.kind == "coffee_ingredient"]
    assert len(products) == 1
    assert products[0].catalog_code is None
    assert f'href="/admin/coffee-ingredients/{products[0].domain_product_id}"' in page.text
    number = products[0].number
    loading = app.policies.get_line(COFFEE_LOADING_PROFILE_ID, number)
    assert loading is not None
    assert loading.radio_n == 10
    from src.application.form_inventory_policy import (
        COFFEE_REVISION_PROFILE_ID,
        TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID,
    )

    revision = app.policies.get_line(COFFEE_REVISION_PROFILE_ID, number)
    assert revision is not None
    assert revision.max_qty == Decimal("4999")
    warehouse = app.policies.get_line(TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID, number)
    assert warehouse is not None
    assert warehouse.max_qty == Decimal("12")


def test_create_ingredient_requires_policy_fields() -> None:
    app = _build(panels=frozenset({AdminPanel.COFFEE_RECIPES}))
    _login(app.client)
    response = app.client.post(
        "/admin/coffee-ingredients/new",
        data={
            "name": "Без политик",
            "unit": "g",
            "pack_size": "1000",
            "action": "save",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "политик" in response.text.casefold()
    assert not [p for p in app.store.list_visible() if p.kind == "coffee_ingredient"]


def test_edit_card_has_no_policy_fields_and_save_keeps_policies() -> None:
    from src.application.form_inventory_policy import (
        COFFEE_REVISION_PROFILE_ID,
        TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID,
        FormInventoryPolicyLine,
        seed_coffee_ingredient_policies,
    )
    from src.application.product_identity.commands import create_domain_product

    app = _build(panels=frozenset({AdminPanel.COFFEE_RECIPES}))
    _login(app.client)
    lookup = FakeCatalogLookup((_INGREDIENT, _INGREDIENT_B, _DRINK))
    product = create_domain_product(
        "Сироп",
        store=app.store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.MILLILITER,
        pack_size=Decimal("1000"),
    )
    seed_coffee_ingredient_policies(
        app.policies,
        domain_number=product.number,
        loading=FormInventoryPolicyLine(
            domain_number=product.number,
            min_qty=Decimal("0"),
            max_qty=Decimal("8"),
            radio_n=8,
        ),
        revision=FormInventoryPolicyLine(
            domain_number=product.number,
            min_qty=Decimal("0"),
            max_qty=Decimal("3000"),
        ),
        warehouse=FormInventoryPolicyLine(
            domain_number=product.number,
            min_qty=Decimal("0"),
            max_qty=Decimal("5"),
        ),
    )
    card = app.client.get(f"/admin/coffee-ingredients/{product.domain_product_id}")
    assert card.status_code == 200
    assert 'name="min_qty"' not in card.text
    assert 'name="max_qty"' not in card.text
    assert 'name="radio_n"' not in card.text
    assert 'name="loading_radio_n"' not in card.text
    saved = app.client.post(
        f"/admin/coffee-ingredients/{product.domain_product_id}",
        data={
            "name": "Сироп ваниль",
            "unit": "ml",
            "pack_size": "1000",
            "action": "save",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert saved.status_code == 303
    warehouse = app.policies.get_line(TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID, product.number)
    assert warehouse is not None
    assert warehouse.max_qty == Decimal("5")
    revision = app.policies.get_line(COFFEE_REVISION_PROFILE_ID, product.number)
    assert revision is not None
    assert revision.max_qty == Decimal("3000")


def test_policies_bulk_empty_max_shows_error() -> None:
    from src.application.form_inventory_policy import (
        COFFEE_REVISION_PROFILE_ID,
        FormInventoryPolicyLine,
        upsert_policy_line,
    )

    app = _build(panels=frozenset({AdminPanel.COFFEE_RECIPES}))
    _login(app.client)
    upsert_policy_line(
        app.policies,
        profile_id=COFFEE_REVISION_PROFILE_ID,
        domain_number="d-1",
        min_qty=Decimal("0"),
        max_qty=Decimal("2000"),
        radio_n=None,
    )
    response = app.client.post(
        "/admin/coffee-form-policies",
        data={
            "action": "bulk_save",
            "profile_id": COFFEE_REVISION_PROFILE_ID,
            "domain_number": "d-1",
            "form_label": "",
            "form_hint": "",
            "min_qty": "0",
            "max_qty": "",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "Min и Max" in response.text
    line = app.policies.get_line(COFFEE_REVISION_PROFILE_ID, "d-1")
    assert line is not None
    assert line.max_qty == Decimal("2000")
    assert isinstance(line, FormInventoryPolicyLine)


def test_policies_page_has_tiles_and_save_bar() -> None:
    from src.application.form_inventory_policy import (
        COFFEE_REVISION_PROFILE_ID,
        upsert_policy_line,
    )
    from src.application.product_identity.commands import create_domain_product

    app = _build(panels=frozenset({AdminPanel.COFFEE_RECIPES}))
    _login(app.client)
    lookup = FakeCatalogLookup((_INGREDIENT, _INGREDIENT_B, _DRINK))
    product = create_domain_product(
        "Молоко",
        store=app.store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    upsert_policy_line(
        app.policies,
        profile_id=COFFEE_REVISION_PROFILE_ID,
        domain_number=product.number,
        min_qty=Decimal("0"),
        max_qty=Decimal("2000"),
        radio_n=None,
        sort_order=1,
        form_label="Молоко",
        form_hint="канистра",
    )
    page = app.client.get(f"/admin/coffee-form-policies?profile={COFFEE_REVISION_PROFILE_ID}")
    assert page.status_code == 200
    assert "table.admin-roster" not in page.text
    assert 'class="admin-roster"' not in page.text
    assert 'class="admin-cell-input"' not in page.text
    assert "coffee-policy-tile" in page.text
    assert 'name="form_label"' in page.text
    assert 'name="form_hint"' in page.text
    assert 'name="min_qty"' in page.text
    assert 'name="max_qty"' in page.text
    assert "admin-save-bar" in page.text
    assert "Сохранить" in page.text
    assert "coffee-policy-tile-list" in page.text
    assert "policy-domain-number" not in page.text
    assert "Сохранить строку" not in page.text
    assert "input_mode:" not in page.text
    assert "Диапазон ввода" not in page.text
    assert "Молоко" in page.text
    assert "канистра" in page.text


def test_coffee_ingredient_card_removes_one_link() -> None:
    from src.application.product_identity.commands import (
        add_domain_product_link,
        create_domain_product,
    )

    app = _build(
        panels=frozenset({AdminPanel.COFFEE_RECIPES, AdminPanel.DOMAIN_PRODUCTS}),
        company_roles=frozenset(
            {CompanyRole.COFFEE_TECHNOLOGIST, CompanyRole.PLANOGRAM_CURATOR},
        ),
    )
    _login(app.client)
    lookup = FakeCatalogLookup((_INGREDIENT, _INGREDIENT_B, _DRINK))
    product = create_domain_product(
        "Молоко",
        store=app.store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.MILLILITER,
        pack_size=Decimal("1000"),
    )
    add_domain_product_link(product.domain_product_id, "raw-1", store=app.store, lookup=lookup)
    add_domain_product_link(product.domain_product_id, "raw-2", store=app.store, lookup=lookup)
    card = app.client.get(f"/admin/coffee-ingredients/{product.domain_product_id}")
    assert card.status_code == 200
    assert "Связи МойСклад" in card.text
    assert "raw-1" in card.text
    assert "raw-2" in card.text
    assert 'name="catalog_code"' not in card.text
    assert ">Связать<" not in card.text
    assert 'name="min_qty"' not in card.text
    assert 'name="radio_n"' not in card.text
    removed = app.client.post(
        f"/admin/coffee-ingredients/{product.domain_product_id}",
        data={"action": "unlink:raw-1"},
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert removed.status_code == 303
    saved = app.store.get(product.domain_product_id)
    assert saved is not None
    assert saved.catalog_code == "raw-2"
    assert saved.extra_catalog_codes == ()


def test_coffee_form_policies_panel_bulk_save() -> None:
    from src.application.form_inventory_policy import upsert_policy_line

    app = _build(panels=frozenset({AdminPanel.COFFEE_RECIPES}))
    _login(app.client)
    upsert_policy_line(
        app.policies,
        profile_id=COFFEE_LOADING_PROFILE_ID,
        domain_number="d-99",
        min_qty=Decimal("0"),
        max_qty=Decimal("5"),
        radio_n=5,
        sort_order=0,
    )
    upsert_policy_line(
        app.policies,
        profile_id=COFFEE_LOADING_PROFILE_ID,
        domain_number="d-100",
        min_qty=Decimal("0"),
        max_qty=Decimal("3"),
        radio_n=3,
        sort_order=1,
    )
    page = app.client.get("/admin/coffee-form-policies")
    assert page.status_code == 200
    assert "coffee_loading" in page.text
    assert "Radio N (уп.)" in page.text
    assert "Min (уп.)" not in page.text
    assert "Max (уп.)" not in page.text
    saved = app.client.post(
        "/admin/coffee-form-policies",
        data={
            "action": "bulk_save",
            "profile_id": COFFEE_LOADING_PROFILE_ID,
            "domain_number": ["d-100", "d-99"],
            "form_label": ["Сто", "Девяносто"],
            "form_hint": ["низ", "верх"],
            "radio_n": ["4", "7"],
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert saved.status_code == 303
    line_a = app.policies.get_line(COFFEE_LOADING_PROFILE_ID, "d-99")
    line_b = app.policies.get_line(COFFEE_LOADING_PROFILE_ID, "d-100")
    assert line_a is not None
    assert line_a.radio_n == 7
    assert line_a.sort_order == 1
    assert line_a.form_label == "Девяносто"
    assert line_a.form_hint == "верх"
    assert line_b is not None
    assert line_b.radio_n == 4
    assert line_b.sort_order == 0
    assert line_b.form_label == "Сто"
    assert line_b.form_hint == "низ"
    ordered = app.policies.list_lines(COFFEE_LOADING_PROFILE_ID)
    assert [line.domain_number for line in ordered] == ["d-100", "d-99"]


def test_coffee_form_policies_columns_by_profile_and_name() -> None:
    from src.application.form_inventory_policy import (
        COFFEE_REVISION_PROFILE_ID,
        TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID,
        upsert_policy_line,
    )
    from src.application.product_identity.commands import create_domain_product

    app = _build(panels=frozenset({AdminPanel.COFFEE_RECIPES}))
    _login(app.client)
    lookup = FakeCatalogLookup((_INGREDIENT, _INGREDIENT_B, _DRINK))
    product = create_domain_product(
        "Молоко сухое",
        store=app.store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    upsert_policy_line(
        app.policies,
        profile_id=COFFEE_REVISION_PROFILE_ID,
        domain_number=product.number,
        min_qty=Decimal("0"),
        max_qty=Decimal("4999"),
        radio_n=None,
    )
    upsert_policy_line(
        app.policies,
        profile_id=TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID,
        domain_number=product.number,
        min_qty=Decimal("0"),
        max_qty=Decimal("12"),
        radio_n=None,
    )
    revision = app.client.get(f"/admin/coffee-form-policies?profile={COFFEE_REVISION_PROFILE_ID}")
    assert revision.status_code == 200
    assert "Min (г)" in revision.text
    assert "Max (г)" in revision.text
    assert "Radio N" not in revision.text
    assert product.number in revision.text
    assert "Молоко сухое" in revision.text

    warehouse = app.client.get(
        f"/admin/coffee-form-policies?profile={TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID}"
    )
    assert warehouse.status_code == 200
    assert "Min (уп.)" in warehouse.text
    assert "Max (уп.)" in warehouse.text
    assert "Radio N" not in warehouse.text


def test_coffee_ingredients_canon_path_and_legacy_301() -> None:
    app = _build(panels=frozenset({AdminPanel.COFFEE_RECIPES}))
    _login(app.client)
    legacy = app.client.get("/admin/domain-products/coffee-ingredients", follow_redirects=False)
    assert legacy.status_code == 301
    assert legacy.headers["location"] == "/admin/coffee-ingredients"
    page = app.client.get("/admin/coffee-ingredients")
    assert page.status_code == 200


def test_coffee_unhide_ui_restores_ingredient() -> None:
    app = _build(panels=frozenset({AdminPanel.COFFEE_RECIPES}))
    _login(app.client)
    app.client.post(
        "/admin/coffee-ingredients/new",
        data={
            "name": "Скрыть меня",
            "unit": "g",
            "pack_size": "1000",
            **_CREATE_POLICIES,
            "action": "save",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    product = next(p for p in app.store.list_visible() if p.kind == "coffee_ingredient")
    hide = app.client.post(
        "/admin/coffee-ingredients/hide",
        data={"domain_product_id": product.domain_product_id},
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert hide.status_code == 303
    assert app.store.get(product.domain_product_id).hidden is True  # type: ignore[union-attr]
    page = app.client.get("/admin/coffee-ingredients")
    assert "Скрыть меня" in page.text
    assert "Восстановить" in page.text
    restore = app.client.post(
        "/admin/coffee-ingredients/unhide",
        data={"domain_product_id": product.domain_product_id},
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert restore.status_code == 303
    assert app.store.get(product.domain_product_id).hidden is False  # type: ignore[union-attr]


def test_coffee_drink_create_with_legacy_code() -> None:
    app = _build(panels=frozenset({AdminPanel.COFFEE_RECIPES}))
    _login(app.client)
    created = app.client.post(
        "/admin/coffee-drinks",
        data={"name": "Латте", "legacy_ms_code": "drink-legacy"},
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert created.status_code == 303
    page = app.client.get("/admin/coffee-drinks")
    assert page.status_code == 200
    assert "Латте" in page.text
    assert "drink-legacy" in page.text
    drinks = [p for p in app.store.list_visible() if p.kind == "coffee_drink"]
    assert len(drinks) == 1
    assert drinks[0].legacy_ms_code == "drink-legacy"


def test_domain_products_list_has_no_coffee_tabs() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS}))
    _login(app.client)
    html = app.client.get("/admin/domain-products").text
    assert 'href="/admin/domain-products/coffee-ingredients"' not in html
    assert "Кофейные ингредиенты" not in html


def test_sidebar_includes_coffee_bom_panels() -> None:
    app = _build(
        panels=frozenset({AdminPanel.DOMAIN_PRODUCTS}),
        company_roles=frozenset(
            {CompanyRole.PLANOGRAM_CURATOR, CompanyRole.COFFEE_TECHNOLOGIST},
        ),
    )
    _login(app.client)
    html = app.client.get("/admin/domain-products").text
    assert 'href="/admin/coffee-drinks"' in html
    assert "Напитки и состав" in html
    assert 'href="/admin/coffee-border-registration"' in html
    assert "Регистрация границы МС→техник" in html
    assert 'href="/admin/coffee-ingredients"' in html


def test_mm_card_post_redirects_coffee_without_hide() -> None:
    app = _build(
        panels=frozenset({AdminPanel.DOMAIN_PRODUCTS, AdminPanel.COFFEE_RECIPES}),
        company_roles=frozenset(
            {CompanyRole.PLANOGRAM_CURATOR, CompanyRole.COFFEE_TECHNOLOGIST},
        ),
    )
    _login(app.client)
    app.client.post(
        "/admin/coffee-ingredients/new",
        data={
            "name": "Чужой hide",
            "unit": "g",
            "pack_size": "1000",
            **_CREATE_POLICIES,
            "action": "save",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    product = next(p for p in app.store.list_visible() if p.kind == "coffee_ingredient")
    response = app.client.post(
        f"/admin/domain-products/{product.domain_product_id}",
        data={"action": "hide"},
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/coffee-ingredients"
    saved = app.store.get(product.domain_product_id)
    assert saved is not None
    assert saved.hidden is False


def test_domain_products_list_has_no_border_queue() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS}))
    _login(app.client)
    note_unregistered_codes(("orphan-9",), products=app.store, border=app.border)
    border_page = app.client.get("/admin/coffee-border-registration")
    assert border_page.status_code == 200
    assert "orphan-9" in border_page.text
    assert "Имя МС" in border_page.text
    assert "—" in border_page.text
    assert 'action="/admin/coffee-border-registration/save"' in border_page.text
    assert "Код МС" in border_page.text
    assert 'action="/admin/coffee-border-registration/link"' not in border_page.text
    mm = app.client.get("/admin/domain-products")
    assert mm.status_code == 200
    assert "Очередь unregistered" not in mm.text
    assert "Игнорируемые" not in mm.text
    assert 'action="/admin/coffee-border-registration/save"' not in mm.text


def test_border_queue_get_options_and_ms_name() -> None:
    from src.application.product_identity.commands import create_domain_product

    app = _build(
        panels=frozenset({AdminPanel.DOMAIN_PRODUCTS}),
        product_catalog_rows=[
            ["code", "name", "entity_kind"],
            ["raw-1", "Зерно МС", "product"],
            ["raw-missing", "Нет в очереди", "product"],
        ],
    )
    _login(app.client)
    note_unregistered_codes(("raw-1", "orphan-9"), products=app.store, border=app.border)
    lookup = FakeCatalogLookup((_INGREDIENT, _INGREDIENT_B, _DRINK))
    ingredient = create_domain_product(
        "Milk<script>",
        store=app.store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    create_domain_product(
        "MM Only",
        store=app.store,
        lookup=lookup,
        kind="micromarket",
    )
    page = app.client.get("/admin/coffee-border-registration")
    assert page.status_code == 200
    assert "Зерно МС" in page.text
    assert "orphan-9" in page.text
    assert "—" in page.text
    match = re.search(
        r'<script type="application/json" id="planogram-domain-product-options">(.*?)</script>',
        page.text,
        flags=re.DOTALL,
    )
    assert match is not None
    raw = match.group(1)
    assert "<script>" not in raw
    assert "\\u003c" in raw
    options = json.loads(raw)
    assert isinstance(options, list)
    assert len(options) == 1
    assert options[0]["domain_product_id"] == ingredient.domain_product_id
    assert options[0]["name"] == "Milk<script>"
    assert "id" not in options[0]
    assert options[0]["linked"] is False


def test_border_queue_save_links_and_ignores() -> None:
    from src.application.product_identity.border_registration import border_status
    from src.application.product_identity.commands import create_domain_product

    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS}))
    _login(app.client)
    note_unregistered_codes(("raw-1", "raw-2"), products=app.store, border=app.border)
    lookup = FakeCatalogLookup((_INGREDIENT, _INGREDIENT_B, _DRINK))
    ingredient = create_domain_product(
        "MilkDom",
        store=app.store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    response = app.client.post(
        "/admin/coffee-border-registration/save",
        data={
            "ms_code": ["raw-1", "raw-2"],
            "domain_product_id": [ingredient.domain_product_id, ""],
            "ignored": ["0", "1"],
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/coffee-border-registration"
    assert border_status("raw-1", products=app.store, border=app.border) == "linked"
    assert border_status("raw-2", products=app.store, border=app.border) == "ignored"


def test_border_queue_save_skips_undecided_rows() -> None:
    from src.application.product_identity.border_registration import border_status
    from src.application.product_identity.commands import create_domain_product

    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS}))
    _login(app.client)
    note_unregistered_codes(("raw-1", "raw-2", "raw-3"), products=app.store, border=app.border)
    lookup = FakeCatalogLookup((_INGREDIENT, _INGREDIENT_B, _DRINK))
    ingredient = create_domain_product(
        "MilkDom",
        store=app.store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    response = app.client.post(
        "/admin/coffee-border-registration/save",
        data={
            "ms_code": ["raw-1", "raw-2", "raw-3"],
            "domain_product_id": [ingredient.domain_product_id, "", ""],
            "ignored": ["0", "0", "1"],
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/coffee-border-registration"
    assert border_status("raw-1", products=app.store, border=app.border) == "linked"
    assert border_status("raw-2", products=app.store, border=app.border) == "unregistered"
    assert border_status("raw-3", products=app.store, border=app.border) == "ignored"


def test_border_queue_save_all_undecided_is_noop() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS}))
    _login(app.client)
    note_unregistered_codes(("raw-1",), products=app.store, border=app.border)
    response = app.client.post(
        "/admin/coffee-border-registration/save",
        data={
            "ms_code": ["raw-1"],
            "domain_product_id": [""],
            "ignored": ["0"],
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/coffee-border-registration"
    from src.application.product_identity.border_registration import border_status

    assert border_status("raw-1", products=app.store, border=app.border) == "unregistered"


def test_border_ignored_list_shows_ms_name_or_em_dash() -> None:
    from src.application.product_identity.border_registration import ignore_border_code

    app = _build(
        panels=frozenset({AdminPanel.DOMAIN_PRODUCTS}),
        product_catalog_rows=[
            ["code", "name", "entity_kind"],
            ["ign-named", "Игнор МС", "product"],
        ],
    )
    _login(app.client)
    ignore_border_code("ign-named", products=app.store, border=app.border)
    ignore_border_code("ign-orphan", products=app.store, border=app.border)
    page = app.client.get("/admin/coffee-border-registration")
    assert page.status_code == 200
    assert "Уже игнорируются" in page.text
    assert "ign-named" in page.text
    assert "Игнор МС" in page.text
    assert "ign-orphan" in page.text
    assert re.search(r"ign-orphan[\s\S]*?—", page.text) is not None


def test_border_picker_hidden_css_covers_attribute() -> None:
    from pathlib import Path

    css = Path("src/interfaces/admin/static/planogram.css").read_text(encoding="utf-8")
    assert ".border-product-picker[hidden]" in css
    js = Path("src/interfaces/admin/static/coffee_border_registration.js").read_text(
        encoding="utf-8"
    )
    assert "picker.hidden = ignored" in js
    html = Path("src/interfaces/admin/templates/coffee_border_registration.html").read_text(
        encoding="utf-8"
    )
    assert "border-product-picker" in html
    assert "border-ignore-mark" in html


def test_border_queue_save_rejects_card_taken() -> None:
    from src.application.product_identity.border_registration import border_status
    from src.application.product_identity.commands import (
        add_domain_product_link,
        create_domain_product,
    )

    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS}))
    _login(app.client)
    note_unregistered_codes(("raw-1", "raw-2"), products=app.store, border=app.border)
    lookup = FakeCatalogLookup((_INGREDIENT, _INGREDIENT_B, _DRINK))
    holder = create_domain_product(
        "Holder",
        store=app.store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    add_domain_product_link(holder.domain_product_id, "raw-1", store=app.store, lookup=lookup)
    other = create_domain_product(
        "Other",
        store=app.store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    response = app.client.post(
        "/admin/coffee-border-registration/save",
        data={
            "ms_code": ["raw-2", "raw-1"],
            "domain_product_id": ["", other.domain_product_id],
            "ignored": ["1", "0"],
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    assert border_status("raw-2", products=app.store, border=app.border) == "unregistered"
    assert border_status("raw-1", products=app.store, border=app.border) == "linked"
