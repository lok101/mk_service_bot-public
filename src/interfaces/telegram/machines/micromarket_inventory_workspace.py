from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from beartype import beartype

from src.application.micromarket_loading.inventory_form_pages import (
    InventoryFormPage,
    build_micromarket_inventory_form_pages,
    flatten_inventory_form_page_codes,
)
from src.application.micromarket_loading.issue_inventory_link import (
    EmptyMicromarketSkuSet,
    IssuedMicromarketInventoryLink,
    IssueMicromarketInventoryLink,
)
from src.application.micromarket_loading.ports import (
    MicromarketDeviceStockStore,
    MicromarketPlanogramStore,
)
from src.application.product_identity.ports import DomainProductStore
from src.domain.ids import TechnicianId

NO_MICROMARKET_SKU_MESSAGE = "нет SKU для инвентаризации"


@beartype
def micromarket_inventory_workspace_flags(
    *,
    is_micromarket: bool,
    issuer: IssueMicromarketInventoryLink | None,
) -> dict[str, bool]:
    available = is_micromarket and issuer is not None
    return {
        "micromarket_inventory_available": available,
        "micromarket_inventory_show_stub": is_micromarket and issuer is None,
        "show_coffee_revision": not is_micromarket,
        "show_coffee_loading": not is_micromarket,
        "show_snack_inventory": not is_micromarket,
    }


@beartype
def resolve_micromarket_inventory_form_pages(
    *,
    machine_code: str,
    planogram_store: MicromarketPlanogramStore,
    stock_store: MicromarketDeviceStockStore,
    products: DomainProductStore | None = None,
    kit_group_names: Mapping[int, str] | None = None,
) -> tuple[InventoryFormPage, ...]:
    planogram = planogram_store.get(machine_code)
    stock = stock_store.load(machine_code)
    stock_qty: dict[str, Decimal] = stock.quantities() if stock is not None else {}
    return build_micromarket_inventory_form_pages(
        planogram=planogram,
        stock_qty=stock_qty,
        products=products,
        kit_group_names=kit_group_names,
    )


@beartype
def resolve_micromarket_inventory_sku_codes(
    *,
    machine_code: str,
    planogram_store: MicromarketPlanogramStore,
    stock_store: MicromarketDeviceStockStore,
    products: DomainProductStore | None = None,
    kit_group_names: Mapping[int, str] | None = None,
) -> list[str]:
    pages = resolve_micromarket_inventory_form_pages(
        machine_code=machine_code,
        planogram_store=planogram_store,
        stock_store=stock_store,
        products=products,
        kit_group_names=kit_group_names,
    )
    return list(flatten_inventory_form_page_codes(pages))


@beartype
def issue_micromarket_inventory_now_link(
    *,
    machine_code: str,
    technician_id: TechnicianId,
    issuer: IssueMicromarketInventoryLink,
    pages: Sequence[InventoryFormPage],
) -> IssuedMicromarketInventoryLink | str:
    result = issuer.execute(
        machine_code=machine_code,
        mode="now",
        pages=pages,
        technician_id=technician_id,
    )
    if isinstance(result, EmptyMicromarketSkuSet):
        return result.message or NO_MICROMARKET_SKU_MESSAGE
    return result
