from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from tests.application.product_identity.fakes import FakeCatalogLookup, FakeDomainProductStore

from src.application.master_data import MachineKind
from src.application.micromarket_loading.inventory_form_pages import InventoryFormPage
from src.application.micromarket_loading.issue_inventory_link import (
    IssuedMicromarketInventoryLink,
    IssueMicromarketInventoryLink,
)
from src.application.micromarket_loading.planogram import (
    MicromarketPlanogram,
    MicromarketPlanogramLine,
    MicromarketPlanogramShelf,
)
from src.application.product_identity import create_domain_product
from src.domain.ids import MachineId, TechnicianId
from src.domain.results import ServiceCapabilities
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
    InMemoryMicromarketInventoryFormRegistry,
    InMemoryMicromarketPlanogramStore,
    StaticMachineKindLookup,
    StubMicromarketInventoryFormFactory,
    StubMicromarketInventoryFormsConfig,
)
from src.interfaces.telegram.machines.micromarket_inventory_workspace import (
    NO_MICROMARKET_SKU_MESSAGE,
    issue_micromarket_inventory_now_link,
    micromarket_inventory_workspace_flags,
    resolve_micromarket_inventory_sku_codes,
)
from src.interfaces.telegram.machines.workspace_getter import build_workspace_payload
from src.interfaces.telegram.machines.workspace_screen import button_label

_MACHINE = MachineId("701")
_TECH = TechnicianId("tech-1")
_ISSUED_AT = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _bot_user() -> SystemUser:
    return SystemUser(
        user_id=SystemUserId("10001"),
        name="Test",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=1,
        technician_id=_TECH,
        company_roles=frozenset(),
    )


def _caps() -> ServiceCapabilities:
    return ServiceCapabilities(
        technician_id=_TECH,
        machine_id=_MACHINE,
        responsibility_phase="responsible",
        can_complete_revision=False,
        can_submit_loading=False,
        can_submit_loading_photos=False,
        can_complete_maintenance=True,
        revision_form_link=None,
    )


_FIELD_BASE = "https://bot.example.com"


def _issue_uc() -> IssueMicromarketInventoryLink:
    return IssueMicromarketInventoryLink(
        registry=InMemoryMicromarketInventoryFormRegistry(),
        factory=StubMicromarketInventoryFormFactory(),
        forms_settings=StubMicromarketInventoryFormsConfig(),
        field_forms_public_base_url=_FIELD_BASE,
        now_template_id="tpl-now",
        as_of_template_id="tpl-as-of",
        token_entry_id="entry.mm",
        now_token_secret="now-secret",
        as_of_token_secret="as-of-secret",
        clock=lambda: _ISSUED_AT,
        qty_max=30,
    )


def test_resolve_inventory_sku_codes_includes_pending_exit_line() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    p_active = create_domain_product("Активный", store=store, lookup=lookup)
    p_exit = create_domain_product("На выбытие", store=store, lookup=lookup)
    planogram_store = InMemoryMicromarketPlanogramStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    planogram_store.upsert(
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
                    domain_product_id=p_active.domain_product_id,
                ),
                MicromarketPlanogramLine(
                    product_code="",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=False,
                    sort_order=1,
                    kit_group_id=6348,
                    pending_exit=True,
                    domain_product_id=p_exit.domain_product_id,
                ),
            ),
            updated_at=_ISSUED_AT,
            shelves=(MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),),
        )
    )
    codes = resolve_micromarket_inventory_sku_codes(
        machine_code="701",
        planogram_store=planogram_store,
        stock_store=stock_store,
        products=store,
    )
    # pages order: active by name, then pending_exit (not sorted codes)
    assert codes == [p_active.number, p_exit.number]


def test_resolve_inventory_sku_codes_uses_domain_number_without_catalog() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    product = create_domain_product("Молоко", store=store, lookup=lookup)
    planogram_store = InMemoryMicromarketPlanogramStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    planogram_store.upsert(
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
            updated_at=_ISSUED_AT,
        )
    )
    codes = resolve_micromarket_inventory_sku_codes(
        machine_code="701",
        planogram_store=planogram_store,
        stock_store=stock_store,
        products=store,
    )
    assert codes == [product.number]


def test_resolve_inventory_sku_codes_skips_product_code_only_line() -> None:
    store = FakeDomainProductStore()
    planogram_store = InMemoryMicromarketPlanogramStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    planogram_store.upsert(
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
            updated_at=_ISSUED_AT,
        )
    )
    codes = resolve_micromarket_inventory_sku_codes(
        machine_code="701",
        planogram_store=planogram_store,
        stock_store=stock_store,
        products=store,
    )
    assert codes == []


def test_issue_now_link_button_url_is_field_form() -> None:
    """happy: «Открыть форму» URL is FieldForm (not Google)."""
    result = issue_micromarket_inventory_now_link(
        machine_code=_MACHINE.value,
        technician_id=_TECH,
        issuer=_issue_uc(),
        pages=(InventoryFormPage(kit_group_id=10, product_codes=("d-1",), title="Холод"),),
    )
    assert isinstance(result, IssuedMicromarketInventoryLink)
    assert result.form_url.startswith(f"{_FIELD_BASE}/forms/micromarket-inventory/now?")
    assert "token=" in result.form_url
    assert "forms.gle" not in result.form_url
    assert "docs.google" not in result.form_url


def test_micromarket_workspace_inventory_button_only() -> None:
    flags = micromarket_inventory_workspace_flags(
        is_micromarket=True,
        issuer=_issue_uc(),
    )
    assert flags["micromarket_inventory_available"] is True
    assert flags["show_coffee_revision"] is False
    assert flags["show_coffee_loading"] is False
    assert flags["show_snack_inventory"] is False
    assert button_label("micromarket_inventory") == "Инвентаризация"
    assert button_label("snack_inventory") == "Инвентаризация снека"

    deps = MagicMock()
    deps.service_display_timezone = ZoneInfo("UTC")
    deps.get_service_capabilities.execute.return_value = _caps()
    deps.issue_snack_inventory_link = None
    deps.snack_inventory_cells = None
    deps.issue_micromarket_inventory_link = _issue_uc()
    deps.micromarket_planogram_store = InMemoryMicromarketPlanogramStore()
    deps.micromarket_stock_store = InMemoryMicromarketDeviceStockStore()
    deps.machine_kind_lookup = StaticMachineKindLookup(
        {_MACHINE.value: MachineKind.MICRO_MARKET},
    )
    manager = MagicMock()
    manager.dialog_data = {"machine_id": _MACHINE.value, "machine_name": "MM 701"}

    from src.interfaces.telegram.machines.maintenance_screen import MaintenanceScreenFlags

    with (
        patch(
            "src.interfaces.telegram.machines.workspace_getter.maintenance_screen_flags",
            return_value=MaintenanceScreenFlags(
                loading_completed=False,
                can_complete_maintenance=True,
                show_maintenance_back=False,
            ),
        ),
        patch(
            "src.interfaces.telegram.machines.workspace_getter.last_service_line_for_machine",
            return_value="🛠️ Последнее обслуживание: нет данных",
        ),
        patch(
            "src.interfaces.telegram.machines.workspace_getter.last_loading_line_for_machine",
            return_value="📦 Последняя загрузка: нет данных",
        ),
    ):
        payload = build_workspace_payload(
            deps,
            dialog_manager=manager,
            bot_user=_bot_user(),
            machine_id=_MACHINE,
        )

    assert payload["micromarket_inventory_available"] is True
    assert payload["show_coffee_revision"] is False
    assert payload["show_coffee_loading"] is False
    assert payload["show_snack_inventory"] is False
    assert payload["snack_inventory_available"] is False


def _planogram_with_sku() -> tuple[
    FakeDomainProductStore,
    InMemoryMicromarketPlanogramStore,
    InMemoryMicromarketDeviceStockStore,
]:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    product = create_domain_product("Молоко", store=store, lookup=lookup)
    planogram_store = InMemoryMicromarketPlanogramStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    planogram_store.upsert(
        MicromarketPlanogram(
            machine_code=_MACHINE.value,
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
            updated_at=_ISSUED_AT,
            shelves=(MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),),
        )
    )
    return store, planogram_store, stock_store


def test_workspace_payload_provisions_inventory_url_without_second_message() -> None:
    """happy: getter puts form URL on workspace for Url button (no second chat message)."""
    products, planogram_store, stock_store = _planogram_with_sku()
    deps = MagicMock()
    deps.service_display_timezone = ZoneInfo("UTC")
    deps.get_service_capabilities.execute.return_value = _caps()
    deps.issue_snack_inventory_link = None
    deps.snack_inventory_cells = None
    deps.issue_micromarket_inventory_link = _issue_uc()
    deps.micromarket_planogram_store = planogram_store
    deps.micromarket_stock_store = stock_store
    deps.domain_product_store = products
    deps.machine_kind_lookup = StaticMachineKindLookup(
        {_MACHINE.value: MachineKind.MICRO_MARKET},
    )
    manager = MagicMock()
    manager.dialog_data = {"machine_id": _MACHINE.value, "machine_name": "MM 701"}

    from src.interfaces.telegram.machines.maintenance_screen import MaintenanceScreenFlags

    with (
        patch(
            "src.interfaces.telegram.machines.workspace_getter.maintenance_screen_flags",
            return_value=MaintenanceScreenFlags(
                loading_completed=False,
                can_complete_maintenance=True,
                show_maintenance_back=False,
            ),
        ),
        patch(
            "src.interfaces.telegram.machines.workspace_getter.last_service_line_for_machine",
            return_value="🛠️ Последнее обслуживание: нет данных",
        ),
        patch(
            "src.interfaces.telegram.machines.workspace_getter.last_loading_line_for_machine",
            return_value="📦 Последняя загрузка: нет данных",
        ),
    ):
        payload = build_workspace_payload(
            deps,
            dialog_manager=manager,
            bot_user=_bot_user(),
            machine_id=_MACHINE,
        )

    assert payload["micromarket_inventory_clickable"] is True
    assert payload["micromarket_inventory_has_url"] is True
    url = manager.dialog_data.get("micromarket_inventory_form_url")
    assert isinstance(url, str)
    assert url.startswith(f"{_FIELD_BASE}/forms/micromarket-inventory/now?")
    assert "token=" in url
    assert "micromarket_inventory_issue_error" not in manager.dialog_data


def test_workspace_payload_no_sku_sets_issue_error_without_url() -> None:
    """edge: empty SKU → no Url; click path can alert from dialog_data."""
    deps = MagicMock()
    deps.service_display_timezone = ZoneInfo("UTC")
    deps.get_service_capabilities.execute.return_value = _caps()
    deps.issue_snack_inventory_link = None
    deps.snack_inventory_cells = None
    deps.issue_micromarket_inventory_link = _issue_uc()
    deps.micromarket_planogram_store = InMemoryMicromarketPlanogramStore()
    deps.micromarket_stock_store = InMemoryMicromarketDeviceStockStore()
    deps.domain_product_store = FakeDomainProductStore()
    deps.machine_kind_lookup = StaticMachineKindLookup(
        {_MACHINE.value: MachineKind.MICRO_MARKET},
    )
    manager = MagicMock()
    manager.dialog_data = {"machine_id": _MACHINE.value, "machine_name": "MM 701"}

    from src.interfaces.telegram.machines.maintenance_screen import MaintenanceScreenFlags

    with (
        patch(
            "src.interfaces.telegram.machines.workspace_getter.maintenance_screen_flags",
            return_value=MaintenanceScreenFlags(
                loading_completed=False,
                can_complete_maintenance=True,
                show_maintenance_back=False,
            ),
        ),
        patch(
            "src.interfaces.telegram.machines.workspace_getter.last_service_line_for_machine",
            return_value="🛠️ Последнее обслуживание: нет данных",
        ),
        patch(
            "src.interfaces.telegram.machines.workspace_getter.last_loading_line_for_machine",
            return_value="📦 Последняя загрузка: нет данных",
        ),
    ):
        payload = build_workspace_payload(
            deps,
            dialog_manager=manager,
            bot_user=_bot_user(),
            machine_id=_MACHINE,
        )

    assert payload["micromarket_inventory_clickable"] is True
    assert payload["micromarket_inventory_has_url"] is False
    assert manager.dialog_data.get("micromarket_inventory_issue_error") == (
        NO_MICROMARKET_SKU_MESSAGE
    )
