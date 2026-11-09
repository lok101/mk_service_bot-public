from __future__ import annotations

from decimal import Decimal, InvalidOperation

from beartype import beartype
from fastapi import Request

from src.application.form_inventory_policy import (
    COFFEE_LOADING_PROFILE_ID,
    COFFEE_POLICY_PROFILE_IDS,
    FormInventoryPolicyLine,
    FormInventoryPolicyProfileId,
    FormInventoryPolicyStore,
)
from src.application.product_identity import DomainProduct, catalog_codes_of
from src.application.product_identity.ports import DomainProductStore
from src.application.reference_data import MsEntityKind
from src.domain.product_catalog import ProductUnit
from src.domain.quantities import QuantityInputMode
from src.domain.system_user import AdminPanel
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import session_user_id, user_has_panel

COFFEE_INGREDIENTS_HREF = "/admin/coffee-ingredients"
_UNIT_BY_FORM = {
    "g": ProductUnit.GRAM,
    "gram": ProductUnit.GRAM,
    "гр": ProductUnit.GRAM,
    "kg": ProductUnit.KILOGRAM,
    "кг": ProductUnit.KILOGRAM,
    "ml": ProductUnit.MILLILITER,
    "мл": ProductUnit.MILLILITER,
    "pc": ProductUnit.PIECE,
    "шт": ProductUnit.PIECE,
}
_UNIT_LABEL = {
    ProductUnit.GRAM: "г",
    ProductUnit.KILOGRAM: "кг",
    ProductUnit.MILLILITER: "мл",
    ProductUnit.PIECE: "шт",
}

__all__ = [
    "COFFEE_INGREDIENTS_HREF",
    "parse_unit_field",
    "parse_pack_size_field",
    "parse_create_policy_fields",
    "unit_form_key",
    "ingredient_row",
    "ingredient_editor_view",
    "policy_profile_id",
    "policy_qty_unit_label",
    "policy_show_radio",
    "ingredient_names_by_number",
    "actor_has_panel",
    "ms_catalog_names",
]


@beartype
def parse_unit_field(raw: str) -> ProductUnit | None:
    return _UNIT_BY_FORM.get(raw.strip().casefold())


@beartype
def parse_pack_size_field(raw: str) -> Decimal | None:
    trimmed = raw.strip().replace(",", ".")
    if not trimmed:
        return None
    try:
        value = Decimal(trimmed)
    except InvalidOperation:
        return None
    return value


@beartype
def unit_form_key(unit: ProductUnit | None) -> str:
    if unit is None:
        return ""
    for key, value in _UNIT_BY_FORM.items():
        if value is unit and key.isascii():
            return key
    return ""


@beartype
def ingredient_row(product: DomainProduct) -> dict[str, str]:
    return {
        "id": product.domain_product_id,
        "number": product.number,
        "name": product.name,
        "codes": ", ".join(catalog_codes_of(product)),
        "unit": _UNIT_LABEL.get(product.unit, "") if product.unit is not None else "",
        "unit_key": unit_form_key(product.unit),
        "pack_size": str(product.pack_size) if product.pack_size is not None else "",
    }


@beartype
def ingredient_editor_view(
    product: DomainProduct | None,
    *,
    catalog_names: dict[str, str],
    policy_store: FormInventoryPolicyStore | None,
) -> dict[str, object]:
    _ = policy_store
    if product is None:
        return {
            "is_new": True,
            "domain_product_id": "",
            "number": "—",
            "name": "",
            "unit_key": "g",
            "pack_size": "",
            "loading_radio_n": "10",
            "revision_min_qty": "0",
            "revision_max_qty": "",
            "warehouse_min_qty": "0",
            "warehouse_max_qty": "",
            "links": (),
        }
    links = tuple(
        {"code": code, "name": catalog_names.get(code, "")}
        for code in catalog_codes_of(product)
    )
    return {
        "is_new": False,
        "domain_product_id": product.domain_product_id,
        "number": product.number,
        "name": product.name,
        "unit_key": unit_form_key(product.unit) or "g",
        "pack_size": str(product.pack_size) if product.pack_size is not None else "",
        "links": links,
    }


@beartype
def parse_create_policy_fields(
    fields: dict[str, str],
) -> tuple[FormInventoryPolicyLine, FormInventoryPolicyLine, FormInventoryPolicyLine] | None:
    radio_raw = fields.get("loading_radio_n", "").strip()
    if not radio_raw.isdigit():
        return None
    radio_n = int(radio_raw)
    revision_min = parse_pack_size_field(fields.get("revision_min_qty", ""))
    revision_max = parse_pack_size_field(fields.get("revision_max_qty", ""))
    warehouse_min = parse_pack_size_field(fields.get("warehouse_min_qty", ""))
    warehouse_max = parse_pack_size_field(fields.get("warehouse_max_qty", ""))
    if (
        revision_min is None
        or revision_max is None
        or warehouse_min is None
        or warehouse_max is None
    ):
        return None
    placeholder = "pending"
    return (
        FormInventoryPolicyLine(
            domain_number=placeholder,
            min_qty=Decimal("0"),
            max_qty=Decimal(radio_n),
            radio_n=radio_n,
        ),
        FormInventoryPolicyLine(
            domain_number=placeholder,
            min_qty=revision_min,
            max_qty=revision_max,
        ),
        FormInventoryPolicyLine(
            domain_number=placeholder,
            min_qty=warehouse_min,
            max_qty=warehouse_max,
        ),
    )


@beartype
def policy_profile_id(raw: str) -> FormInventoryPolicyProfileId:
    for profile_id in COFFEE_POLICY_PROFILE_IDS:
        if profile_id == raw:
            return profile_id
    return COFFEE_LOADING_PROFILE_ID


@beartype
def policy_qty_unit_label(input_mode: str) -> str:
    if input_mode == QuantityInputMode.BASE_STOCK.value:
        return "г"
    return "уп."


@beartype
def policy_show_radio(profile_id: FormInventoryPolicyProfileId) -> bool:
    return profile_id == COFFEE_LOADING_PROFILE_ID


@beartype
def ingredient_names_by_number(store: DomainProductStore) -> dict[str, str]:
    names: dict[str, str] = {}
    for number in store.numbers():
        product = store.get_by_number(number)
        if product is None or product.kind != "coffee_ingredient":
            continue
        names[product.number] = product.name
    return names


@beartype
def actor_has_panel(request: Request, deps: AdminHttpDeps, panel: AdminPanel) -> bool:
    user_id = session_user_id(request, deps)
    if user_id is None:
        return False
    return user_has_panel(deps, user_id, panel)


@beartype
def ms_catalog_names(deps: AdminHttpDeps) -> dict[str, str]:
    catalog = deps.provider.product_catalog_or_none()
    if catalog is None:
        return {}
    return {
        code: entry.name
        for code, entry in catalog.by_code.items()
        if entry.entity_kind is MsEntityKind.PRODUCT
    }
