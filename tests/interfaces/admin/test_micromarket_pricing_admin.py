from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.interfaces.admin import test_planogram_panel_gates as panel_gates
from tests.interfaces.admin.test_micromarket_planogram_routes import (
    _build_app,
    _seed_line,
    _signed_widget_fields,
)

from src.application.master_data import MachineKind
from src.application.micromarket_loading.pricing_stores import (
    InMemoryMicromarketMachineMultiplierStore,
    InMemoryMicromarketPriceChangeJournal,
    InMemoryMicromarketPricingRulesStore,
    InMemoryMicromarketProductMultiplierStore,
)
from src.application.product_identity.procurement_mirror import ProcurementMirror
from src.domain.micromarket_pricing.formula import MicromarketPricingRules
from src.domain.system_user import AdminPanel
from src.infrastructure.product_identity.memory_procurement_mirror_store import (
    MemoryProcurementMirrorStore,
)
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
)
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes import register_admin_routes


def _with_pricing(deps: AdminHttpDeps) -> AdminHttpDeps:
    rules = InMemoryMicromarketPricingRulesStore()
    rules.save(
        MicromarketPricingRules(
            margin_percent=Decimal("50"),
            margin_floor=Decimal("20"),
            rounding_last_digits=None,
        )
    )
    return replace(
        deps,
        micromarket_pricing_rules_store=rules,
        micromarket_product_multiplier_store=InMemoryMicromarketProductMultiplierStore(),
        micromarket_machine_multiplier_store=InMemoryMicromarketMachineMultiplierStore(),
        micromarket_price_change_journal=InMemoryMicromarketPriceChangeJournal(),
    )


def _app_with_pricing(
    *,
    panels: frozenset[AdminPanel] | None = None,
) -> tuple[TestClient, AdminHttpDeps]:
    if panels is None:
        _app, deps = _build_app(machine_kind=MachineKind.MICRO_MARKET, machine_id="701")
    else:
        _app, deps = panel_gates._build_app(
            panels=panels,
            attach_micromarket_planogram=True,
            micromarket_stock_store=InMemoryMicromarketDeviceStockStore(),
        )
    deps = _with_pricing(deps)
    fresh = FastAPI()
    register_admin_routes(fresh, deps, enabled=True)
    return TestClient(fresh), deps


def _auth(client: TestClient) -> None:
    client.post("/admin/auth/telegram", data=_signed_widget_fields())


def test_prices_tab_renders() -> None:
    client, _deps = _app_with_pricing()
    _auth(client)
    response = client.get("/admin/micromarket-planograms?tab=prices")
    assert response.status_code == 200
    assert "Цены" in response.text
    assert 'name="margin_percent"' in response.text
    assert "Множители товаров" in response.text
    assert "Множители аппаратов" in response.text
    assert 'name="product_domain_id"' in response.text
    assert "Поиск (код / имя)" in response.text
    assert response.text.index("Множители аппаратов") < response.text.index("Множители товаров")


def test_prices_post_ok_with_matrix_pricing_when_users_disabled() -> None:
    client, deps = _app_with_pricing()
    _auth(client)
    response = client.post(
        "/admin/micromarket-planograms/prices",
        data={
            "margin_percent": "40",
            "margin_floor": "25",
            "rounding_last_digits": "",
            "product_domain_id": ["dp-water", ""],
            "product_multiplier": ["1.1", ""],
            "machine_id": ["701"],
            "machine_multiplier": ["1.2"],
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    rules = deps.micromarket_pricing_rules_store.get()  # type: ignore[union-attr]
    assert rules is not None
    assert rules.margin_percent == Decimal("40")
    product_store = deps.micromarket_product_multiplier_store
    assert product_store is not None
    assert product_store.get("dp-water") == Decimal("1.1")
    machine_store = deps.micromarket_machine_multiplier_store
    assert machine_store is not None
    assert machine_store.get("701") == Decimal("1.2")


def test_prices_post_forbidden_without_matrix_pricing() -> None:
    client, _deps = _app_with_pricing(
        panels=frozenset({AdminPanel.MICROMARKET_PLANOGRAMS}),
    )
    client.post("/admin/auth/telegram", data=panel_gates._signed_widget_fields())
    response = client.post(
        "/admin/micromarket-planograms/prices",
        data={"margin_percent": "40", "margin_floor": "25"},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_planogram_marks_manual_price_class() -> None:
    client, deps = _app_with_pricing()
    _seed_line(deps, product_code="2311", price_rub=Decimal("189"))
    doc = deps.micromarket_planogram_store.get("701")  # type: ignore[union-attr]
    assert doc is not None
    line = replace(doc.lines[0], price_origin="manual")
    deps.micromarket_planogram_store.upsert(replace(doc, lines=(line,)))  # type: ignore[union-attr]
    _auth(client)
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    assert "planogram-price-manual" in response.text
    assert 'class="planogram-price-reset"' in response.text
    assert "➡️" in response.text
    assert "🔄" not in response.text
    assert 'aria-label="К расчётной"' in response.text
    assert ">к расчётной<" not in response.text.lower()
    assert "planogram-price-domain" in response.text
    assert 'aria-label="Цена домена"' in response.text
    assert 'name="price_rub-0"' in response.text
    assert 'value="189"' in response.text
    assert "Коэффициент аппарата" in response.text
    assert "Сбросить все цены" in response.text


def test_planogram_manual_shows_domain_price_from_formula() -> None:
    mirrors = MemoryProcurementMirrorStore()
    mirrors.upsert(
        ProcurementMirror(
            catalog_code="2311",
            supplier_id="a1",
            supplier_name="ООО",
            last_buy_price=Decimal("100"),
            supply_moment=datetime(2026, 10, 1, tzinfo=UTC),
            synced_at=datetime(2026, 10, 1, tzinfo=UTC),
        )
    )
    _app, deps = _build_app(
        machine_kind=MachineKind.MICRO_MARKET,
        machine_id="701",
        procurement_mirror_enabled=True,
        procurement_mirror_store=mirrors,
    )
    deps = _with_pricing(deps)
    fresh = FastAPI()
    register_admin_routes(fresh, deps, enabled=True)
    client = TestClient(fresh)
    _seed_line(deps, product_code="2311", price_rub=Decimal("189"))
    doc = deps.micromarket_planogram_store.get("701")  # type: ignore[union-attr]
    assert doc is not None
    line = replace(doc.lines[0], price_origin="manual")
    deps.micromarket_planogram_store.upsert(replace(doc, lines=(line,)))  # type: ignore[union-attr]
    _auth(client)
    response = client.get("/admin/micromarket-planograms/701")
    assert response.status_code == 200
    # P=100, margin=max(50,20)=50 → domain sell=150
    assert "planogram-price-domain" in response.text
    assert 'value="150"' in response.text
