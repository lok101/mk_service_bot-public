from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests._company_roles_for_panels import company_roles_for_test_panels
from tests.application.product_identity.fakes import FakeCatalogLookup

from src.application.master_data import (
    InMemoryMasterDataStores,
    InMemorySystemUserStore,
    SystemUserRecord,
)
from src.application.product_identity.models import CatalogProduct, DomainProduct
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.sheets import SystemUsersSnapshot
from src.domain.system_user import AdminPanel, BotRole, SystemUser, SystemUserId
from src.infrastructure.product_identity import MemoryDomainProductStore
from src.infrastructure.testing.coffee_recipe_fakes import InMemoryCoffeeRecipeRepository
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes

_BOT_TOKEN = "test-bot-token"
_SESSION_SECRET = "admin-session-secret"
_ADMIN_TG = 1001
_FROZEN_NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
_ORIGIN = {"origin": "http://testserver"}


@dataclass(frozen=True, slots=True)
class _CoffeeBomApp:
    client: TestClient
    store: MemoryDomainProductStore
    recipes: InMemoryCoffeeRecipeRepository


def _login(client: TestClient) -> None:
    response = client.post(
        "/admin/auth/stub",
        data={"telegram_user_id": str(_ADMIN_TG)},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}


def _build(
    *,
    refresh_pending_after_bom: Callable[[], None] | None = None,
) -> _CoffeeBomApp:
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
        company_roles=company_roles_for_test_panels(frozenset({AdminPanel.COFFEE_RECIPES})),
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
    store.insert(
        DomainProduct(
            domain_product_id="drink-1",
            number="D-001",
            name="Латте",
            catalog_code=None,
            hidden=False,
            kind="coffee_drink",
            legacy_ms_code="2301",
        ),
    )
    store.insert(
        DomainProduct(
            domain_product_id="ing-1",
            number="I-001",
            name="Зерно",
            catalog_code="raw-1",
            hidden=False,
            kind="coffee_ingredient",
        ),
    )
    recipes = InMemoryCoffeeRecipeRepository()
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
        coffee_recipe_repo=recipes,
        refresh_pending_after_bom=refresh_pending_after_bom,
        catalog_product_lookup=FakeCatalogLookup(
            (CatalogProduct(code="raw-1", name="Зерно", archived=False),),
        ),
    )
    app = FastAPI()
    register_admin_routes(app, deps, enabled=True)
    return _CoffeeBomApp(client=TestClient(app), store=store, recipes=recipes)


def test_coffee_drinks_post_composition() -> None:
    refreshed: list[bool] = []
    app = _build(refresh_pending_after_bom=lambda: refreshed.append(True))
    _login(app.client)
    saved = app.client.post(
        "/admin/coffee-drinks/recipe",
        data={
            "drink_product_id": "drink-1",
            "ingredient_product_id": "ing-1",
            "quantity_per_unit": "12.5",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert saved.status_code == 303
    recipe = app.recipes.get("drink-1")
    assert recipe is not None
    assert recipe.components[0].ingredient_product_id == "ing-1"
    assert recipe.components[0].quantity_per_unit == Decimal("12.5")
    assert refreshed == [True]
    page = app.client.get("/admin/coffee-drinks")
    assert page.status_code == 200
    assert "12.5" in page.text
    assert "Удалить" in page.text


def test_coffee_drinks_empty_components_clears_recipe() -> None:
    app = _build()
    _login(app.client)
    app.client.post(
        "/admin/coffee-drinks/recipe",
        data={
            "drink_product_id": "drink-1",
            "ingredient_product_id": "ing-1",
            "quantity_per_unit": "1",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    cleared = app.client.post(
        "/admin/coffee-drinks/recipe",
        data={
            "drink_product_id": "drink-1",
            "ingredient_product_id": "",
            "quantity_per_unit": "",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert cleared.status_code == 303
    recipe = app.recipes.get("drink-1")
    assert recipe is not None
    assert recipe.components == ()


def test_coffee_drinks_rejects_bad_ingredient_id() -> None:
    app = _build()
    _login(app.client)
    response = app.client.post(
        "/admin/coffee-drinks/recipe",
        data={
            "drink_product_id": "drink-1",
            "ingredient_product_id": "missing",
            "quantity_per_unit": "1",
        },
        headers=_ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in (response.headers.get("location") or "")
    assert app.recipes.get("drink-1") is None
    page = app.client.get(response.headers["location"])
    assert page.status_code == 200
    assert "ingredient" in page.text.lower() or "Unknown" in page.text
