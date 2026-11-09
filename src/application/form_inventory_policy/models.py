from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from beartype import beartype

from src.domain.quantities import QuantityInputMode

FormInventoryPolicyProfileId = Literal[
    "coffee_loading",
    "coffee_revision",
    "technician_warehouse_coffee",
]

COFFEE_LOADING_PROFILE_ID: FormInventoryPolicyProfileId = "coffee_loading"
COFFEE_REVISION_PROFILE_ID: FormInventoryPolicyProfileId = "coffee_revision"
TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID: FormInventoryPolicyProfileId = "technician_warehouse_coffee"

COFFEE_POLICY_PROFILE_IDS: tuple[FormInventoryPolicyProfileId, ...] = (
    COFFEE_LOADING_PROFILE_ID,
    COFFEE_REVISION_PROFILE_ID,
    TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID,
)


@beartype
@dataclass(frozen=True, slots=True)
class FormInventoryPolicyProfile:
    profile_id: FormInventoryPolicyProfileId
    input_mode: QuantityInputMode
    allow_zero: bool
    apply_stock_range: bool
    allow_empty: bool


@beartype
@dataclass(frozen=True, slots=True)
class FormInventoryPolicyLine:
    domain_number: str
    min_qty: Decimal
    max_qty: Decimal
    radio_n: int | None = None
    sort_order: int = 0
    form_label: str = ""
    form_hint: str = ""


DEFAULT_COFFEE_PROFILES: tuple[FormInventoryPolicyProfile, ...] = (
    FormInventoryPolicyProfile(
        profile_id=COFFEE_LOADING_PROFILE_ID,
        input_mode=QuantityInputMode.PACKAGE_COUNT,
        allow_zero=True,
        apply_stock_range=True,
        allow_empty=False,
    ),
    FormInventoryPolicyProfile(
        profile_id=COFFEE_REVISION_PROFILE_ID,
        input_mode=QuantityInputMode.BASE_STOCK,
        allow_zero=True,
        apply_stock_range=True,
        allow_empty=True,
    ),
    FormInventoryPolicyProfile(
        profile_id=TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID,
        input_mode=QuantityInputMode.PACKAGE_COUNT,
        allow_zero=True,
        apply_stock_range=True,
        allow_empty=True,
    ),
)
