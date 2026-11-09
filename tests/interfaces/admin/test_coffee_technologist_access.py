from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests._company_roles_for_panels import company_roles_for_test_panels
from tests.application.product_identity.fakes import FakeCatalogLookup

from src.application.form_inventory_policy import MemoryFormInventoryPolicyStore
from src.application.master_data import (
    InMemoryMasterDataStores,
    InMemorySystemUserStore,
    SystemUserRecord,
)
from src.application.product_identity import MemoryBorderRegistrationStore, create_domain_product
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
from src.domain.system_user import AdminPanel, BotRole, SystemUser, SystemUserId
from src.infrastructure.product_identity import MemoryDomainProductStore
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_FROZEN_NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
_ORIGIN = {"origin": "http://testserver"}
_INGREDIENT = CatalogProduct(code="raw-1", name="Зерно", archived=False)
_DRINK = CatalogProduct(code="drink-legacy", name="Латте", archived=False)


@dataclass(frozen=True, slots=True)
class _CoffeeApp:
    client: TestClient
    store: MemoryDomainProductStore


def _login(client: TestClient) -> None:
    response = client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}


def _build(*, panels: frozenset[AdminPanel]) -> _CoffeeApp:
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
        form_inventory_policy_store=MemoryFormInventoryPolicyStore(),
        catalog_product_lookup=FakeCatalogLookup((_INGREDIENT, _DRINK)),
        border_registration_store=MemoryBorderRegistrationStore(),
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return _CoffeeApp(client=TestClient(app), store=store)


def test_technologist_creates_ingredient_curator_unlinks() -> None:
    from src.application.product_identity.commands import add_domain_product_link

    tech = _build(panels=frozenset({AdminPanel.COFFEE_RECIPES}))
    _login(tech.client)
    created = tech.client.post(
        "/admin/coffee-ingredients/new",
        data={"name": "Молоко", "unit": "g", "pack_size": "1000", "action": "save"},
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert created.status_code == 303
    product = next(p for p in tech.store.list_visible() if p.kind == "coffee_ingredient")
    assert product.catalog_code is None
    assert product.pack_size is not None

    lookup = FakeCatalogLookup((_INGREDIENT, _DRINK))
    add_domain_product_link(product.domain_product_id, "raw-1", store=tech.store, lookup=lookup)
    curator = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS}))
    curator.store.save(tech.store.get(product.domain_product_id))  # type: ignore[arg-type]
    _login(curator.client)
    unlinked = curator.client.post(
        f"/admin/coffee-ingredients/{product.domain_product_id}",
        data={"action": "unlink:raw-1"},
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert unlinked.status_code == 303
    saved = curator.store.get(product.domain_product_id)
    assert saved is not None
    assert saved.catalog_code is None


def test_curator_cannot_create_ingredient() -> None:
    app = _build(panels=frozenset({AdminPanel.DOMAIN_PRODUCTS}))
    _login(app.client)
    nested = app.client.get("/admin/domain-products/coffee-ingredients", follow_redirects=False)
    assert nested.status_code == 301
    assert app.client.get("/admin/coffee-ingredients").status_code == 200
    denied = app.client.post(
        "/admin/coffee-ingredients/new",
        data={"name": "Молоко", "unit": "g", "pack_size": "1000", "action": "save"},
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert denied.status_code == 403


def test_technologist_cannot_unlink_or_open_border() -> None:
    from src.application.product_identity.commands import add_domain_product_link

    app = _build(panels=frozenset({AdminPanel.COFFEE_RECIPES}))
    _login(app.client)
    lookup = FakeCatalogLookup((_INGREDIENT, _DRINK))
    product = create_domain_product(
        "Молоко",
        store=app.store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    add_domain_product_link(product.domain_product_id, "raw-1", store=app.store, lookup=lookup)
    denied_unlink = app.client.post(
        f"/admin/coffee-ingredients/{product.domain_product_id}",
        data={"action": "unlink:raw-1"},
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert denied_unlink.status_code == 403
    assert app.client.get("/admin/coffee-border-registration").status_code == 403


def test_master_data_alone_forbidden_on_coffee() -> None:
    app = _build(panels=frozenset({AdminPanel.MASTER_DATA}))
    _login(app.client)
    assert app.client.get("/admin/coffee-drinks").status_code == 403
    assert app.client.get("/admin/coffee-ingredients").status_code == 403
    assert app.client.get("/admin/coffee-border-registration").status_code == 403
